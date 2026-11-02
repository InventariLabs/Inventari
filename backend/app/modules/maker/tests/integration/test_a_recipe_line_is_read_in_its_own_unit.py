"""A recipe line saying 500 g must take 0.5 kg off a shelf kept in kilograms.

The availability check converted; the consumption path did not. It read the
quantity from a flat explosion that had dropped the line's unit on the way and
handed the bare number to the ledger, which knows nothing about units. So a
line reading 500 g against stock in kilograms passed the check — that one
converts — and then took 500 kg off the shelf. The valuation layers, the
history and every later count carried the inflated figure, and where the shelf
was too small the run failed hard against a check that had just said yes.

The error multiplies by the factor between the two units: 1000× for grams
against kilograms, 1000× for millilitres against litres.

This was the only place the application actively falsified authoritative stock,
so the test seeds a shelf that would show the difference plainly and reads what
the shelf's records hold afterwards.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
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


def _recipe_with_line(
    db: Session,
    org: Organization,
    *,
    output_id: UUID,
    child_id: UUID,
    qty: str,
    line_uom: Uom,
) -> MakerRecipe:
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

    db.add(
        BoMLine(
            organization_id=org.id,
            recipe_id=recipe.id,
            parent_template_id=output_id,
            child_template_id=child_id,
            qty_per_batch=Decimal(qty),
            uom_id=line_uom.id,
            unit=line_uom.symbol,
        )
    )
    db.commit()
    return recipe


def _run(
    client: TestClient,
    headers: dict[str, str],
    *,
    output_id: UUID,
    input_loc: StorageLocation,
    output_loc: StorageLocation,
    qty: str = '1',
) -> None:
    created = client.post(
        '/api/v1/maker/production/orders',
        headers=headers,
        json={
            'output_template_id': str(output_id),
            'planned_qty': qty,
            'input_storage_location_id': str(input_loc.id),
            'output_location_id': str(output_loc.id),
        },
    )
    assert created.status_code == 201, created.text
    order_id = created.json()['id']

    completed = client.post(
        f'/api/v1/maker/production/orders/{order_id}/complete', headers=headers
    )
    assert completed.status_code == 200, completed.text


def _remaining(db: Session, template_id: UUID) -> Decimal:
    row = db.scalars(
        select(ShelfRow).where(ShelfRow.product_template_id == template_id)
    ).first()
    assert row is not None, 'the ingredient is gone from the shelf'
    return Decimal(str(row.quantity))


@pytest.mark.parametrize(
    ('line_symbol', 'stock_symbol', 'line_qty', 'on_shelf', 'left'),
    [
        ('g', 'kg', '500', '2.000', Decimal('1.500')),
        ('ml', 'l', '250', '2.000', Decimal('1.750')),
        ('kg', 'kg', '0.5', '2.000', Decimal('1.500')),
    ],
    ids=['grams-against-kilograms', 'millilitres-against-litres', 'same-unit'],
)
def test_the_shelf_loses_what_the_line_asks_for(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
    line_symbol: str,
    stock_symbol: str,
    line_qty: str,
    on_shelf: str,
    left: Decimal,
) -> None:
    stock_uom = _uom(db_session, stock_symbol)
    line_uom = _uom(db_session, line_symbol)

    ingredient = _template(db_session, mk_org, name='Ingredient', uom_id=stock_uom.id)
    output = _template(db_session, mk_org, name='Output')
    _recipe_with_line(
        db_session,
        mk_org,
        output_id=output.id,
        child_id=ingredient.id,
        qty=line_qty,
        line_uom=line_uom,
    )
    post_on_shelf(client, mk_auth_headers, ingredient, mk_input_loc.id, on_shelf)

    _run(
        client,
        mk_auth_headers,
        output_id=output.id,
        input_loc=mk_input_loc,
        output_loc=mk_output_loc,
    )

    assert _remaining(db_session, ingredient.id) == left


def test_a_line_in_an_unreadable_unit_is_refused_when_written(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    db_session: Session,
) -> None:
    """Grams against pieces, with nothing saying what a piece weighs.

    Cycles and self-reference were checked when a line was written; units were
    not, so the recipe could hold a quantity nothing downstream could act on.
    """
    pieces = _uom(db_session, 'pcs')
    grams = _uom(db_session, 'g')

    ingredient = _template(db_session, mk_org, name='Jars', uom_id=pieces.id)
    output = _template(db_session, mk_org, name='Candle')

    recipe = MakerRecipe(
        organization_id=mk_org.id,
        output_template_id=output.id,
        name='Candle recipe',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db_session.add(recipe)
    db_session.commit()
    db_session.refresh(recipe)

    response = client.post(
        f'/api/v1/maker/recipes/{recipe.id}/bom-lines',
        headers=mk_auth_headers,
        json={
            'child_template_id': str(ingredient.id),
            'qty_per_batch': '400',
            'uom_id': str(grams.id),
            'unit': 'g',
        },
    )

    assert response.status_code == 400, response.text
    assert 'pcs' in response.text
