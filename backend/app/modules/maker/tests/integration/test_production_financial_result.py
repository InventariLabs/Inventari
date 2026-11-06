"""Integration tests for the financial result snapshot (savings / margin).

Test contract:
  - complete stores the financial snapshot on the order:
    unit_cost, reference_price, result per unit and per batch
  - snapshot respects actual_qty (scrap → higher unit cost)
  - no reference price on the recipe → result fields stay NULL
  - legacy orders (recipe_id=None) keep NULL snapshots
  - order list/detail expose the snapshot fields
  - GET /production/monthly-result aggregates per month (zero months included,
    only COMPLETED orders with a snapshot, org-scoped)
"""

from __future__ import annotations

import uuid
from calendar import monthrange
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.maker.models import BoMLine, MakerRecipe, ProductionOrder
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers (same patterns as test_production_faza_a.py)
# ---------------------------------------------------------------------------


def _template(db: Session, org: Organization, *, name: str = 'T') -> ProductTemplate:
    t = ProductTemplate(
        organization_id=org.id,
        name=name,
        sku=f'SKU-{uuid.uuid4().hex[:8]}',
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _recipe(
    db: Session,
    org: Organization,
    template_id: UUID,
    *,
    name: str = 'Formula',
    batch_yield_qty: str = '1',
    reference_price: str | None = None,
) -> MakerRecipe:
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=template_id,
        name=name,
        batch_yield_qty=Decimal(batch_yield_qty),
        reference_price=Decimal(reference_price) if reference_price else None,
        is_default=True,
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return recipe


def _bom_line(
    db: Session,
    *,
    recipe_id: UUID,
    parent_id: UUID,
    child_id: UUID,
    qty: str = '1.0',
) -> BoMLine:
    parent = db.get(ProductTemplate, parent_id)
    assert parent is not None
    line = BoMLine(
        organization_id=parent.organization_id,
        recipe_id=recipe_id,
        parent_template_id=parent_id,
        child_template_id=child_id,
        qty_per_batch=Decimal(qty),
        unit='kg',
    )
    db.add(line)
    db.commit()
    db.refresh(line)
    return line


def _insert_order_row(
    db: Session,
    *,
    org_id: UUID,
    output_template_id: UUID,
    output_location_id: UUID,
    planned_qty: str = '4.000',
    actual_qty: str | None = None,
    recipe_id: UUID | None = None,
    status: str = 'COMPLETED',
    completed_at: datetime | None = None,
    unit_cost_snapshot: str | None = None,
    reference_price_snapshot: str | None = None,
    result_per_unit: str | None = None,
    result_per_batch: str | None = None,
) -> ProductionOrder:
    order = ProductionOrder(
        organization_id=org_id,
        output_template_id=output_template_id,
        recipe_id=recipe_id,
        planned_qty=Decimal(planned_qty),
        actual_qty=Decimal(actual_qty) if actual_qty else None,
        output_storage_location_id=output_location_id,
        status=status,
        completed_at=completed_at,
        unit_cost_snapshot=(
            Decimal(unit_cost_snapshot) if unit_cost_snapshot else None
        ),
        reference_price_snapshot=(
            Decimal(reference_price_snapshot) if reference_price_snapshot else None
        ),
        result_per_unit=Decimal(result_per_unit) if result_per_unit else None,
        result_per_batch=Decimal(result_per_batch) if result_per_batch else None,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestResultSnapshot:
    """complete stores unit_cost, reference price and per-unit/per-batch result."""

    def test_complete_stores_financial_snapshot(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, name='Cocoa')
        output = _template(db_session, mk_org, name='Chocolate')
        recipe = _recipe(
            db_session,
            mk_org,
            output.id,
            batch_yield_qty='2',
            reference_price='12.50',
        )
        _bom_line(
            db_session, recipe_id=recipe.id, parent_id=output.id, child_id=ingredient.id
        )
        post_on_shelf(
            client,
            mk_auth_headers,
            ingredient,
            mk_input_loc.id,
            '100.000',
            purchase_price='2.00',
        )

        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '4.000',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert create_resp.status_code == 201
        order_id = create_resp.json()['id']

        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
            json={},
        )
        assert complete_resp.status_code == 200, complete_resp.text
        body = complete_resp.json()

        # yield=2, planned=4 → 2 batches × 1.0 kg @ 2.00 = 4.00 total
        # → unit cost 1.00; ref 12.50 → 11.50/unit, 23.00/batch.
        assert body['unit_cost_snapshot'] == '1.0000'
        assert body['reference_price_snapshot'] == '12.50'
        assert body['result_per_unit'] == '11.50'
        assert body['result_per_batch'] == '23.00'

    def test_snapshot_uses_actual_qty_for_unit_cost(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, name='Cocoa')
        output = _template(db_session, mk_org, name='Chocolate')
        recipe = _recipe(db_session, mk_org, output.id, reference_price='12.50')
        _bom_line(
            db_session, recipe_id=recipe.id, parent_id=output.id, child_id=ingredient.id
        )
        post_on_shelf(
            client,
            mk_auth_headers,
            ingredient,
            mk_input_loc.id,
            '100.000',
            purchase_price='2.00',
        )

        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '4.000',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        order_id = create_resp.json()['id']

        # actual = 3 → unit cost = 8.00 / 3 = 2.6667 (scrap raises the cost).
        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
            json={'actual_qty': '3.000'},
        )
        assert complete_resp.status_code == 200, complete_resp.text
        body = complete_resp.json()
        assert body['unit_cost_snapshot'] == '2.6667'
        assert body['result_per_unit'] == '9.83'
        assert body['result_per_batch'] == '9.83'

    def test_a_run_with_an_uncosted_ingredient_states_no_result(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """A margin measured against a cost that left an ingredient out is
        overstated by what was left out, so the run keeps its cost and states
        no result - the same withholding the recipe card applies."""
        cocoa = _template(db_session, mk_org, name='Cocoa')
        hazelnuts = _template(db_session, mk_org, name='Hazelnuts')
        output = _template(db_session, mk_org, name='Chocolate')
        recipe = _recipe(db_session, mk_org, output.id, reference_price='12.50')
        for ingredient in (cocoa, hazelnuts):
            _bom_line(
                db_session,
                recipe_id=recipe.id,
                parent_id=output.id,
                child_id=ingredient.id,
            )
        post_on_shelf(
            client,
            mk_auth_headers,
            cocoa,
            mk_input_loc.id,
            '100.000',
            purchase_price='2.00',
        )
        post_on_shelf(client, mk_auth_headers, hazelnuts, mk_input_loc.id, '100.000')

        order_id = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '4.000',
                'output_location_id': str(mk_output_loc.id),
            },
        ).json()['id']
        completed = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
            json={},
        )
        assert completed.status_code == 200, completed.text
        body = completed.json()

        assert body['unit_cost_snapshot'] is not None
        assert body['result_per_unit'] is None
        assert body['result_per_batch'] is None

        months = client.get(
            '/api/v1/maker/production/monthly-result', headers=mk_auth_headers
        ).json()
        assert months[-1]['orders'] == 0
        assert months[-1]['result'] == '0.00'

    def test_snapshot_result_null_without_reference_price(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, name='Cocoa')
        output = _template(db_session, mk_org, name='Chocolate')
        recipe = _recipe(db_session, mk_org, output.id)  # no reference_price
        _bom_line(
            db_session, recipe_id=recipe.id, parent_id=output.id, child_id=ingredient.id
        )
        post_on_shelf(
            client,
            mk_auth_headers,
            ingredient,
            mk_input_loc.id,
            '100.000',
            purchase_price='2.00',
        )

        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1.000',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        order_id = create_resp.json()['id']

        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
            json={},
        )
        assert complete_resp.status_code == 200, complete_resp.text
        body = complete_resp.json()
        assert body['unit_cost_snapshot'] == '2.0000'
        assert body['reference_price_snapshot'] is None
        assert body['result_per_unit'] is None
        assert body['result_per_batch'] is None

    def test_legacy_order_without_recipe_keeps_null_snapshots(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        # Legacy order from before recipes: no recipe_id on the order row. The default
        # recipe still has to list ingredients — a run that consumes nothing
        # is refused (empty_bom), and that is a separate rule from this one.
        output = _template(db_session, mk_org, name='Legacy')
        ingredient = _template(db_session, mk_org, name='LegacyIngredient')
        default_recipe = _recipe(db_session, mk_org, output.id, name='Legacy default')
        _bom_line(
            db_session,
            recipe_id=default_recipe.id,
            parent_id=output.id,
            child_id=ingredient.id,
        )
        post_on_shelf(client, mk_auth_headers, ingredient, mk_input_loc.id, '100.000')
        order = _insert_order_row(
            db_session,
            org_id=mk_org.id,
            output_template_id=output.id,
            output_location_id=mk_output_loc.id,
            status='DRAFT',
        )
        assert order.recipe_id is None

        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{order.id}/complete',
            headers=mk_auth_headers,
            json={},
        )
        assert complete_resp.status_code == 200, complete_resp.text
        body = complete_resp.json()
        assert body['status'] == 'COMPLETED'
        assert body['unit_cost_snapshot'] is None
        assert body['reference_price_snapshot'] is None
        assert body['result_per_unit'] is None
        assert body['result_per_batch'] is None


