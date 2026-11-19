"""A BOM line's free-text unit is read, never taken for the stock unit.

A formula line said "Wheat flour 300 g" in text and named no unit id, while
the ingredient was stocked in pieces. The explosion labelled the bare number
with the stock unit, so two batches drew 600 pcs off the shelf and the batch
record said "600 pcs": the line's grams had silently become pieces. The same
hole accepted "1 cup" beside a stock of kilograms.

The line's text now names a unit the way a unit id does: the catalogue
resolves it (aliases included), a save refuses one the ingredient's stock
cannot be read in, and a run whose line predates the check converts the
quantity or refuses before drawing anything. The composition tab marks such
a line, so a mismatch already stored is fixed before its next run.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ShelfRow
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.modules.maker.models import BoMLine, MakerRecipe
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration

RECIPES = '/api/v1/maker/recipes'
ORDERS = '/api/v1/maker/production/orders'


def _uom(db: Session, symbol: str) -> Uom:
    uom = db.scalars(select(Uom).where(Uom.symbol == symbol)).first()
    assert uom is not None, f'the seed has no {symbol!r} unit'
    return uom


def _template(
    db: Session, org: Organization, *, name: str, uom_id: UUID | None = None
) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id,
        name=name,
        sku=f'SKU-{uuid.uuid4().hex[:8]}',
        uom_id=uom_id,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def _recipe(
    db: Session,
    org: Organization,
    output_id: UUID,
    *,
    batch_yield: str = '1',
) -> MakerRecipe:
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=output_id,
        name='One line',
        batch_yield_qty=Decimal(batch_yield),
        is_default=True,
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return recipe


def _stored_line(
    db: Session,
    org: Organization,
    *,
    recipe: MakerRecipe,
    child_id: UUID,
    qty: str,
    unit: str,
    uom_id: UUID | None = None,
) -> BoMLine:
    """A line written straight into the table, as one saved before the check."""
    line = BoMLine(
        organization_id=org.id,
        recipe_id=recipe.id,
        parent_template_id=recipe.output_template_id,
        child_template_id=child_id,
        qty_per_batch=Decimal(qty),
        unit=unit,
        uom_id=uom_id,
    )
    db.add(line)
    db.commit()
    db.refresh(line)
    return line


def _add_line(
    client: TestClient,
    headers: dict[str, str],
    recipe_id: UUID,
    child_id: UUID,
    *,
    qty: str = '1',
    unit: str = 'g',
    uom_id: UUID | None = None,
) -> Response:
    body: dict[str, object] = {
        'child_template_id': str(child_id),
        'qty_per_batch': qty,
        'unit': unit,
    }
    if uom_id is not None:
        body['uom_id'] = str(uom_id)
    return client.post(f'{RECIPES}/{recipe_id}/bom-lines', headers=headers, json=body)


def _detail(client: TestClient, headers: dict[str, str], recipe_id: UUID) -> Any:
    response = client.get(f'{RECIPES}/{recipe_id}', headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _run(
    client: TestClient,
    headers: dict[str, str],
    output_id: UUID,
    output_loc: StorageLocation,
    planned_qty: str = '1',
) -> Response:
    created = client.post(
        ORDERS,
        headers=headers,
        json={
            'output_template_id': str(output_id),
            'planned_qty': planned_qty,
            'output_location_id': str(output_loc.id),
            # WARN is the default strategy: an unmeasurable line is warned
            # about at creation and the run is confirmed by the person anyway.
            # Completion is where this test reads the verdict.
            'confirm_shortage': True,
        },
    )
    assert created.status_code == 201, created.text
    return client.post(f'{ORDERS}/{created.json()["id"]}/complete', headers=headers)


def _on_shelf(db: Session, template_id: UUID) -> Decimal:
    row = db.scalars(
        select(ShelfRow).where(ShelfRow.product_template_id == template_id)
    ).first()
    assert row is not None, 'the ingredient is gone from the shelf'
    return Decimal(str(row.quantity))


class TestSavingALineWhoseUnitCannotBeRead:
    def test_grams_against_stock_in_pieces_are_refused_naming_both_units(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        pcs = _uom(db_session, 'pcs')
        output = _template(db_session, mk_org, name='Bread')
        flour = _template(db_session, mk_org, name='Wheat flour', uom_id=pcs.id)
        recipe = _recipe(db_session, mk_org, output.id, batch_yield='12')

        response = _add_line(
            client, mk_auth_headers, recipe.id, flour.id, qty='300', unit='g'
        )

        assert response.status_code == 400, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'BOM_LINE_UNIT_NOT_CONVERTIBLE'
        assert 'pcs' in detail['message']
        assert 'g' in detail['message']

    def test_a_unit_the_catalogue_does_not_know_is_refused(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """A number labelled in something no unit table holds cannot be read."""
        pcs = _uom(db_session, 'pcs')
        output = _template(db_session, mk_org, name='Bread')
        flour = _template(db_session, mk_org, name='Wheat flour', uom_id=pcs.id)
        recipe = _recipe(db_session, mk_org, output.id)

        response = _add_line(
            client, mk_auth_headers, recipe.id, flour.id, qty='1', unit='cup'
        )

        assert response.status_code == 400, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'BOM_LINE_UNIT_NOT_CONVERTIBLE'
        assert 'cup' in detail['message']
        assert 'pcs' in detail['message']

    def test_a_unit_that_converts_is_accepted(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        kg = _uom(db_session, 'kg')
        output = _template(db_session, mk_org, name='Bread')
        flour = _template(db_session, mk_org, name='Wheat flour', uom_id=kg.id)
        recipe = _recipe(db_session, mk_org, output.id)

        response = _add_line(
            client, mk_auth_headers, recipe.id, flour.id, qty='500', unit='g'
        )

        assert response.status_code == 201, response.text

    def test_the_text_that_names_the_stock_unit_needs_no_id(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """A line saying "pcs" beside stock in pieces is the stock unit itself."""
        pcs = _uom(db_session, 'pcs')
        output = _template(db_session, mk_org, name='Bread')
        flour = _template(db_session, mk_org, name='Wheat flour', uom_id=pcs.id)
        recipe = _recipe(db_session, mk_org, output.id)

        response = _add_line(
            client, mk_auth_headers, recipe.id, flour.id, qty='2', unit='pcs'
        )

        assert response.status_code == 201, response.text


class TestAStoredLineStopsTheRun:
    def test_a_line_in_grams_against_stock_in_pieces_is_refused_before_the_draw(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """A row found in the field: 300 g a batch, stock in pieces, two batches.

        Before the check the run took 600 pieces and the record said "600 pcs".
        Now the run refuses with the line that cannot be measured, and the
        shelf keeps every piece it had.
        """
        pcs = _uom(db_session, 'pcs')
        output = _template(db_session, mk_org, name='Rye bread')
        flour = _template(db_session, mk_org, name='Wheat flour', uom_id=pcs.id)
        recipe = _recipe(db_session, mk_org, output.id, batch_yield='12')
        _stored_line(
            db_session,
            mk_org,
            recipe=recipe,
            child_id=flour.id,
            qty='300',
            unit='g',
        )
        post_on_shelf(client, mk_auth_headers, flour, mk_input_loc.id, '7000')

        completed = _run(
            client,
            mk_auth_headers,
            output.id,
            mk_output_loc,
            planned_qty='24',
        )

        assert completed.status_code == 422, completed.text
        [shortage] = completed.json()['detail']['shortages']
        assert shortage['child_template_name'] == 'Wheat flour'
        assert shortage['convertible'] is False
        assert shortage['shortage'] is None
        assert _on_shelf(db_session, flour.id) == Decimal('7000')

    def test_a_convertible_line_draws_the_converted_amount(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """500 g a batch of stock kept in kilograms takes a kilogram for two."""
        kg = _uom(db_session, 'kg')
        output = _template(db_session, mk_org, name='Rye bread')
        flour = _template(db_session, mk_org, name='Wheat flour', uom_id=kg.id)
        recipe = _recipe(db_session, mk_org, output.id)
        _stored_line(
            db_session,
            mk_org,
            recipe=recipe,
            child_id=flour.id,
            qty='500',
            unit='g',
        )
        post_on_shelf(client, mk_auth_headers, flour, mk_input_loc.id, '2')

        completed = _run(
            client,
            mk_auth_headers,
            output.id,
            mk_output_loc,
            planned_qty='2',
        )

        assert completed.status_code == 200, completed.text
        order = client.get(
            f'{ORDERS}/{completed.json()["id"]}', headers=mk_auth_headers
        ).json()
        [line] = order['lines']
        assert line['child_template_name'] == 'Wheat flour'
        assert Decimal(line['consumed_qty']) == Decimal('1')
        assert line['unit'] == 'kg'
        assert _on_shelf(db_session, flour.id) == Decimal('1')


class TestTheCompositionTabAsksForAUnit:
    def test_a_mismatched_line_is_marked_and_a_convertible_one_is_not(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        pcs = _uom(db_session, 'pcs')
        kg = _uom(db_session, 'kg')
        output = _template(db_session, mk_org, name='Rye bread')
        flour = _template(db_session, mk_org, name='Wheat flour', uom_id=pcs.id)
        recipe = _recipe(db_session, mk_org, output.id)
        _stored_line(
            db_session,
            mk_org,
            recipe=recipe,
            child_id=flour.id,
            qty='300',
            unit='g',
        )
        salt = _template(db_session, mk_org, name='Salt', uom_id=kg.id)
        _stored_line(
            db_session,
            mk_org,
            recipe=recipe,
            child_id=salt.id,
            qty='20',
            unit='g',
        )

        lines = _detail(client, mk_auth_headers, recipe.id)['lines']

        marked = {line['child_template_name']: line['unit_mismatch'] for line in lines}
        assert marked == {'Wheat flour': True, 'Salt': False}

    def test_choosing_a_unit_clears_the_mismatch(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        pcs = _uom(db_session, 'pcs')
        output = _template(db_session, mk_org, name='Rye bread')
        flour = _template(db_session, mk_org, name='Wheat flour', uom_id=pcs.id)
        recipe = _recipe(db_session, mk_org, output.id)
        line = _stored_line(
            db_session,
            mk_org,
            recipe=recipe,
            child_id=flour.id,
            qty='300',
            unit='g',
        )

        patched = client.patch(
            f'{RECIPES}/{recipe.id}/bom-lines/{line.id}',
            headers=mk_auth_headers,
            json={'uom_id': str(pcs.id)},
        )

        assert patched.status_code == 200, patched.text
        [read] = _detail(client, mk_auth_headers, recipe.id)['lines']
        assert read['unit_mismatch'] is False
        # The free text followed the unit that is now structural: the row
        # cannot show grams beside a number the shelf reads in pieces.
        assert read['unit'] == 'pcs'

    def test_editing_the_quantity_in_the_old_unit_is_refused(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """An edit is a save: it may not keep a unit the shelf cannot read."""
        pcs = _uom(db_session, 'pcs')
        output = _template(db_session, mk_org, name='Rye bread')
        flour = _template(db_session, mk_org, name='Wheat flour', uom_id=pcs.id)
        recipe = _recipe(db_session, mk_org, output.id)
        line = _stored_line(
            db_session,
            mk_org,
            recipe=recipe,
            child_id=flour.id,
            qty='300',
            unit='g',
        )

        patched = client.patch(
            f'{RECIPES}/{recipe.id}/bom-lines/{line.id}',
            headers=mk_auth_headers,
            json={'qty_per_batch': '400'},
        )

        assert patched.status_code == 400, patched.text
        detail = patched.json()['detail']
        assert detail['code'] == 'BOM_LINE_UNIT_NOT_CONVERTIBLE'
        assert 'g' in detail['message']
        assert 'pcs' in detail['message']
