"""The unit guard reads the shelf, not just the catalogue row.

``_refuse_unconvertible_unit`` went silent whenever the ingredient's
template carried no unit and claimed the silence covered "products
predating units". After the piece backfill every item row carries a unit,
so a unitless template's shelves hold pieces — and a line written in
kilograms against those shelves was accepted, because the guard looked
only at the template. The silence now reads the unit the product's items
actually carry and remains only where nothing knows the unit: a product
with no items at all, which is what a record predating the units world
looks like.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.modules.maker.models import MakerRecipe
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration


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


def _default_recipe(db: Session, org: Organization, output_id: UUID) -> MakerRecipe:
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=output_id,
        name='One line',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return recipe


def _add_line(
    client: TestClient,
    headers: dict[str, str],
    recipe_id: UUID,
    child: UUID,
    kg: Uom,
) -> Any:
    return client.post(
        f'/api/v1/maker/recipes/{recipe_id}/bom-lines',
        headers=headers,
        json={
            'child_template_id': str(child),
            'qty_per_batch': '1',
            'unit': 'kg',
            'uom_id': str(kg.id),
        },
    )


def _create_item_without_unit(
    client: TestClient, headers: dict[str, str], name: str, storage: StorageLocation
) -> Any:
    response = client.post(
        '/api/v1/items',
        headers=headers,
        json={
            'name': name,
            'location_id': str(storage.id),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestGuardReadsTheShelf:
    def test_a_kilogram_line_refuses_when_the_shelves_hold_pieces(
        self,
        client: TestClient,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        mk_input_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """Unitless template, items in pieces, line in kilograms → refused.

        This is the hole the silence protected: the guard compared the line
        with a template that says nothing and let the number through."""
        child = _template(db_session, mk_org, name='Bare flour')
        _create_item_without_unit(client, mk_auth_headers, 'Bare flour', mk_input_loc)
        output = _template(db_session, mk_org, name='Bare output')
        recipe = _default_recipe(db_session, mk_org, output.id)

        response = _add_line(
            client, mk_auth_headers, recipe.id, child.id, _uom(db_session, 'kg')
        )

        assert response.status_code == 400, response.text

    def test_silence_survives_where_nothing_knows_the_unit(
        self,
        client: TestClient,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """A product with no items at all keeps the old silence.

        This is what a record predating the units world looks like: the
        template says nothing and no shelf exists to contradict it. The
        narrowed guard must not close the recipe editor for it."""
        child = _template(db_session, mk_org, name='Never stocked')
        output = _template(db_session, mk_org, name='Never stocked output')
        recipe = _default_recipe(db_session, mk_org, output.id)

        response = _add_line(
            client, mk_auth_headers, recipe.id, child.id, _uom(db_session, 'kg')
        )

        assert response.status_code == 201, response.text


class TestGuardReadsTheWholeShelf:
    def test_a_hundred_newest_rows_do_not_outvote_an_older_one(
        self,
        client: TestClient,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        mk_input_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """Mixed units → the guard steps aside, whatever the page order.

        The fallback used to read a page of 100 newest rows: a product with
        a hundred piece-items and one older kilogram-item looked like a
        pieces-only shelf, and a kilogram line got refused. The verdict
        must come from the whole set — mixed means no single stock unit,
        mixed means silence.
        """
        from datetime import datetime, timedelta

        from app.models.item import Item

        child = _template(db_session, mk_org, name='Mixed shelf flour')
        output = _template(db_session, mk_org, name='Mixed shelf output')
        kg = _uom(db_session, 'kg')
        pcs = _uom(db_session, 'pcs')

        base = datetime(2026, 1, 1, 12, 0, 0)
        for i in range(101):
            db_session.add(
                Item(
                    organization_id=mk_org.id,
                    template_id=child.id,
                    name='Mixed shelf flour',
                    storage_location_id=mk_input_loc.id,
                    uom_id=kg.id if i == 0 else pcs.id,
                    quantity=1,
                    created_at=base + timedelta(minutes=i),
                )
            )
        anchor_pending_records(db_session)
        db_session.commit()

        recipe = _default_recipe(db_session, mk_org, output.id)
        response = _add_line(client, mk_auth_headers, recipe.id, child.id, kg)

        assert response.status_code == 201, response.text


class TestTheGuardGuardsTheEditToo:
    def test_patching_a_line_into_an_unreadable_unit_is_refused(
        self,
        client: TestClient,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        mk_input_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """Adding in pieces and patching to kilograms must hit the same gate.

        The guard stood only on the add path, so the refusal was
        bypassable: add the line in pieces, then PATCH the unit to
        kilograms against a shelf that holds pieces. Red before the fix:
        the patch returned 200 and the line kept unit='pcs' next to
        uom_id=kg.
        """
        child = _template(db_session, mk_org, name='Patchable flour')
        _create_item_without_unit(
            client, mk_auth_headers, 'Patchable flour', mk_input_loc
        )
        output = _template(db_session, mk_org, name='Patchable output')
        recipe = _default_recipe(db_session, mk_org, output.id)
        pcs = _uom(db_session, 'pcs')
        added = client.post(
            f'/api/v1/maker/recipes/{recipe.id}/bom-lines',
            headers=mk_auth_headers,
            json={
                'child_template_id': str(child.id),
                'qty_per_batch': '1',
                'unit': 'pcs',
                'uom_id': str(pcs.id),
            },
        )
        assert added.status_code == 201, added.text
        line_id = added.json()['id']
        kg = _uom(db_session, 'kg')

        patched = client.patch(
            f'/api/v1/maker/recipes/{recipe.id}/bom-lines/{line_id}',
            headers=mk_auth_headers,
            json={'uom_id': str(kg.id)},
        )

        assert patched.status_code == 400, patched.text


class TestItemInheritsTheTemplatesUnit:
    def test_a_kilogram_line_meets_a_kilogram_shelf(
        self,
        client: TestClient,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        mk_input_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """Template kg + item created without a unit + kg line: consistent.

        The record used to land in pieces while its catalogue row said
        kilograms, so the guard and the shelf disagreed about what the line
        meant. The record now inherits the matched template's unit before
        any line is written against it."""
        kg = _uom(db_session, 'kg')
        child = _template(db_session, mk_org, name='Kilo flour', uom_id=kg.id)
        item = _create_item_without_unit(
            client, mk_auth_headers, 'Kilo flour', mk_input_loc
        )
        output = _template(db_session, mk_org, name='Kilo output')
        recipe = _default_recipe(db_session, mk_org, output.id)

        response = _add_line(
            client, mk_auth_headers, recipe.id, child.id, _uom(db_session, 'kg')
        )

        assert response.status_code == 201, response.text
        row = db_session.scalars(select(Item).where(Item.id == UUID(item['id']))).one()
        assert row.uom_id == kg.id