class TestOrderResultFields:
    """List and detail expose the snapshot fields."""

    def test_list_and_detail_expose_snapshot(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, name='Cocoa')
        output = _template(db_session, mk_org, name='Chocolate')
        recipe = _recipe(db_session, mk_org, output.id, reference_price='12.50')
        _bom_line(
            db_session, recipe_id=recipe.id, parent_id=output.id, child_id=ingredient.id
        )
        post_on_shelf(
            client,
            mk_auth_headers,
            ingredient,
            mk_input_loc.id,
            '100.000',
            purchase_price='2.00',
        )

        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1.000',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        order_id = create_resp.json()['id']
        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
            json={},
        )
        assert complete_resp.status_code == 200

        list_resp = client.get(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
        )
        assert list_resp.status_code == 200
        item = list_resp.json()['items'][0]
        assert item['result_per_unit'] == '10.50'
        assert item['result_per_batch'] == '10.50'

        detail_resp = client.get(
            f'/api/v1/maker/production/orders/{order_id}',
            headers=mk_auth_headers,
        )
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail['unit_cost_snapshot'] == '2.0000'
        assert detail['reference_price_snapshot'] == '12.50'
        assert detail['result_per_unit'] == '10.50'


class TestMonthlyResult:
    """GET /production/monthly-result aggregates the snapshot by month."""

    def test_aggregates_completed_orders_by_month(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        output = _template(db_session, mk_org, name='Jam')
        now = datetime.now(tz=UTC)
        # Two completed orders this month: 10.00 × 2 + 10.00 × 3 = 50.00.
        _insert_order_row(
            db_session,
            org_id=mk_org.id,
            output_template_id=output.id,
            output_location_id=mk_output_loc.id,
            actual_qty='2.000',
            completed_at=now,
            result_per_unit='10.00',
        )
        _insert_order_row(
            db_session,
            org_id=mk_org.id,
            output_template_id=output.id,
            output_location_id=mk_output_loc.id,
            actual_qty='3.000',
            completed_at=now,
            result_per_unit='10.00',
        )
        # Previous month: 4.00 × 4 = 16.00. Clamp the day — months have
        # different lengths, so a naive replace() blows up on the 29th–31st.
        prev_year, prev_month = (
            (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
        )
        prev = now.replace(
            year=prev_year,
            month=prev_month,
            day=min(now.day, monthrange(prev_year, prev_month)[1]),
        )
        _insert_order_row(
            db_session,
            org_id=mk_org.id,
            output_template_id=output.id,
            output_location_id=mk_output_loc.id,
            actual_qty='4.000',
            completed_at=prev,
            result_per_unit='4.00',
        )

        resp = client.get(
            '/api/v1/maker/production/monthly-result',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 200
        months = resp.json()
        # 6 months window, oldest → newest, zero months included.
        assert len(months) == 6
        assert months[-1]['month'] == now.strftime('%Y-%m')
        assert months[-1]['result'] == '50.00'
        assert months[-1]['orders'] == 2
        prev_entry = next(
            (m for m in months if m['month'] == prev.strftime('%Y-%m')), None
        )
        assert prev_entry is not None
        assert prev_entry['result'] == '16.00'
        assert prev_entry['orders'] == 1

    def test_ignores_drafts_cancelled_and_snapshotless(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        output = _template(db_session, mk_org, name='Jam')
        now = datetime.now(tz=UTC)
        # DRAFT — not counted.
        _insert_order_row(
            db_session,
            org_id=mk_org.id,
            output_template_id=output.id,
            output_location_id=mk_output_loc.id,
            status='DRAFT',
            result_per_unit='10.00',
        )
        # COMPLETED without a result snapshot (legacy) — not counted.
        _insert_order_row(
            db_session,
            org_id=mk_org.id,
            output_template_id=output.id,
            output_location_id=mk_output_loc.id,
            actual_qty='5.000',
            completed_at=now,
        )
        # CANCELLED with a snapshot — not counted.
        _insert_order_row(
            db_session,
            org_id=mk_org.id,
            output_template_id=output.id,
            output_location_id=mk_output_loc.id,
            status='CANCELLED',
            result_per_unit='10.00',
        )

        resp = client.get(
            '/api/v1/maker/production/monthly-result',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 200
        months = resp.json()
        assert sum(m['orders'] for m in months) == 0
        assert sum(Decimal(m['result']) for m in months) == Decimal('0')

    def test_org_scoping(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        h: ModuleTestHelper,
        mk_org: Organization,
        mk_user: User,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        output = _template(db_session, mk_org, name='Jam')
        _insert_order_row(
            db_session,
            org_id=mk_org.id,
            output_template_id=output.id,
            output_location_id=mk_output_loc.id,
            actual_qty='2.000',
            completed_at=datetime.now(tz=UTC),
            result_per_unit='10.00',
        )

        # Another org with its own completed order must not leak.
        other_org = h.create_org(
            'Other Org',
            ['core', 'items', 'locations', 'categories', 'stats', 'maker'],
        )
        other_user = h.create_user(other_org, email='other-maker@example.com')
        other_headers = h.get_auth_headers(other_user)
        other_output = _template(db_session, other_org, name='Jam')
        other_st = h.create_storage_type('Other Storage', 'OTHER')
        other_loc = h.create_storage_location(
            other_org, other_st, other_user, name='Other Store'
        )
        _insert_order_row(
            db_session,
            org_id=other_org.id,
            output_template_id=other_output.id,
            output_location_id=other_loc.id,
            actual_qty='9.000',
            completed_at=datetime.now(tz=UTC),
            result_per_unit='100.00',
        )

        resp = client.get(
            '/api/v1/maker/production/monthly-result',
            headers=other_headers,
        )
        assert resp.status_code == 200
        months = resp.json()
        assert months[-1]['result'] == '900.00'
        assert months[-1]['orders'] == 1
