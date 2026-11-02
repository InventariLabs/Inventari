"""Integration tests for cost rollup and breakdown."""

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
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.modules.maker.models import BoMLine, MakerRecipe
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration


def _make_template(
    db_session: Session, org: Organization, *, name: str, removal_strategy: str = 'FIFO'
) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id,
        name=name,
        sku=f'SKU-{uuid.uuid4().hex[:8]}',
        removal_strategy=removal_strategy,
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    return template


def _ensure_recipe(
    db_session: Session, org: Organization, template_id: UUID
) -> MakerRecipe:
    """Get or create a default recipe for template_id."""
    existing = (
        db_session.query(MakerRecipe)
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
    db_session.add(recipe)
    db_session.commit()
    db_session.refresh(recipe)
    return recipe


def _make_bom_line(
    db_session: Session,
    org: Organization,
    *,
    parent_id: UUID,
    child_id: UUID,
    qty: str = '1.0',
    unit: str = 'kg',
) -> BoMLine:
    recipe = _ensure_recipe(db_session, org, parent_id)
    line = BoMLine(
        organization_id=org.id,
        recipe_id=recipe.id,
        parent_template_id=parent_id,
        child_template_id=child_id,
        qty_per_batch=Decimal(qty),
        unit=unit,
    )
    db_session.add(line)
    db_session.commit()
    db_session.refresh(line)
    return line


def _seed_valuation(
    db_session: Session,
    *,
    org_id: UUID,
    template_id: UUID,
    qty: str,
    unit_cost: str,
) -> StockValuationLayer:
    cost_dec = Decimal(unit_cost)
    layer = StockValuationLayer(
        organization_id=org_id,
        product_template_id=template_id,
        quantity=Decimal(qty),
        remaining_qty=Decimal(qty),
        unit_cost=cost_dec,
        total_value=Decimal(qty) * cost_dec,
        direction='IN',
    )
    db_session.add(layer)
    db_session.commit()
    db_session.refresh(layer)
    return layer


class TestCostRollupAndBreakdown:
    """Verify AVCO × effective_qty across the BOM and percentage breakdown."""

    def test_breakdown_percentages_sum_to_100(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        soup = _make_template(db_session, mk_org, name='Soup')
        carrot = _make_template(db_session, mk_org, name='Carrots')
        potato = _make_template(db_session, mk_org, name='Potatoes')

        # Carrots 10 @ 2 = 20; Potatoes 10 @ 3 = 30. Total = 50.
        _seed_valuation(
            db_session,
            org_id=mk_org.id,
            template_id=carrot.id,
            qty='10.00',
            unit_cost='2.00',
        )
        _seed_valuation(
            db_session,
            org_id=mk_org.id,
            template_id=potato.id,
            qty='10.00',
            unit_cost='3.00',
        )
        _make_bom_line(
            db_session,
            mk_org,
            parent_id=soup.id,
            child_id=carrot.id,
            qty='1.0',
        )
        _make_bom_line(
            db_session,
            mk_org,
            parent_id=soup.id,
            child_id=potato.id,
            qty='1.0',
        )

        response = client.get(
            f'/api/v1/maker/breakdown/{soup.id}?qty=10',
            headers=mk_auth_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert Decimal(body['total_cost']) == Decimal('50.00')

        # Each ingredient entry carries its display name (FE renders names).
        names = {
            entry['child_template_id']: entry['child_template_name']
            for entry in body['entries']
        }
        assert names[str(carrot.id)] == 'Carrots'
        assert names[str(potato.id)] == 'Potatoes'

        percentages = [Decimal(p['percentage_of_total']) for p in body['entries']]
        # Allow tiny float quantize drift; sum must be ≈100.
        total_pct = sum(percentages)
        assert abs(total_pct - Decimal('100.00')) < Decimal('0.05')

    def test_breakdown_missing_cost_marks_template(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        soup = _make_template(db_session, mk_org, name='Soup')
        carrot = _make_template(db_session, mk_org, name='Carrots')
        # No valuation layer for carrot — missing_cost_lines must list it.
        _make_bom_line(
            db_session,
            mk_org,
            parent_id=soup.id,
            child_id=carrot.id,
            qty='1.0',
        )

        response = client.get(
            f'/api/v1/maker/breakdown/{soup.id}?qty=10',
            headers=mk_auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body['missing_cost_lines'] == [str(carrot.id)]
        entry = body['entries'][0]
        assert entry['cost'] is None
        assert entry['percentage_of_total'] is None
        assert entry['cost_source'] == 'none'
        assert entry['child_template_name'] == 'Carrots'

    def test_preview_endpoint_returns_no_state_change(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        # Preview must NOT consume any stock — verify the shelf is unchanged.
        soup = _make_template(db_session, mk_org, name='Soup')
        carrot = _make_template(db_session, mk_org, name='Carrot')
        _make_bom_line(
            db_session,
            mk_org,
            parent_id=soup.id,
            child_id=carrot.id,
            qty='0.5',
        )
        post_on_shelf(
            client,
            mk_auth_headers,
            carrot,
            mk_input_loc.id,
            '5.000',
            purchase_price='2.00',
        )
        shelf = db_session.execute(
            select(ShelfRow).where(
                ShelfRow.organization_id == mk_org.id,
                ShelfRow.product_template_id == carrot.id,
                ShelfRow.storage_location_id == mk_input_loc.id,
            )
        ).scalar_one()
        original_qty = shelf.quantity

        response = client.post(
            '/api/v1/maker/production/orders/preview',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(soup.id),
                'planned_qty': '2.000',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert Decimal(body['total_cost']) == Decimal('2.00')

        # Stock unchanged — preview is read-only.
        updated = db_session.execute(
            select(ShelfRow).where(ShelfRow.id == shelf.id)
        ).scalar_one()
        assert updated.quantity == original_qty
