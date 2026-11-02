"""A production run takes its ingredients off the cost ledger too.

The run raised a layer for the goods it made and never lowered one for the
goods it ate. Consumption goes straight to the quants
(``stock_consumption.consume_across_locations``), and the mirror onto
``Item.quantity`` turned the record's own posting off, which skipped the
outflow it would have posted — so ``record_delivery_async`` was never
reached from anywhere in the module. The ingredients stayed on the books with
their full remaining quantity while the finished goods were added beside them,
and every run made the warehouse worth more than it was: the same stock
counted twice, once as flour and once as bread.

The output is valued at what the ingredients actually cost, not at the average
of the layers standing at the time. That is what a manufacturing order does in
Odoo and ERPNext, and after the outflow is posted at its FIFO cost the two
figures are no longer the same number.
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
from app.modules.maker.models import BoMLine, MakerRecipe
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration


def _template(db: Session, org: Organization, name: str) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id,
        name=name,
        sku=f'SKU-{uuid.uuid4().hex[:8]}',
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def _recipe(
    db: Session, org: Organization, *, output_id: UUID, child_id: UUID
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
            qty_per_batch=Decimal('1'),
            unit='pcs',
        )
    )
    db.commit()
    return recipe


def _layers(
    db: Session, template_id: UUID, direction: str
) -> list[StockValuationLayer]:
    db.expire_all()
    return list(
        db.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.product_template_id == template_id,
                StockValuationLayer.direction == direction,
            )
        ).all()
    )


def _stock_value(db: Session, org: Organization) -> Decimal:
    """What the layers say the shelves are worth."""
    db.expire_all()
    rows = db.scalars(
        select(StockValuationLayer).where(
            StockValuationLayer.organization_id == org.id,
            StockValuationLayer.direction == 'IN',
        )
    ).all()
    return sum((row.remaining_qty * row.unit_cost for row in rows), Decimal('0'))


def _complete_a_run(
    client: TestClient,
    headers: dict[str, str],
    *,
    output_id: UUID,
    input_loc: StorageLocation,
    output_loc: StorageLocation,
    planned: str = '2',
) -> None:
    created = client.post(
        '/api/v1/maker/production/orders',
        headers=headers,
        json={
            'output_template_id': str(output_id),
            'planned_qty': planned,
            'input_storage_location_id': str(input_loc.id),
            'output_location_id': str(output_loc.id),
        },
    )
    assert created.status_code == 201, created.text
    completed = client.post(
        f'/api/v1/maker/production/orders/{created.json()["id"]}/complete',
        headers=headers,
    )
    assert completed.status_code == 200, completed.text


def _one_priced_ingredient(
    client: TestClient,
    headers: dict[str, str],
    db: Session,
    org: Organization,
    input_loc: StorageLocation,
) -> tuple[ProductTemplate, ProductTemplate]:
    ingredient = _template(db, org, 'Priced ingredient')
    output = _template(db, org, 'Output')
    _recipe(db, org, output_id=output.id, child_id=ingredient.id)
    post_on_shelf(client, headers, ingredient, input_loc.id, 10, purchase_price='2.00')
    return ingredient, output


def test_a_run_posts_an_outgoing_layer_for_what_it_ate(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
) -> None:
    ingredient, output = _one_priced_ingredient(
        client, mk_auth_headers, db_session, mk_org, mk_input_loc
    )

    _complete_a_run(
        client,
        mk_auth_headers,
        output_id=output.id,
        input_loc=mk_input_loc,
        output_loc=mk_output_loc,
    )

    (out,) = _layers(db_session, ingredient.id, 'OUT')
    assert out.quantity == Decimal('2')
    assert out.total_value == Decimal('4.00')

    (remaining,) = _layers(db_session, ingredient.id, 'IN')
    assert remaining.remaining_qty == Decimal('8')


def test_the_warehouse_is_worth_the_same_after_a_run(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
) -> None:
    """Production transforms value; it does not create it."""
    _, output = _one_priced_ingredient(
        client, mk_auth_headers, db_session, mk_org, mk_input_loc
    )
    before = _stock_value(db_session, mk_org)

    _complete_a_run(
        client,
        mk_auth_headers,
        output_id=output.id,
        input_loc=mk_input_loc,
        output_loc=mk_output_loc,
    )

    assert _stock_value(db_session, mk_org) == before


def test_the_output_costs_what_the_ingredients_actually_cost(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
) -> None:
    """Two prices in the history, so FIFO and the average disagree.

    Five at 1.00 and five at 3.00: the average is 2.00, the two units the run
    eats cost 1.00 each. The output is worth what was eaten, not what the
    shelf averages out to.
    """
    ingredient = _template(db_session, mk_org, 'Two-price ingredient')
    output = _template(db_session, mk_org, 'Output')
    _recipe(db_session, mk_org, output_id=output.id, child_id=ingredient.id)
    post_on_shelf(
        client, mk_auth_headers, ingredient, mk_input_loc.id, 5, purchase_price='1.00'
    )
    post_on_shelf(
        client, mk_auth_headers, ingredient, mk_input_loc.id, 5, purchase_price='3.00'
    )

    _complete_a_run(
        client,
        mk_auth_headers,
        output_id=output.id,
        input_loc=mk_input_loc,
        output_loc=mk_output_loc,
    )

    (made,) = _layers(db_session, output.id, 'IN')
    assert made.unit_cost == Decimal('1.0000')
    assert made.total_value == Decimal('2.00')
