"""A production run opens the card at the cost it ran at.

A run posting a layer of 2.50 a piece opened the output record with
"purchase price per unit" empty — the same hole the receipt path closed,
one field over. The field is what a person reads on the product screen
and the fallback value for an organization that keeps no cost layers, so
the run now fills it in when it opens the record.

The layer stays the source of truth for what the stock is worth. A run
whose inputs carry no price opens a card that says nothing, matching the
layer it posts as unknown.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item import Item
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


def _complete_a_run(
    client: TestClient,
    headers: dict[str, str],
    *,
    output_id: UUID,
    input_loc: StorageLocation,
    output_loc: StorageLocation,
) -> None:
    created = client.post(
        '/api/v1/maker/production/orders',
        headers=headers,
        json={
            'output_template_id': str(output_id),
            'planned_qty': '2',
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


def _card(db: Session, org_id: UUID, template_id: UUID) -> Item:
    db.expire_all()
    return db.scalars(
        select(Item).where(
            Item.organization_id == org_id,
            Item.template_id == template_id,
        )
    ).one()


def test_a_priced_run_opens_the_card_at_its_unit_cost(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
) -> None:
    """5.00 of ingredients into 2 pieces: the card reads 2.50, like the run."""
    ingredient = _template(db_session, mk_org, 'Flour the ledger priced')
    output = _template(db_session, mk_org, 'Output')
    _recipe(db_session, mk_org, output_id=output.id, child_id=ingredient.id)
    post_on_shelf(
        client,
        mk_auth_headers,
        ingredient,
        mk_input_loc.id,
        10,
        purchase_price='2.50',
    )

    _complete_a_run(
        client,
        mk_auth_headers,
        output_id=output.id,
        input_loc=mk_input_loc,
        output_loc=mk_output_loc,
    )

    card = _card(db_session, mk_org.id, output.id)
    assert Decimal(str(card.purchase_price)) == Decimal('2.50')
    # The layer stays what the stock is worth — the record carries what the
    # run said, the ledger keeps what the stock cost.
    (layer,) = db_session.scalars(
        select(StockValuationLayer).where(
            StockValuationLayer.product_template_id == output.id,
            StockValuationLayer.direction == 'IN',
        )
    ).all()
    assert Decimal(str(layer.unit_cost)) == Decimal('2.50')
    assert layer.cost_basis == 'stated'


def test_a_run_from_priceless_ingredients_opens_a_silent_card(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
) -> None:
    """Nothing the run consumed carried a price: the card says nothing too."""
    ingredient = _template(db_session, mk_org, 'Ingredient nobody priced')
    output = _template(db_session, mk_org, 'Output')
    _recipe(db_session, mk_org, output_id=output.id, child_id=ingredient.id)
    post_on_shelf(client, mk_auth_headers, ingredient, mk_input_loc.id, 10)

    _complete_a_run(
        client,
        mk_auth_headers,
        output_id=output.id,
        input_loc=mk_input_loc,
        output_loc=mk_output_loc,
    )

    card = _card(db_session, mk_org.id, output.id)
    assert card.purchase_price is None
