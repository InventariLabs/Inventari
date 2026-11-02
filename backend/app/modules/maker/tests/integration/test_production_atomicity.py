"""Integration tests for production atomicity (rollback on failure).

A production run that fails mid-way must roll back ALL state changes:
- No partial consume of ingredients
- No output item created
- No stock moved on either shelf
- Order stays DRAFT
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
    qty: str,
) -> ShelfRow:
    """Put *qty* of *template* on the shelf as a record; returns its group."""
    post_on_shelf(client, headers, template, location_id, qty)
    return db.execute(
        select(ShelfRow).where(
            ShelfRow.organization_id == template.organization_id,
            ShelfRow.product_template_id == template.id,
            ShelfRow.storage_location_id == location_id,
        )
    ).scalar_one()


class TestProductionAtomicity:
    """Failed production must leave the system untouched."""

    def test_insufficient_stock_rolls_back_everything(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        # Output requires 5 kg of ingredient. Stock: only 3 kg.
        ingredient = _template(db_session, mk_org, name='Cocoa')
        output = _template(db_session, mk_org, name='Chocolate')
        _bom_line(
            db_session,
            mk_org,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='5.0',
        )
        shelf = _quant(
            client, mk_auth_headers, db_session, ingredient, mk_input_loc.id, '3.000'
        )
        original_qty = shelf.quantity
        original_output_stock = db_session.execute(
            select(ShelfRow).where(
                ShelfRow.organization_id == mk_org.id,
                ShelfRow.product_template_id == output.id,
                ShelfRow.storage_location_id == mk_output_loc.id,
            )
        ).scalar_one_or_none()
        assert original_output_stock is None

        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1.000',
                'output_location_id': str(mk_output_loc.id),
                # These tests drive completion, rollback and cancelling;
                # the strategy default (WARN) must not stop the draft here.
                'confirm_shortage': True,
            },
        )
        assert create_resp.status_code == 201
        order_id = create_resp.json()['id']

        # Complete — must fail with 422 (actionable shortage list).
        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
        )
        assert complete_resp.status_code == 422
        detail = complete_resp.json()['detail']
        assert detail['error'] == 'insufficient_stock'
        assert len(detail['shortages']) > 0
        assert Decimal(detail['shortages'][0]['shortage']) > 0

        # 1. Order status: still DRAFT (not COMPLETED).
        order_body = client.get(
            f'/api/v1/maker/production/orders/{order_id}',
            headers=mk_auth_headers,
        ).json()
        assert order_body['status'] == 'DRAFT'

        # 2. Ingredient shelf: untouched.
        refreshed = db_session.execute(
            select(ShelfRow).where(ShelfRow.id == shelf.id)
        ).scalar_one()
        assert refreshed.quantity == original_qty

        # 3. No output stock added.
        output_stock = db_session.execute(
            select(ShelfRow).where(
                ShelfRow.organization_id == mk_org.id,
                ShelfRow.product_template_id == output.id,
                ShelfRow.storage_location_id == mk_output_loc.id,
            )
        ).scalar_one_or_none()
        assert output_stock is None, 'the failed run left goods on the output shelf'

        # 4. No output Item created.
        new_items = list(
            db_session.execute(
                select(Item).where(
                    Item.organization_id == mk_org.id,
                    Item.template_id == output.id,
                )
            )
            .scalars()
            .all()
        )
        assert new_items == []

    def test_cancel_draft_order_succeeds(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, name='Y')
        output = _template(db_session, mk_org, name='Z')
        _bom_line(
            db_session,
            mk_org,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='1.0',
        )

        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1.000',
                'output_location_id': str(mk_output_loc.id),
                # These tests drive completion, rollback and cancelling;
                # the strategy default (WARN) must not stop the draft here.
                'confirm_shortage': True,
            },
        )
        assert create_resp.status_code == 201
        order_id = create_resp.json()['id']

        cancel_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/cancel',
            headers=mk_auth_headers,
        )
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()['status'] == 'CANCELLED'

    def test_cancel_completed_order_rejected(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, name='X')
        output = _template(db_session, mk_org, name='Y')
        _bom_line(
            db_session,
            mk_org,
            parent_id=output.id,
            child_id=ingredient.id,
            qty='0.1',
        )
        _quant(
            client, mk_auth_headers, db_session, ingredient, mk_input_loc.id, '10.000'
        )
        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1.000',
                'output_location_id': str(mk_output_loc.id),
                # These tests drive completion, rollback and cancelling;
                # the strategy default (WARN) must not stop the draft here.
                'confirm_shortage': True,
            },
        )
        order_id = create_resp.json()['id']
        client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
        )
        # Now try to cancel — must fail.
        cancel_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/cancel',
            headers=mk_auth_headers,
        )
        assert cancel_resp.status_code == 400

    def test_cancel_with_reason_stores_reason_and_audit(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_user: User,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """Cancel must capture an optional reason + write AuditLog."""
        output = _template(db_session, mk_org, name='Reasonable')
        _ensure_recipe(db_session, mk_org, template_id=output.id)
        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1.000',
                'output_location_id': str(mk_output_loc.id),
                # These tests drive completion, rollback and cancelling;
                # the strategy default (WARN) must not stop the draft here.
                'confirm_shortage': True,
            },
        )
        assert create_resp.status_code == 201
        order_id = create_resp.json()['id']

        cancel_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/cancel',
            headers=mk_auth_headers,
            json={'reason': 'Customer pulled the order'},
        )
        assert cancel_resp.status_code == 200, cancel_resp.text
        body = cancel_resp.json()
        assert body['status'] == 'CANCELLED'
        assert body['cancel_reason'] == 'Customer pulled the order'

        # Audit log entry written with the reason mirrored. The order now
        # also leaves a CREATE entry (and a completed one would leave its
        # own UPDATE) — the cancel is the entry whose snapshot says
        # DRAFT -> CANCELLED.
        from app.models.audit_log import AuditLog

        audit_entries = list(
            db_session.execute(
                select(AuditLog).where(
                    AuditLog.organization_id == mk_org.id,
                    AuditLog.target_type == 'maker_production_order',
                    AuditLog.target_id == uuid.UUID(order_id),
                )
            )
            .scalars()
            .all()
        )
        cancels = [
            e
            for e in audit_entries
            if (e.snapshot or {}).get('new_status') == 'CANCELLED'
        ]
        assert len(cancels) == 1
        entry = cancels[0]
        assert entry.reason == 'Customer pulled the order'
        assert entry.snapshot == {'old_status': 'DRAFT', 'new_status': 'CANCELLED'}

    def test_cancel_without_reason_stores_null(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """Cancelling without a body must still work (backward compatible)."""
        output = _template(db_session, mk_org, name='NoReason')
        _ensure_recipe(db_session, mk_org, template_id=output.id)
        create_resp = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1.000',
                'output_location_id': str(mk_output_loc.id),
                # These tests drive completion, rollback and cancelling;
                # the strategy default (WARN) must not stop the draft here.
                'confirm_shortage': True,
            },
        )
        order_id = create_resp.json()['id']

        cancel_resp = client.post(
            f'/api/v1/maker/production/orders/{order_id}/cancel',
            headers=mk_auth_headers,
        )
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()['cancel_reason'] is None
