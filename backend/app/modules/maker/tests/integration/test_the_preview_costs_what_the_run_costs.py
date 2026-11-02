"""A line reading 500 g must be costed as half a kilogram, not five hundred.

Consumption learned to convert; the numbers shown beside it did not. The cost
preview and the per-ingredient breakdown took the quantity in the recipe
line's unit and multiplied it by a rate held per stock unit, so a formula
written in grams against a shelf kept in kilograms came out a thousand times
too expensive — and the run it was previewing took the right amount off the
shelf and posted the right cost, so the two disagreed about the same batch.

The conversion had been a second step the caller was expected to remember.
It is part of the explosion now, so the question "in what unit is this
number" has one answer for everything downstream of a formula.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.modules.maker.models import BoMLine, MakerRecipe
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration

#: 20.00 per kilogram, and the formula asks for half of one.
RATE_PER_KG = Decimal('20.00')
EXPECTED_COST = Decimal('10.00')


def _uom(db: Session, symbol: str) -> Uom:
    uom = db.scalars(select(Uom).where(Uom.symbol == symbol)).first()
    assert uom is not None, f'the seed has no {symbol!r} unit'
    return uom


def _template(
    db: Session, org: Organization, name: str, uom_id: UUID | None = None
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


@pytest.fixture
def half_a_kilo_written_in_grams(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    db_session: Session,
    mk_org: Organization,
    mk_input_loc: StorageLocation,
) -> tuple[ProductTemplate, ProductTemplate]:
    """An ingredient kept in kilograms, asked for in grams."""
    kg = _uom(db_session, 'kg')
    g = _uom(db_session, 'g')
    ingredient = _template(db_session, mk_org, 'Flour', uom_id=kg.id)
    output = _template(db_session, mk_org, 'Loaf')

    recipe = MakerRecipe(
        organization_id=mk_org.id,
        output_template_id=output.id,
        name='One loaf',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db_session.add(recipe)
    db_session.commit()
    db_session.refresh(recipe)
    db_session.add(
        BoMLine(
            organization_id=mk_org.id,
            recipe_id=recipe.id,
            parent_template_id=output.id,
            child_template_id=ingredient.id,
            qty_per_batch=Decimal('500'),
            uom_id=g.id,
            unit=g.symbol,
        )
    )
    db_session.commit()
    post_on_shelf(
        client,
        mk_auth_headers,
        ingredient,
        mk_input_loc.id,
        50,
        purchase_price=RATE_PER_KG,
    )
    return ingredient, output


def test_the_preview_costs_half_a_kilogram(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    half_a_kilo_written_in_grams: tuple[ProductTemplate, ProductTemplate],
) -> None:
    _ingredient, output = half_a_kilo_written_in_grams

    resp = client.get(
        f'/api/v1/maker/breakdown/{output.id}',
        headers=mk_auth_headers,
        params={'qty': '1'},
    )
    assert resp.status_code == 200, resp.text
    assert Decimal(str(resp.json()['total_cost'])) == EXPECTED_COST


def test_the_breakdown_row_adds_up_in_the_unit_it_shows(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    half_a_kilo_written_in_grams: tuple[ProductTemplate, ProductTemplate],
) -> None:
    """`unit_cost` x `consumed_qty` = `cost`, in the unit printed beside them."""
    _ingredient, output = half_a_kilo_written_in_grams

    resp = client.get(
        f'/api/v1/maker/breakdown/{output.id}',
        headers=mk_auth_headers,
        params={'qty': '1'},
    )
    assert resp.status_code == 200, resp.text
    (row,) = resp.json()['entries']
    assert row['unit'] == 'kg'
    assert Decimal(str(row['consumed_qty'])) == Decimal('0.5')
    assert Decimal(str(row['cost'])) == EXPECTED_COST


def test_the_run_posts_what_the_preview_promised(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
    half_a_kilo_written_in_grams: tuple[ProductTemplate, ProductTemplate],
) -> None:
    """The preview and the completed run answer the same number."""
    _ingredient, output = half_a_kilo_written_in_grams

    preview = client.get(
        f'/api/v1/maker/breakdown/{output.id}',
        headers=mk_auth_headers,
        params={'qty': '1'},
    )
    assert preview.status_code == 200, preview.text

    created = client.post(
        '/api/v1/maker/production/orders',
        headers=mk_auth_headers,
        json={
            'output_template_id': str(output.id),
            'planned_qty': '1',
            'input_storage_location_id': str(mk_input_loc.id),
            'output_location_id': str(mk_output_loc.id),
        },
    )
    assert created.status_code == 201, created.text
    completed = client.post(
        f'/api/v1/maker/production/orders/{created.json()["id"]}/complete',
        headers=mk_auth_headers,
    )
    assert completed.status_code == 200, completed.text

    db_session.expire_all()
    layer = db_session.scalars(
        select(StockValuationLayer).where(
            StockValuationLayer.product_template_id == output.id,
            StockValuationLayer.direction == 'IN',
        )
    ).first()
    assert layer is not None
    assert Decimal(str(layer.unit_cost)) == EXPECTED_COST
    assert Decimal(str(preview.json()['total_cost'])) == Decimal(str(layer.unit_cost))
