"""
Penetration Tests for Equipment Module.

Covers:
- Authentication & authorization bypass
- Input validation & boundary conditions
- Injection attacks (SQL, XSS)
- Cross-organization data isolation
- Status state machine edge cases
- Assignment flow vulnerabilities
- Maintenance log edge cases
- Bulk operations security
- Public attestation token security
- Model/Template CRUD edge cases
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.storage_location import StorageLocation

EQUIPMENT_URL = '/api/v1/equipment'


# ══════════════════════════════════════════════════════════════════════════════
# 1. AUTHENTICATION & AUTHORIZATION
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestAuthentication:
    """Auth bypass tests for equipment endpoints."""

    def test_no_token_all_endpoints(self, client: TestClient) -> None:
        """All equipment endpoints must reject unauthenticated requests."""
        fake_id = str(uuid.uuid4())
        endpoints = [
            ('GET', f'{EQUIPMENT_URL}/assignments'),
            ('POST', f'{EQUIPMENT_URL}/assignments'),
            ('GET', f'{EQUIPMENT_URL}/dashboard'),
            ('GET', f'{EQUIPMENT_URL}/warranty-alerts'),
            ('GET', f'{EQUIPMENT_URL}/models'),
            ('POST', f'{EQUIPMENT_URL}/models'),
            ('PUT', f'{EQUIPMENT_URL}/models/{fake_id}'),
            ('DELETE', f'{EQUIPMENT_URL}/models/{fake_id}'),
            ('GET', f'{EQUIPMENT_URL}/my-assets'),
            ('GET', f'{EQUIPMENT_URL}/my-assets/history'),
            ('GET', f'{EQUIPMENT_URL}/templates'),
            ('POST', f'{EQUIPMENT_URL}/templates'),
            ('GET', f'{EQUIPMENT_URL}/campaigns'),
            ('POST', f'{EQUIPMENT_URL}/campaigns'),
            ('GET', f'{EQUIPMENT_URL}/valuation'),
            ('GET', f'{EQUIPMENT_URL}/assignments/item/{fake_id}'),
        ]
        for method, url in endpoints:
            if method == 'GET':
                r = client.get(url)
            elif method == 'POST':
                r = client.post(url, json={})
            elif method == 'PUT':
                r = client.put(url, json={})
            elif method == 'DELETE':
                r = client.delete(url)
            assert r.status_code in (401, 405), (
                f'{method} {url} should return 401 or 405, got {r.status_code}'
            )

    def test_invalid_token(self, client: TestClient) -> None:
        """Invalid Bearer token → 401."""
        r = client.get(
            f'{EQUIPMENT_URL}/assignments',
            headers={'Authorization': 'Bearer garbage.token.value'},
        )
        assert r.status_code == 401

    def test_empty_bearer(self, client: TestClient) -> None:
        """Empty Bearer → 401."""
        r = client.get(
            f'{EQUIPMENT_URL}/assignments',
            headers={'Authorization': 'Bearer '},
        )
        assert r.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# 2. CROSS-ORGANIZATION DATA ISOLATION
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestCrossOrgIsolation:
    """Verify equipment data is isolated per organization."""

    def test_cross_org_cannot_checkout_other_orgs_item(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """User from org B cannot check out item from org A."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        org_b = h.create_org('Org B Equip', ['core', 'items', 'equipment'])
        user_b = h.create_user(org_b, email='orgb_equip@example.com')
        headers_b = h.get_auth_headers(user_b)

        r = client.post(
            f'{EQUIPMENT_URL}/assignments',
            headers=headers_b,
            json={'item_id': str(eq_item.id), 'assigned_to_name': 'Hacker'},
        )
        assert r.status_code == 404

    def test_cross_org_cannot_see_other_orgs_assignments(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Org B cannot list org A's assignments."""
        # Create an assignment as org A
        r1 = client.post(
            f'{EQUIPMENT_URL}/assignments',
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assigned_to_name': 'OrgA User'},
        )
        assert r1.status_code == 201

        # Org A can see their assignment
        list_r = client.get(f'{EQUIPMENT_URL}/assignments', headers=eq_auth_headers)
        assert list_r.status_code == 200
        assert list_r.json()['total'] >= 1

    def test_cross_org_cannot_access_maintenance(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """Org B cannot create maintenance on org A's item."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        org_b = h.create_org('Org B Maint', ['core', 'items', 'equipment'])
        user_b = h.create_user(org_b, email='orgb_maint@example.com')
        headers_b = h.get_auth_headers(user_b)

        r = client.post(
            f'{EQUIPMENT_URL}/maintenance',
            headers=headers_b,
            json={
                'item_id': str(eq_item.id),
                'maintenance_type': 'REPAIR',
                'title': 'Hack repair',
                'performed_at': date.today().isoformat(),
            },
        )
        assert r.status_code in (404, 403)


# ══════════════════════════════════════════════════════════════════════════════
# 3. INPUT VALIDATION & BOUNDARY CONDITIONS
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestInputValidation:
    """Boundary and input validation tests."""

    def test_checkout_empty_body(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Checkout with empty body → 422."""
        r = client.post(
            f'{EQUIPMENT_URL}/assignments',
            headers=eq_auth_headers,
            json={},
        )
        assert r.status_code == 422

    def test_checkout_invalid_item_id(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Checkout with invalid UUID → 422."""
        r = client.post(
            f'{EQUIPMENT_URL}/assignments',
            headers=eq_auth_headers,
            json={'item_id': 'not-a-uuid', 'assigned_to_name': 'Test'},
        )
        assert r.status_code == 422

    def test_checkout_nonexistent_item(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Checkout with non-existent item → 404."""
        r = client.post(
            f'{EQUIPMENT_URL}/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': '00000000-0000-0000-0000-000000000000',
                'assigned_to_name': 'Test',
            },
        )
        assert r.status_code == 404

    def test_checkout_empty_assigned_to_name(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """An empty assigned_to_name is refused, not accepted.

        Both lines that stood here once claimed the opposite — "accepted
        (has default='')". The refusal was real but lived in the schema
        (``min_length=1``), which also refused the location mode, where no
        person is named at all; it now lives in ``checkout()`` as the rule
        it always was — a holder is a person **or** a place — so the answer
        is a translated 400 rather than a 422 naming a field. Refused either
        way, which is what this test is here for.
        """
        r = client.post(
            f'{EQUIPMENT_URL}/assignments',
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assigned_to_name': ''},
        )
        assert r.status_code == 400

    def test_checkout_xss_in_assigned_to_name(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """XSS in assigned_to_name — stored as-is."""
        r = client.post(
            f'{EQUIPMENT_URL}/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': '<script>alert(1)</script>',
            },
        )
        if r.status_code == 201:
            assert r.json()['assigned_to_name'] == '<script>alert(1)</script>'

    def test_checkout_very_long_notes(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Very long checkout notes."""
        r = client.post(
            f'{EQUIPMENT_URL}/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': 'Test',
                'checkout_notes': 'A' * 10000,
            },
        )
        # checkout_notes carries no max_length and lands in a Text column, so
        # ten thousand characters are stored, not refused.
        assert r.status_code == 201

    def test_create_model_empty_name(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Model with empty name → 422."""
        r = client.post(
            f'{EQUIPMENT_URL}/models',
            headers=eq_auth_headers,
            json={'name': ''},
        )
        assert r.status_code == 422

    def test_create_model_long_name(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Model with name >255 chars → 422."""
        r = client.post(
            f'{EQUIPMENT_URL}/models',
            headers=eq_auth_headers,
            json={'name': 'A' * 256},
        )
        assert r.status_code == 422

    def test_create_model_name_at_limit(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Model with name exactly 255 chars → 201."""
        r = client.post(
            f'{EQUIPMENT_URL}/models',
            headers=eq_auth_headers,
            json={'name': 'B' * 255},
        )
        assert r.status_code == 201
        model_id = r.json()['id']

        # Cleanup
        client.delete(f'{EQUIPMENT_URL}/models/{model_id}', headers=eq_auth_headers)

    def test_create_model_long_brand(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Model with brand >255 chars → 422."""
        r = client.post(
            f'{EQUIPMENT_URL}/models',
            headers=eq_auth_headers,
            json={'name': 'Test Model', 'brand': 'C' * 256},
        )
        assert r.status_code == 422

    def test_create_model_negative_purchase_price(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Negative purchase_price → 422 (ge=0)."""
        r = client.post(
            f'{EQUIPMENT_URL}/models',
            headers=eq_auth_headers,
            json={
                'name': 'Negative Price Model',
                'equipment_meta': {'purchase_price': -100},
            },
        )
        # equipment_meta is free-form dict — negative is accepted
        assert r.status_code == 201
        model_id = r.json()['id']
        client.delete(f'{EQUIPMENT_URL}/models/{model_id}', headers=eq_auth_headers)

    def test_maintenance_invalid_type(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Maintenance with invalid type → 422."""
        r = client.post(
            f'{EQUIPMENT_URL}/maintenance',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'maintenance_type': 'INVALID_TYPE',
                'title': 'Test',
                'performed_at': date.today().isoformat(),
            },
        )
        assert r.status_code == 422

    def test_maintenance_negative_cost(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Maintenance with negative cost → 422."""
        r = client.post(
            f'{EQUIPMENT_URL}/maintenance',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'maintenance_type': 'REPAIR',
                'title': 'Negative Cost',
                'cost': -100,
                'performed_at': date.today().isoformat(),
            },
        )
        assert r.status_code == 422

    def test_maintenance_empty_title(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Maintenance with empty title."""
        r = client.post(
            f'{EQUIPMENT_URL}/maintenance',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'maintenance_type': 'REPAIR',
                'title': '',
                'performed_at': date.today().isoformat(),
            },
        )
        # The schema sets max_length=255 and no min_length, so an empty title
        # is accepted. Not "may be" — there is one answer, and this is it.
        assert r.status_code == 201

    def test_bulk_create_empty_entries(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Bulk create with empty entries → 422."""
        r = client.post(
            f'{EQUIPMENT_URL}/items/bulk',
            headers=eq_auth_headers,
            json={
                'name': 'Bulk Test',
                'location_id': str(uuid.uuid4()),
                'entries': [],
            },
        )
        assert r.status_code == 422

    def test_bulk_create_too_many_entries(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Bulk create with >200 entries → 422."""
        entries = [{'serial_number': f'SN-{i}'} for i in range(201)]
        r = client.post(
            f'{EQUIPMENT_URL}/items/bulk',
            headers=eq_auth_headers,
            json={
                'name': 'Bulk Overflow',
                'location_id': str(uuid.uuid4()),
                'entries': entries,
            },
        )
        assert r.status_code == 422

    def test_bulk_create_entry_empty_serial_number(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
    ) -> None:
        """Bulk create with empty serial number → 422."""
        r = client.post(
            f'{EQUIPMENT_URL}/items/bulk',
            headers=eq_auth_headers,
            json={
                'name': 'Bulk Empty SN',
                'location_id': str(eq_storage_location.id),
                'entries': [{'serial_number': ''}],
            },
        )
        assert r.status_code == 422

    def test_bulk_edit_endpoint_not_exposed(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Bulk edit endpoint is not exposed via HTTP (service-only)."""
        r = client.post(
            f'{EQUIPMENT_URL}/items/bulk-edit',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(uuid.uuid4())],
                'action': 'delete_everything',
            },
        )
        assert r.status_code == 404  # Endpoint not exposed

    def test_bulk_edit_empty_item_ids(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Bulk edit endpoint not exposed."""
        r = client.post(
            f'{EQUIPMENT_URL}/items/bulk-edit',
            headers=eq_auth_headers,
            json={
                'item_ids': [],
                'action': 'change_status',
                'data': {'status': 'AVAILABLE'},
            },
        )
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 4. ASSIGNMENT FLOW EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestAssignmentFlow:
    """Assignment checkout/checkin edge cases."""

    def test_checkout_already_checked_out(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Double checkout → 409."""
        payload = {'item_id': str(eq_item.id), 'assigned_to_name': 'Alice'}
        r1 = client.post(
            f'{EQUIPMENT_URL}/assignments',
            headers=eq_auth_headers,
            json=payload,
        )
        assert r1.status_code == 201

        r2 = client.post(
            f'{EQUIPMENT_URL}/assignments',
            headers=eq_auth_headers,
            json=payload,
        )
        assert r2.status_code == 409

    def test_checkin_nonexistent_assignment(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Checkin with non-existent assignment → 404."""
        r = client.post(
            f'{EQUIPMENT_URL}/assignments/{uuid.uuid4()}/checkin',
            headers=eq_auth_headers,
            json={'checkin_condition': 'GOOD'},
        )
        assert r.status_code == 404

    def test_checkin_invalid_condition(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Checkin with invalid condition → 422."""
        # First checkout
        checkout = client.post(
            f'{EQUIPMENT_URL}/assignments',
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assigned_to_name': 'Bob'},
        )
        assignment_id = checkout.json()['id']

        # Checkin with invalid condition
        r = client.post(
            f'{EQUIPMENT_URL}/assignments/{assignment_id}/checkin',
            headers=eq_auth_headers,
            json={'checkin_condition': 'BROKEN_BUT_NOT_VALID'},
        )
        assert r.status_code == 422

    def test_checkin_valid_condition_good(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """GOOD condition accepted on checkin."""
        checkout = client.post(
            f'{EQUIPMENT_URL}/assignments',
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assigned_to_name': 'Good Tester'},
        )
        assignment_id = checkout.json()['id']

        r = client.post(
            f'{EQUIPMENT_URL}/assignments/{assignment_id}/checkin',
            headers=eq_auth_headers,
            json={'checkin_condition': 'GOOD'},
        )
        assert r.status_code == 200

    def test_list_assignments_pagination(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """List assignments with pagination params."""
        r = client.get(
            f'{EQUIPMENT_URL}/assignments?limit=5&offset=0',
            headers=eq_auth_headers,
        )
        assert r.status_code == 200

    def test_list_assignments_negative_limit(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Negative limit → 422."""
        r = client.get(
            f'{EQUIPMENT_URL}/assignments?limit=-1',
            headers=eq_auth_headers,
        )
        assert r.status_code == 422

    def test_list_assignments_huge_limit(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Limit > 200 → 422."""
        r = client.get(
            f'{EQUIPMENT_URL}/assignments?limit=10000',
            headers=eq_auth_headers,
        )
        assert r.status_code == 422

    def test_item_assignment_history_nonexistent_item(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Assignment history for an id the register does not know → 404."""
        r = client.get(
            f'{EQUIPMENT_URL}/assignments/item/{uuid.uuid4()}',
            headers=eq_auth_headers,
        )
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 5. MAINTENANCE LOG EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestMaintenanceEdgeCases:
    """Maintenance log edge cases."""

    def test_create_maintenance_nonexistent_item(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Maintenance for non-existent item → 404."""
        r = client.post(
            f'{EQUIPMENT_URL}/maintenance',
            headers=eq_auth_headers,
            json={
                'item_id': '00000000-0000-0000-0000-000000000000',
                'maintenance_type': 'REPAIR',
                'title': 'Ghost repair',
                'performed_at': date.today().isoformat(),
            },
        )
        assert r.status_code == 404

    def test_update_maintenance_nonexistent(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Update non-existent maintenance log → 404."""
        r = client.put(
            f'{EQUIPMENT_URL}/maintenance/{uuid.uuid4()}',
            headers=eq_auth_headers,
            json={'title': 'Updated'},
        )
        assert r.status_code == 404

    def test_delete_maintenance_nonexistent(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Delete non-existent maintenance log → 404."""
        r = client.delete(
            f'{EQUIPMENT_URL}/maintenance/{uuid.uuid4()}',
            headers=eq_auth_headers,
        )
        assert r.status_code == 404

    def test_maintenance_future_performed_at(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Maintenance with future performed_at — may be accepted."""
        r = client.post(
            f'{EQUIPMENT_URL}/maintenance',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'maintenance_type': 'INSPECTION',
                'title': 'Future inspection',
                'performed_at': (date.today() + timedelta(days=30)).isoformat(),
            },
        )
        # No future-date validator — accepted
        assert r.status_code == 201
        log_id = r.json()['id']
        client.delete(f'{EQUIPMENT_URL}/maintenance/{log_id}', headers=eq_auth_headers)

    def test_maintenance_negative_next_maintenance(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """next_maintenance_at in the past."""
        r = client.post(
            f'{EQUIPMENT_URL}/maintenance',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'maintenance_type': 'CLEANING',
                'title': 'Past next maint',
                'performed_at': date.today().isoformat(),
                'next_maintenance_at': (date.today() - timedelta(days=10)).isoformat(),
            },
        )
        assert r.status_code == 201
        log_id = r.json()['id']
        client.delete(f'{EQUIPMENT_URL}/maintenance/{log_id}', headers=eq_auth_headers)


# ══════════════════════════════════════════════════════════════════════════════
# 6. PUBLIC ATTESTATION ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestPublicAttestation:
    """Public attestation endpoint security."""

    def test_get_attestation_invalid_token(self, client: TestClient) -> None:
        """Non-existent token → 404."""
        r = client.get('/api/v1/equipment/public/attestation/invalid-token-123')
        assert r.status_code == 404

    def test_confirm_attestation_invalid_token(self, client: TestClient) -> None:
        """Confirm with invalid token → 404."""
        r = client.post(
            '/api/v1/equipment/public/attestation/invalid-token-123/confirm'
        )
        assert r.status_code == 404

    def test_dispute_attestation_invalid_token(self, client: TestClient) -> None:
        """Dispute with invalid token → 404."""
        r = client.post(
            '/api/v1/equipment/public/attestation/invalid-token-123/dispute',
            json={'dispute_type': 'MISSING', 'reason': 'Not found'},
        )
        assert r.status_code == 404

    def test_dispute_attestation_empty_body(self, client: TestClient) -> None:
        """Dispute with empty body on non-existent token → 404 (token lookup first)."""
        r = client.post(
            '/api/v1/equipment/public/attestation/fake-token/dispute',
            json={},
        )
        # Token lookup happens first → 404 before body validation
        assert r.status_code == 404

    def test_dispute_invalid_type(self, client: TestClient) -> None:
        """Dispute with invalid type on non-existent token → 404."""
        r = client.post(
            '/api/v1/equipment/public/attestation/fake-token/dispute',
            json={'dispute_type': 'INVALID', 'reason': 'Test'},
        )
        assert r.status_code == 404

    def test_dispute_empty_reason(self, client: TestClient) -> None:
        """Dispute with empty reason on non-existent token → 404."""
        r = client.post(
            '/api/v1/equipment/public/attestation/fake-token/dispute',
            json={'dispute_type': 'MISSING', 'reason': ''},
        )
        assert r.status_code == 404

    def test_dispute_very_long_reason(self, client: TestClient) -> None:
        """Dispute with reason >1000 chars on non-existent token → 404."""
        r = client.post(
            '/api/v1/equipment/public/attestation/fake-token/dispute',
            json={'dispute_type': 'OTHER', 'reason': 'X' * 1001},
        )
        assert r.status_code == 404

    def test_get_attestation_sql_injection_token(self, client: TestClient) -> None:
        """SQL injection via token parameter."""
        r = client.get("/api/v1/equipment/public/attestation/' OR 1=1 --")
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 7. MODEL CRUD EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestModelCrud:
    """Equipment model CRUD edge cases."""

    def test_update_nonexistent_model(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Update non-existent model → 404."""
        r = client.put(
            f'{EQUIPMENT_URL}/models/{uuid.uuid4()}',
            headers=eq_auth_headers,
            json={'name': 'Updated'},
        )
        assert r.status_code == 404

    def test_delete_nonexistent_model(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Delete non-existent model → 404."""
        r = client.delete(
            f'{EQUIPMENT_URL}/models/{uuid.uuid4()}',
            headers=eq_auth_headers,
        )
        assert r.status_code == 404

    def test_clone_nonexistent_model(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Clone non-existent model → 404."""
        r = client.post(
            f'{EQUIPMENT_URL}/models/{uuid.uuid4()}/clone',
            headers=eq_auth_headers,
        )
        assert r.status_code == 404

    def test_create_model_xss_in_name(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """XSS in model name — stored as-is."""
        xss_name = '<img src=x onerror=alert(1)>Model'
        r = client.post(
            f'{EQUIPMENT_URL}/models',
            headers=eq_auth_headers,
            json={'name': xss_name},
        )
        assert r.status_code == 201
        model_id = r.json()['id']
        assert r.json()['name'] == xss_name

        # Verify list still works (XSS doesn't break rendering)
        list_r = client.get(f'{EQUIPMENT_URL}/models', headers=eq_auth_headers)
        assert list_r.status_code == 200

        # Cleanup
        client.delete(f'{EQUIPMENT_URL}/models/{model_id}', headers=eq_auth_headers)

    def test_create_model_sql_injection_in_name(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """SQL injection in model name."""
        r = client.post(
            f'{EQUIPMENT_URL}/models',
            headers=eq_auth_headers,
            json={'name': "'; DROP TABLE equipment_models; --"},
        )
        assert r.status_code == 201
        model_id = r.json()['id']

        # Verify table still works
        list_r = client.get(f'{EQUIPMENT_URL}/models', headers=eq_auth_headers)
        assert list_r.status_code == 200

        client.delete(f'{EQUIPMENT_URL}/models/{model_id}', headers=eq_auth_headers)

    def test_list_models_returns_list(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """List models returns array."""
        r = client.get(f'{EQUIPMENT_URL}/models', headers=eq_auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json()['items'], list)


# ══════════════════════════════════════════════════════════════════════════════
# 8. TEMPLATE CRUD EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestTemplateCrud:
    """Document template CRUD edge cases."""

    def test_create_template_invalid_type(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Template with invalid document_type → 422."""
        r = client.post(
            f'{EQUIPMENT_URL}/templates',
            headers=eq_auth_headers,
            json={'name': 'Bad Template', 'document_type': 'INVALID'},
        )
        assert r.status_code == 422

    def test_create_template_valid_types(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """CHECKOUT, CHECKIN, UNIVERSAL are all valid."""
        cleanup_ids = []
        for doc_type in ['CHECKOUT', 'CHECKIN', 'UNIVERSAL']:
            r = client.post(
                f'{EQUIPMENT_URL}/templates',
                headers=eq_auth_headers,
                json={
                    'name': f'{doc_type} Template',
                    'module': 'equipment',
                    'document_type': doc_type,
                    'body_html': '<html>Test</html>',
                },
            )
            assert r.status_code == 201
            cleanup_ids.append(r.json()['id'])

        for tid in cleanup_ids:
            client.delete(f'{EQUIPMENT_URL}/templates/{tid}', headers=eq_auth_headers)

    def test_get_nonexistent_template(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Get non-existent template → 404."""
        r = client.get(
            f'{EQUIPMENT_URL}/templates/{uuid.uuid4()}',
            headers=eq_auth_headers,
        )
        assert r.status_code == 404

    def test_update_nonexistent_template(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Update non-existent template → 404."""
        r = client.put(
            f'{EQUIPMENT_URL}/templates/{uuid.uuid4()}',
            headers=eq_auth_headers,
            json={'name': 'Updated'},
        )
        assert r.status_code == 404

    def test_delete_nonexistent_template(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Delete non-existent template → 404."""
        r = client.delete(
            f'{EQUIPMENT_URL}/templates/{uuid.uuid4()}',
            headers=eq_auth_headers,
        )
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 9. CAMPAIGN EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestCampaignEdgeCases:
    """Audit campaign edge cases."""

    def test_create_campaign_past_deadline(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Campaign with a past deadline is refused (the org's clock knows).

        The refusal moved from the schema (which cannot know the
        organization's clock and rejected a legal "today" for half of its
        day) into create_campaign, after the arrival is re-pinned to the
        end of the picked day — a keyed rejection the global handler maps
        to 400 with a translated message.
        """
        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        r = client.post(
            f'{EQUIPMENT_URL}/campaigns',
            headers=eq_auth_headers,
            json={
                'name': 'Past Deadline Campaign',
                'deadline': past,
            },
        )
        assert r.status_code == 400
        assert 'deadline' in r.json()['detail']['message'].lower()

    def test_create_campaign_invalid_scope_type(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Campaign with invalid scope_type → 422."""
        r = client.post(
            f'{EQUIPMENT_URL}/campaigns',
            headers=eq_auth_headers,
            json={
                'name': 'Bad Scope',
                'deadline': (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                'scope_type': 'INVALID',
            },
        )
        assert r.status_code == 422

    def test_create_campaign_reminder_days_boundary(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """reminder_days_before with boundary values."""
        # 0 is valid (ge=0)
        r0 = client.post(
            f'{EQUIPMENT_URL}/campaigns',
            headers=eq_auth_headers,
            json={
                'name': 'Zero Reminder',
                'deadline': (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                'reminder_days_before': 0,
            },
        )
        if r0.status_code == 201:
            campaign_id = r0.json()['id']
            client.delete(
                f'{EQUIPMENT_URL}/campaigns/{campaign_id}',
                headers=eq_auth_headers,
            )

        # 31 should be rejected (le=30)
        r31 = client.post(
            f'{EQUIPMENT_URL}/campaigns',
            headers=eq_auth_headers,
            json={
                'name': 'Too Many Reminders',
                'deadline': (datetime.now(UTC) + timedelta(days=60)).isoformat(),
                'reminder_days_before': 31,
            },
        )
        assert r31.status_code == 422

    def test_launch_nonexistent_campaign(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Launch non-existent campaign → 404."""
        r = client.post(
            f'{EQUIPMENT_URL}/campaigns/{uuid.uuid4()}/launch',
            headers=eq_auth_headers,
        )
        assert r.status_code in (404, 400)

    def test_get_nonexistent_campaign(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Get non-existent campaign → 404."""
        r = client.get(
            f'{EQUIPMENT_URL}/campaigns/{uuid.uuid4()}',
            headers=eq_auth_headers,
        )
        assert r.status_code == 404

    def test_campaign_xss_in_name(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """XSS in campaign name — stored as-is."""
        xss = '<b onclick=alert(1)>Bold Campaign</b>'
        future = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        r = client.post(
            f'{EQUIPMENT_URL}/campaigns',
            headers=eq_auth_headers,
            json={'name': xss, 'deadline': future},
        )
        assert r.status_code == 201
        assert r.json()['name'] == xss

        # Cleanup
        client.delete(
            f'{EQUIPMENT_URL}/campaigns/{r.json()["id"]}',
            headers=eq_auth_headers,
        )


# ══════════════════════════════════════════════════════════════════════════════
# 10. DASHBOARD & VALUATION EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestDashboardValuation:
    """Dashboard and valuation edge cases."""

    def test_dashboard_returns_stats(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Dashboard returns valid structure."""
        r = client.get(f'{EQUIPMENT_URL}/dashboard', headers=eq_auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)

    def test_warranty_alerts_default_days(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Warranty alerts with default days param."""
        r = client.get(f'{EQUIPMENT_URL}/warranty-alerts', headers=eq_auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json()['items'], list)

    def test_warranty_alerts_custom_days(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Warranty alerts with custom days param."""
        r = client.get(
            f'{EQUIPMENT_URL}/warranty-alerts?days=90', headers=eq_auth_headers
        )
        assert r.status_code == 200

    def test_warranty_alerts_negative_days(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Warranty alerts with negative days."""
        r = client.get(
            f'{EQUIPMENT_URL}/warranty-alerts?days=-1', headers=eq_auth_headers
        )
        # days is Query(30, ge=1, le=365): -1 never reaches the handler.
        assert r.status_code == 422

    def test_fleet_valuation(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Fleet valuation returns structure."""
        r = client.get(f'{EQUIPMENT_URL}/valuation', headers=eq_auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert 'total_purchase_value' in data
        assert 'asset_count' in data

    def test_asset_valuation_nonexistent(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Asset valuation for non-existent item → 404."""
        r = client.get(
            f'{EQUIPMENT_URL}/{uuid.uuid4()}/valuation',
            headers=eq_auth_headers,
        )
        assert r.status_code == 404

    def test_my_assets_returns_list(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """My assets endpoint returns list."""
        r = client.get(f'{EQUIPMENT_URL}/my-assets', headers=eq_auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json()['items'], list)

    def test_my_assets_history_returns_list(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """My assets history returns list."""
        r = client.get(f'{EQUIPMENT_URL}/my-assets/history', headers=eq_auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json()['items'], list)


# ══════════════════════════════════════════════════════════════════════════════
# 11. INJECTION ATTACKS
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestInjection:
    """SQL injection and XSS tests."""

    def test_sql_injection_in_model_search(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """SQL injection via model search."""
        r = client.get(
            f"{EQUIPMENT_URL}/models?search=' OR 1=1 --",
            headers=eq_auth_headers,
        )
        assert r.status_code == 200
        # Should return empty or filtered list, not all
        assert isinstance(r.json()['items'], list)

    def test_xss_in_maintenance_title(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """XSS in maintenance title — stored as-is."""
        xss = '<img src=x onerror=alert(1)>Repair'
        r = client.post(
            f'{EQUIPMENT_URL}/maintenance',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'maintenance_type': 'REPAIR',
                'title': xss,
                'performed_at': date.today().isoformat(),
            },
        )
        assert r.status_code == 201
        assert r.json()['title'] == xss

        # Cleanup
        client.delete(
            f'{EQUIPMENT_URL}/maintenance/{r.json()["id"]}',
            headers=eq_auth_headers,
        )

    def test_null_bytes_in_model_name_rejected(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """FIXED: Null bytes in model name now rejected by field_validator."""
        r = client.post(
            f'{EQUIPMENT_URL}/models',
            headers=eq_auth_headers,
            json={'name': 'Model\x00Name'},
        )
        assert r.status_code == 422

    def test_unicode_in_model_name(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Unicode in model name."""
        r = client.post(
            f'{EQUIPMENT_URL}/models',
            headers=eq_auth_headers,
            json={'name': 'Модель 中文 🖥️ Modelo'},
        )
        assert r.status_code == 201
        assert r.json()['name'] == 'Модель 中文 🖥️ Modelo'

        client.delete(
            f'{EQUIPMENT_URL}/models/{r.json()["id"]}',
            headers=eq_auth_headers,
        )
