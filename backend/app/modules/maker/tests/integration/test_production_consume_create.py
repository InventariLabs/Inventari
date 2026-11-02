"""Integration tests for end-to-end production flow.

Create a DRAFT order, complete it, verify:
- The ingredient's shelf decreased
- Output item created with template_id
- The output's shelf increased
- Order moves to COMPLETED with total_cost
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
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.maker.models import BoMLine, MakerRecipe
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration


def _template(
    db: Session,
    org: Organization,
    *,
    name: str = 'T',
    removal_strategy: str = 'FIFO',
) -> ProductTemplate:
    t = ProductTemplate(
        organization_id=org.id,
        name=name,
        sku=f'SKU-{uuid.uuid4().hex[:8]}',
        removal_strategy=removal_strategy,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _ensure_recipe(
    db: Session,
    org: Organization,
    template_id: UUID,
) -> MakerRecipe:
    """Get or create a default recipe for template_id."""
    existing = (
        db.query(MakerRecipe)
        .filter(
            MakerRecipe.organization_id == org.id,
            MakerRecipe.output_template_id == template_id,
            MakerRecipe.is_default.is_(True),
        )
        .first()
    )
    if existing:
        return existing
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=template_id,
        name='Test',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return recipe


def _bom_line(
    db: Session,
    org: Organization,
    *,
    parent_id: UUID,
    child_id: UUID,
    qty: str = '1.0',
) -> BoMLine:
    recipe = _ensure_recipe(db, org, parent_id)
    line = BoMLine(
        organization_id=org.id,
        recipe_id=recipe.id,
        parent_template_id=parent_id,
        child_template_id=child_id,
        qty_per_batch=Decimal(qty),
        unit='kg',
    )
    db.add(line)
    db.commit()
    db.refresh(line)
    return line


def _quant(
    client: TestClient,
    headers: dict[str, str],
    db: Session,
    template: ProductTemplate,
    location_id: UUID,
    qty: str = '10.000',
    *,
    unit_cost: str | None = None,
) -> ShelfRow:
    """Put *qty* of *template* on the shelf as a record; returns its group.

    *unit_cost* is the record's purchase price, which is what values the
    receipt layer behind it.
    """
    post_on_shelf(client, headers, template, location_id, qty, purchase_price=unit_cost)
    return db.execute(
        select(ShelfRow).where(
            ShelfRow.organization_id == template.organization_id,
            ShelfRow.product_template_id == template.id,
            ShelfRow.storage_location_id == location_id,
        )
    ).scalar_one()


class TestProductionConsumeAndCreate:
    """End-to-end happy-path: 1 ingredient → 1 output."""

    def test_complete_production_consumes_and_creates(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_user: User,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, name='Sugar')
        output = _template(db_session, mk_org, name='Jam')
        # 1 kg of sugar per 1 kg of jam.
        _bom_line(
            db_session,
            mk_org,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='1.0',
        )
        # 5 kg of sugar in stock at 2.00/unit.
        shelf = _quant(
            client,
            mk_auth_headers,
            db_session,
            ingredient,
            mk_input_loc.id,
            '5.000',
            unit_cost='2.00',
        )
        original_ingredient_qty = shelf.quantity

        # Create DRAFT order for 2 kg of jam.
        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '2.000',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        order_id = create_resp.json()['id']
        assert create_resp.json()['status'] == 'DRAFT'

        # Complete the order.
        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
        )
        assert complete_resp.status_code == 200, complete_resp.text
        body = complete_resp.json()
        assert body['status'] == 'COMPLETED'
        # total = 2 kg × 2.00 AVCO = 4.00
        assert Decimal(body['total_cost']) == Decimal('4.00')
        assert body['completed_by'] == str(mk_user.id)

        # Ingredient shelf decreased.
        updated_shelf = db_session.execute(
            select(ShelfRow).where(ShelfRow.id == shelf.id)
        ).scalar_one()
        assert updated_shelf.quantity == original_ingredient_qty - Decimal('2.000')

        # Output item created (quantity = planned_qty).
        items = list(
            db_session.execute(
                select(Item).where(
                    Item.organization_id == mk_org.id,
                    Item.template_id == output.id,
                    Item.storage_location_id == mk_output_loc.id,
                )
            )
            .scalars()
            .all()
        )
        assert any(i.quantity == Decimal('2.000') for i in items)

        # Output stock added.
        output_shelf = db_session.execute(
            select(ShelfRow).where(
                ShelfRow.organization_id == mk_org.id,
                ShelfRow.product_template_id == output.id,
                ShelfRow.storage_location_id == mk_output_loc.id,
            )
        ).scalar_one_or_none()
        assert output_shelf is not None
        assert output_shelf.quantity >= Decimal('2.000')

        # ProductionOrderLine snapshot created.
        order_resp = client.get(
            f'/api/v1/maker/production/orders/{order_id}',
            headers=mk_auth_headers,
        )
        order_body = order_resp.json()
        assert len(order_body['lines']) == 1
        assert order_body['lines'][0]['child_template_id'] == str(ingredient.id)
        assert order_body['lines'][0]['child_template_name'] == 'Sugar'
        assert Decimal(order_body['lines'][0]['consumed_qty']) == Decimal('2.0000')
        assert order_body['lines'][0]['cost_source'] == 'fifo'

        # The order response carries the resolved product name.
        assert order_body['output_template_name'] == 'Jam'
        # The create response also carries it (list-page needs it).
        assert create_resp.json()['output_template_name'] == 'Jam'

        # Completion links the produced output Item.
        assert order_body['produced_item_id'] is not None
        produced = db_session.get(Item, uuid.UUID(order_body['produced_item_id']))
        assert produced is not None
        assert produced.template_id == output.id
        assert produced.quantity == Decimal('2.000')

    def test_complete_production_creates_audit_stock_moves(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, name='Flour')
        output = _template(db_session, mk_org, name='Bread')
        _bom_line(
            db_session,
            mk_org,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='0.5',
        )
        _quant(
            client,
            mk_auth_headers,
            db_session,
            ingredient,
            mk_input_loc.id,
            '10.000',
            unit_cost='1.00',
        )

        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '2.000',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert create_resp.status_code == 201
        order_id = create_resp.json()['id']

        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
        )
        assert complete_resp.status_code == 200

        # Audit: stock_moves with reference_type='maker_production'.
        from app.models.stock_move import StockMove

        moves = list(
            db_session.execute(
                select(StockMove).where(
                    StockMove.organization_id == mk_org.id,
                    StockMove.reference_type == 'maker_production',
                    StockMove.reference_id == uuid.UUID(order_id),
                )
            )
            .scalars()
            .all()
        )
        # 1 input move (flour: from=input_loc → None) and 1 output move
        # (jam: None → output_loc).
        assert len(moves) >= 2
        directions = {(m.from_location_id, m.to_location_id) for m in moves}
        assert (mk_input_loc.id, None) in directions  # input move
        assert (None, mk_output_loc.id) in directions  # output move
