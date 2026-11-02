"""Smoke tests for the inventory invariant helpers.

Proves ``_invariants.assert_invariants`` runs without false positives on
valid state. The detection side (asserting the helpers RAISE on negative /
corrupted SVL) is exercised by Suite C cost-preservation tests. The quant
consistency check, and the case that kept a record without a card out of
it, went with the quant table.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.services.token_service import create_access_token
from tests.integration._shelf import anchor_pending_records

from ._invariants import assert_invariants, get_stock_value


def _headers(user) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.mark.integration
class TestInvariantHelpers:
    def test_invariants_pass_for_org_without_inventory(
        self, db_session, test_household
    ):
        # Fresh org, zero items/SVL rows.
        assert_invariants(db_session, test_household.id)
        assert get_stock_value(db_session, test_household.id) == 0


@pytest.mark.integration
class TestScanQuantityValidation:
    """LabelAssignRequest.quantity must reject negatives at the schema
    layer (422), not pass through to the scan handler."""

    def test_scan_assign_rejects_negative_quantity(
        self, client, test_user, test_storage_location
    ):
        resp = client.post(
            '/api/v1/labels/scan/12345678/assign',
            json={
                'location_id': str(test_storage_location.id),
                'name': 'ScanNeg',
                'quantity': -5,
            },
            headers=_headers(test_user),
        )
        assert resp.status_code == 422


@pytest.mark.integration
class TestQuantityValidation:
    """Negative quantity must be rejected at the schema layer (422), not
    leak through to the DB CheckConstraint as an opaque 500."""

    def test_negative_quantity_update_returns_422(self, client, test_user, test_item):
        resp = client.patch(
            f'/api/v1/items/{test_item.id}/quantity',
            json={'quantity': -5},
            headers=_headers(test_user),
        )
        assert resp.status_code == 422


@pytest.mark.integration
class TestGlobalTemplateIsolation:
    """Updating min_quantity on an item that references a GLOBAL (shared)
    ProductTemplate must not mutate that shared template — it would change the
    low-stock threshold for every organization."""

    def test_min_quantity_update_does_not_mutate_global_template(
        self, client, db_session, test_user, test_storage_location
    ):
        global_tpl = ProductTemplate(
            organization_id=None,
            name='GlobalShared',
            sku=f'GLOB-{uuid4().hex[:8]}',
        )
        db_session.add(global_tpl)
        db_session.commit()
        db_session.refresh(global_tpl)
        original_min = global_tpl.min_quantity

        item = Item(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            template_id=global_tpl.id,
            name='OnGlobalTpl',
            quantity=2,
        )
        db_session.add(item)
        anchor_pending_records(db_session)
        db_session.commit()
        db_session.refresh(item)

        resp = client.put(
            f'/api/v1/items/{item.id}',
            json={'min_quantity': 99},
            headers=_headers(test_user),
        )
        assert resp.status_code == 200, resp.text

        db_session.expire_all()
        db_session.refresh(global_tpl)
        assert global_tpl.min_quantity == original_min, (
            'global/shared template was mutated by an org-scoped item update'
        )
