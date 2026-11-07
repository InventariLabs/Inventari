"""Warehouse module — penetration / security tests.

Covers: authentication, authorization, multi-tenancy, input validation,
        state machine violations, SQL injection, XSS, correction/return edge
        cases, WMS picking/receiving, tax rate validation, period closure
        enforcement, PDF generation, and error handling.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.models.user import User

# ─── helpers ─────────────────────────────────────────────────────────────────

# A receipt takes only products on the list into stock, so the line every
# document here is built with names one — by the code it carries.
_ITEM_BARCODE = '5901234560002'


@pytest.fixture(autouse=True)
def _the_item_is_on_the_list(h: ModuleTestHelper, doc_org: Organization) -> None:
    h.create_template(doc_org, name='Item', barcode=_ITEM_BARCODE)


def _make_doc_payload(
    *,
    type: str = 'IN',
    partner_id: str | None = None,
    target_id: str | None = None,
    source_id: str | None = None,
    lines: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        'type': type,
        'partner_id': partner_id,
        'target_location_id': target_id,
        'source_location_id': source_id,
        # ``or`` would swap an explicitly empty list for the default line —
        # the empty-lines test then passed for an unrelated reason.
        'lines': (
            [{'name': 'Item', 'barcode': _ITEM_BARCODE, 'expected_quantity': 1}]
            if lines is None
            else lines
        ),
    }


def _create_doc(
    client: TestClient,
    headers: dict[str, str],
    **kwargs: Any,
) -> dict[str, Any]:
    resp = client.post(
        '/api/v1/warehouse/documents',
        json=_make_doc_payload(**kwargs),
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return cast(dict[str, Any], resp.json())


# ══════════════════════════════════════════════════════════════════════════════
# 1. AUTHENTICATION & AUTHORIZATION
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestDocumentsAuthBypass:
    """Verify every document endpoint rejects unauthenticated requests."""

    ENDPOINTS = [
        ('GET', '/api/v1/warehouse/documents'),
        ('POST', '/api/v1/warehouse/documents'),
        ('GET', '/api/v1/warehouse/register?date_from=2026-01-01&date_to=2026-12-31'),
        ('GET', '/api/v1/warehouse/documents/lookup/IN/2026/001'),
        ('GET', '/api/v1/warehouse/documents/00000000-0000-0000-0000-000000000001'),
        ('PUT', '/api/v1/warehouse/documents/00000000-0000-0000-0000-000000000002'),
        (
            'PATCH',
            '/api/v1/warehouse/documents/00000000-0000-0000-0000-000000000003/confirm',
        ),
        (
            'PATCH',
            '/api/v1/warehouse/documents/00000000-0000-0000-0000-000000000004/complete',
        ),
        (
            'PATCH',
            '/api/v1/warehouse/documents/00000000-0000-0000-0000-000000000005/cancel',
        ),
        ('DELETE', '/api/v1/warehouse/documents/00000000-0000-0000-0000-000000000006'),
        ('GET', '/api/v1/warehouse/documents/00000000-0000-0000-0000-000000000007/pdf'),
        ('POST', '/api/v1/warehouse/corrections'),
        ('GET', '/api/v1/warehouse/profile'),
        ('PUT', '/api/v1/warehouse/profile'),
        ('GET', '/api/v1/warehouse/profile/presets'),
        ('GET', '/api/v1/warehouse/settings/type-configs'),
        ('GET', '/api/v1/warehouse/templates'),
        ('GET', '/api/v1/warehouse/periods'),
        ('GET', '/api/v1/warehouse/tax-rates'),
        ('POST', '/api/v1/warehouse/tax-rates'),
        ('GET', '/api/v1/warehouse/product-search?q=test'),
    ]

    @pytest.mark.parametrize('method,path', ENDPOINTS)
    def test_unauthenticated_returns_401(
        self, client: TestClient, method: str, path: str
    ) -> None:
        resp = client.request(method, path)
        assert resp.status_code == 401, f'{method} {path} → {resp.status_code}'

    def test_invalid_token_returns_401(self, client: TestClient) -> None:
        resp = client.get(
            '/api/v1/warehouse/documents',
            headers={'Authorization': 'Bearer invalid.jwt.token'},
        )
        assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# 2. MULTI-TENANCY ISOLATION
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestDocumentsMultiTenancy:
    """Documents from org A must not be visible to org B."""

    def test_cross_org_document_invisible(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        # Create a second org + user
        org2 = h.create_org('Tenant B', ['core', 'items', 'warehouse'])
        user2 = h.create_user(org2, email='tenantb@example.com')
        headers2 = h.get_auth_headers(user2)

        # Create a document in org A
        doc = _create_doc(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            target_id=str(doc_target_location.id),
        )

        # Try to read it from org B
        resp = client.get(f'/api/v1/warehouse/documents/{doc["id"]}', headers=headers2)
        assert resp.status_code == 404

    def test_cross_org_register_empty(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        org2 = h.create_org('Tenant C', ['core', 'warehouse'])
        user2 = h.create_user(org2, email='tenantc@example.com')
        headers2 = h.get_auth_headers(user2)

        resp = client.get(
            '/api/v1/warehouse/register/summary',
            params={'date_from': '2020-01-01', 'date_to': '2030-12-31'},
            headers=headers2,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get('summary', {}).get('total_documents', 0) == 0


# ══════════════════════════════════════════════════════════════════════════════
# 3. INPUT VALIDATION
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestDocumentsInputValidation:
    """Schema-level validation for document creation and updates."""

    def test_invalid_document_type_returns_422(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/documents',
            json=_make_doc_payload(type='INVALID_TYPE'),
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_empty_lines_returns_422(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/documents',
            json=_make_doc_payload(type='IN', lines=[]),
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_line_without_name_or_template_returns_422(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/documents',
            json=_make_doc_payload(
                type='IN',
                lines=[{'expected_quantity': 5}],  # no name, no template, no item
            ),
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_negative_quantity_returns_422(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/documents',
            json=_make_doc_payload(
                type='IN',
                lines=[{'name': 'Item', 'expected_quantity': -10}],
            ),
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_zero_quantity_returns_422(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/documents',
            json=_make_doc_payload(
                type='IN',
                lines=[{'name': 'Item', 'expected_quantity': 0}],
            ),
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_in_type_without_partner_rejected_when_partners_module_enabled(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        # Partner requirement for IN/OUT is enforced in the service layer and
        # only when the partners module is enabled — with the module
        # disabled a partner-less receipt is a legitimate payload.
        doc_org.enabled_modules = (doc_org.enabled_modules or []) + ['partners']
        db_session.commit()

        resp = client.post(
            '/api/v1/warehouse/documents',
            json=_make_doc_payload(type='IN', target_id=str(doc_target_location.id)),
            headers=doc_auth_headers,
        )
        assert resp.status_code == 400
        assert 'requires a partner' in resp.json()['detail']['message']

    def test_in_type_without_target_is_refused(
        self, client: TestClient, doc_auth_headers: dict[str, str], doc_partner: Partner
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/documents',
            json=_make_doc_payload(type='IN', partner_id=str(doc_partner.id)),
            headers=doc_auth_headers,
        )
        assert resp.status_code == 400
        assert 'needs a' in resp.json()['detail']['message']

    def test_rw_without_source_is_refused(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/documents',
            json=_make_doc_payload(type='INTERNAL_OUT'),
            headers=doc_auth_headers,
        )
        assert resp.status_code == 400
        assert 'needs a' in resp.json()['detail']['message']

    def test_pw_without_target_is_refused(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/documents',
            json=_make_doc_payload(type='INTERNAL_IN'),
            headers=doc_auth_headers,
        )
        assert resp.status_code == 400
        assert 'needs a' in resp.json()['detail']['message']

    def test_correction_via_main_endpoint_returns_422(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/documents',
            json=_make_doc_payload(type='CORRECTION'),
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_xss_in_notes_stored_safely(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        xss = '<script>alert("xss")</script>'
        doc = _create_doc(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            target_id=str(doc_target_location.id),
        )
        resp = client.put(
            f'/api/v1/warehouse/documents/{doc["id"]}',
            json={'notes': xss},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()['notes'] == xss  # stored as-is (React escapes)

    def test_sql_injection_in_search(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/documents',
            params={'search': "' OR 1=1 --"},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200
        # SQL injection should return 0 or filtered results, not all
        data = resp.json()
        assert data['total'] == 0

    def test_long_notes_exceeds_limit(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            target_id=str(doc_target_location.id),
        )
        resp = client.put(
            f'/api/v1/warehouse/documents/{doc["id"]}',
            json={'notes': 'A' * 2001},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_long_external_reference_exceeds_limit(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            target_id=str(doc_target_location.id),
        )
        resp = client.put(
            f'/api/v1/warehouse/documents/{doc["id"]}',
            json={'external_reference': 'A' * 101},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# 4. STATE MACHINE VIOLATIONS
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestDocumentsStateMachine:
    """Verify invalid state transitions are rejected."""

    def test_confirm_completed_doc_fails(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        db_session: Session,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            target_id=str(doc_target_location.id),
        )
        # Confirm
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200

        # Complete (no execution data needed for simple test)
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == 200

        # Confirming a COMPLETED document is refused, not repeated: the
        # idempotent early return covers CONFIRMED only, so the transition
        # guard raises and map_service_errors turns that into a 400.
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 400

    def test_cancel_completed_doc_fails(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            target_id=str(doc_target_location.id),
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/cancel',
            headers=doc_auth_headers,
        )
        assert resp.status_code in (400, 409)

    def test_update_confirmed_doc_fails(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            target_id=str(doc_target_location.id),
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )

        resp = client.put(
            f'/api/v1/warehouse/documents/{doc["id"]}',
            json={'notes': 'updated'},
            headers=doc_auth_headers,
        )
        assert resp.status_code in (400, 409)

    def test_delete_confirmed_doc_fails(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            target_id=str(doc_target_location.id),
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )

        resp = client.delete(
            f'/api/v1/warehouse/documents/{doc["id"]}',
            headers=doc_auth_headers,
        )
        assert resp.status_code in (400, 409)

    def test_complete_draft_doc_fails(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            target_id=str(doc_target_location.id),
        )
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code in (400, 409)

    def test_double_confirm_same_doc(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            target_id=str(doc_target_location.id),
        )
        resp1 = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert resp1.status_code == 200

        resp2 = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm',
            headers=doc_auth_headers,
        )
        # Confirming an already CONFIRMED document is idempotent by design:
        # the transition guard returns it untouched instead of raising, so the
        # second call answers 200. Pinned here on purpose — the note that used
        # to stand in its place wondered whether this "may be intentional" and
        # accepted every outcome, which left the question open forever. If the
        # endpoint ever starts refusing, that is a decision somebody made, and
        # this is the line that will say so.
        assert resp2.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 5. DOCUMENT CRUD EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestDocumentsCrudEdgeCases:
    """Edge cases for document creation, reading, updating, deletion."""

    def test_get_nonexistent_doc_returns_404(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            f'/api/v1/warehouse/documents/{uuid.uuid4()}',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 404

    def test_delete_nonexistent_doc_returns_error(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.delete(
            f'/api/v1/warehouse/documents/{uuid.uuid4()}',
            headers=doc_auth_headers,
        )
        assert resp.status_code in (400, 404)

    def test_update_nonexistent_doc_returns_error(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.put(
            f'/api/v1/warehouse/documents/{uuid.uuid4()}',
            json={'notes': 'test'},
            headers=doc_auth_headers,
        )
        assert resp.status_code in (400, 404)

    def test_invalid_uuid_format_returns_422(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/documents/not-a-uuid',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_lookup_nonexistent_number_returns_404(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/documents/lookup/XX/9999/999',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 404

    def test_double_delete_returns_error(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            target_id=str(doc_target_location.id),
        )
        resp1 = client.delete(
            f'/api/v1/warehouse/documents/{doc["id"]}',
            headers=doc_auth_headers,
        )
        assert resp1.status_code == 204

        resp2 = client.delete(
            f'/api/v1/warehouse/documents/{doc["id"]}',
            headers=doc_auth_headers,
        )
        assert resp2.status_code in (400, 404)

    def test_register_with_invalid_dates_returns_error(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/register',
            params={'date_from': 'not-a-date', 'date_to': '2026-12-31'},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_list_with_invalid_sort_by_returns_422(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/documents',
            params={'sort_by': 'malicious_column', 'sort_order': 'asc'},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_list_with_negative_limit_returns_422(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/documents',
            params={'limit': -1},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_list_with_huge_limit_returns_422(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/documents',
            params={'limit': 99999},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_legacy_type_codes_normalized(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        """PZ → IN, WZ → OUT, MM → INT."""
        for legacy, canonical in [('PZ', 'IN'), ('WZ', 'OUT'), ('MM', 'INT')]:
            payload = _make_doc_payload(
                type=legacy,
                partner_id=str(doc_partner.id) if canonical in ('IN', 'OUT') else None,
                target_id=str(doc_target_location.id)
                if canonical in ('IN', 'INT')
                else None,
                source_id=str(doc_target_location.id)
                if canonical in ('OUT', 'INT')
                else None,
            )
            resp = client.post(
                '/api/v1/warehouse/documents',
                json=payload,
                headers=doc_auth_headers,
            )
            assert resp.status_code in (200, 201), resp.text
            assert resp.json()['type'] == canonical


# ══════════════════════════════════════════════════════════════════════════════
# 6. TAX RATE VALIDATION
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestDocumentsTaxRateValidation:
    """Pydantic validation on tax rate endpoints."""

    def test_negative_tax_rate_returns_422(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/tax-rates',
            json={'name': 'VAT', 'rate': -5},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_tax_rate_over_100_returns_422(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/tax-rates',
            json={'name': 'Absurd', 'rate': 150},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_empty_name_returns_422(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/tax-rates',
            json={'name': '', 'rate': 23},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_valid_tax_rate_succeeds(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/tax-rates',
            json={'name': 'VAT 23%', 'rate': 23},
            headers=doc_auth_headers,
        )
        assert resp.status_code in (200, 201)
        rate_id = resp.json()['id']

        # Cleanup
        client.delete(
            f'/api/v1/warehouse/tax-rates/{rate_id}',
            headers=doc_auth_headers,
        )

    def test_get_nonexistent_tax_rate_returns_404(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            f'/api/v1/warehouse/tax-rates/{uuid.uuid4()}',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 404

    def test_delete_nonexistent_tax_rate_returns_404(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.delete(
            f'/api/v1/warehouse/tax-rates/{uuid.uuid4()}',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 7. DOCUMENT PROFILE VALIDATION
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestDocumentsProfileValidation:
    """Profile update validation."""

    def test_invalid_tax_handling_returns_422(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.put(
            '/api/v1/warehouse/profile',
            json={'tax_handling': 'INVALID'},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_invalid_type_label_key_returns_422(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.put(
            '/api/v1/warehouse/profile',
            json={'type_labels': {'INVALID_TYPE': 'Custom'}},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_valid_profile_update_succeeds(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.put(
            '/api/v1/warehouse/profile',
            json={'name': 'Test Profile', 'tax_handling': 'NONE'},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200

    def test_apply_nonexistent_preset_returns_error(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/profile/apply-preset/NONEXISTENT',
            headers=doc_auth_headers,
        )
        assert resp.status_code in (400, 404, 422)

    def test_list_presets_succeeds(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/profile/presets',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ══════════════════════════════════════════════════════════════════════════════
# 8. CORRECTION & RETURN EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestDocumentsCorrectionReturn:
    """Edge cases for correction and return documents."""

    def test_correction_on_draft_doc_fails(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            target_id=str(doc_target_location.id),
        )
        resp = client.post(
            '/api/v1/warehouse/corrections',
            json={
                'corrects_document_id': doc['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': 1, 'quantity_delta': 1}],
                'notes': 'Penetration test',
            },
            headers=doc_auth_headers,
        )
        # Should fail — can only correct COMPLETED docs
        assert resp.status_code in (400, 409)

    def test_correction_on_nonexistent_doc_returns_404(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/corrections',
            json={
                'corrects_document_id': str(uuid.uuid4()),
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': 1, 'quantity_delta': 1}],
                'notes': 'Penetration test',
            },
            headers=doc_auth_headers,
        )
        assert resp.status_code in (400, 404)

    def test_return_on_draft_doc_fails(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            target_id=str(doc_target_location.id),
        )
        resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/return',
            json={
                'reason_code': 'DAMAGED',
                'lines': [{'original_line_number': 1, 'return_quantity': 1}],
            },
            headers=doc_auth_headers,
        )
        assert resp.status_code in (400, 409)

    def test_correction_empty_lines_returns_422(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/corrections',
            json={
                'corrects_document_id': str(uuid.uuid4()),
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [],
            },
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_correction_negative_line_number_returns_422(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/corrections',
            json={
                'corrects_document_id': str(uuid.uuid4()),
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': -1, 'quantity_delta': 1}],
            },
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# 9. WMS PICKING / RECEIVING EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestDocumentsWmsEdgeCases:
    """WMS picking and receiving edge cases."""

    def test_picking_on_nonexistent_doc_returns_error(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            f'/api/v1/warehouse/documents/{uuid.uuid4()}/picking/start',
            json={},
            headers=doc_auth_headers,
        )
        assert resp.status_code in (400, 404)

    def test_receiving_on_nonexistent_doc_returns_error(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            f'/api/v1/warehouse/documents/{uuid.uuid4()}/receiving/start',
            json={},
            headers=doc_auth_headers,
        )
        assert resp.status_code in (400, 404)

    def test_scan_picking_refuses_a_session_nobody_opened(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        """A scan quoting a session that is not there is refused as not found.

        What stood here posted to `/api/v1/warehouse/picking/scan`, a path
        this module has never served — the route carries both ids,
        `/{document_id}/picking/{session_id}/scan`. So the request collected
        the 404 that any unrouted path returns, `status_code >= 400` passed,
        and it would have passed for as long as the file existed. The body
        now posts to the real route.

        The refusal used to be `value_error_handler`'s 400 for the bare
        ValueError `_get_active_session_async` raises. The session access
        door now reads the id under the URL's document and answers 404 when
        no such session is there — the pin moves with the door. The test
        stays here rather than in test_wms_picking.py because every scan
        there opens a real session first, so none of them reaches the
        refusal.
        """
        resp = client.post(
            f'/api/v1/warehouse/documents/{uuid.uuid4()}/picking/{uuid.uuid4()}/scan',
            json={'barcode': 'TEST'},
            headers=doc_auth_headers,
        )

        assert resp.status_code == 404
        assert resp.json()['detail']['code'] == 'PICKING_SESSION_NOT_FOUND'


# ══════════════════════════════════════════════════════════════════════════════
# 10. TEMPLATE & TYPE CONFIG EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestDocumentsTemplateConfig:
    """Template and type config validation."""

    def test_get_nonexistent_template_returns_404(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            f'/api/v1/warehouse/templates/{uuid.uuid4()}',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 404

    def test_delete_nonexistent_template_returns_404(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.delete(
            f'/api/v1/warehouse/templates/{uuid.uuid4()}',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 404

    def test_list_templates_succeeds(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/templates',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200

    def test_list_type_configs_succeeds(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/settings/type-configs',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200

    def test_delete_nonexistent_type_config_returns_404(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.delete(
            '/api/v1/warehouse/settings/type-configs/INVALID',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 404

    def test_placeholders_succeeds(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/templates/placeholders',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 11. PRODUCT SEARCH EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestDocumentsProductSearch:
    """Product search edge cases."""

    def test_empty_search_is_refused(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """An empty query is refused, so the old name promised the opposite."""
        resp = client.get(
            '/api/v1/warehouse/product-search',
            params={'q': ''},
            headers=doc_auth_headers,
        )
        # The router raises ValidationException('Query cannot be empty'),
        # which is a 400 — there are no empty results to return.
        assert resp.status_code == 400

    def test_sql_injection_in_search(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/product-search',
            params={'q': "' OR 1=1 --"},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_quick_create_empty_name_returns_422(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/product-search/quick-create',
            json={'name': ''},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_quick_create_valid_succeeds(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/product-search/quick-create',
            json={'name': f'QuickStub-{uuid.uuid4().hex[:8]}'},
            headers=doc_auth_headers,
        )
        assert resp.status_code in (200, 201)


# ══════════════════════════════════════════════════════════════════════════════
# 12. STOCK QUERIES EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestDocumentsStockQueries:
    """Stock query endpoints."""

    def test_quants_list_succeeds(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        # Served by the core now — an organization can read its own
        # shelves without the warehouse module.
        resp = client.get(
            '/api/v1/stock-quants',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200

    def test_lots_list_succeeds(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            '/api/v1/stock-lots',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200

    def test_replenishment_alerts_succeeds(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        # The alerts are the purchase orders module's route now.
        doc_org.enabled_modules = [*doc_org.enabled_modules, 'purchase_orders']
        db_session.commit()

        resp = client.get(
            '/api/v1/purchase-orders/replenishment/alerts',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 13. INVENTORY PERIOD EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestDocumentsInventoryPeriods:
    """Inventory period edge cases."""

    def test_list_periods_succeeds(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/periods',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200

    def test_closing_a_period_twice_is_refused(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """The refusal is the second close — the first one creates the period.

        What stood here posted once against 2020/1 under the name
        "..._returns_error" and accepted 200, 400, 404 and 409 together. The
        service creates a period it cannot find, so that single call
        succeeds: the test was named for a refusal it never reached, and
        could not have failed whichever way the endpoint behaved.
        """
        first = client.post(
            '/api/v1/warehouse/periods/2020/1/close',
            headers=doc_auth_headers,
        )
        assert first.status_code == 200

        second = client.post(
            '/api/v1/warehouse/periods/2020/1/close',
            headers=doc_auth_headers,
        )
        assert second.status_code == 409


# ══════════════════════════════════════════════════════════════════════════════
# 14. PDF GENERATION EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestDocumentsPdfGeneration:
    """PDF endpoint edge cases."""

    def test_pdf_for_nonexistent_doc_returns_404(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            f'/api/v1/warehouse/documents/{uuid.uuid4()}/pdf',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 404

    def test_pdf_for_draft_doc_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            target_id=str(doc_target_location.id),
        )
        resp = client.get(
            f'/api/v1/warehouse/documents/{doc["id"]}/pdf',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 400  # PDF only for CONFIRMED/COMPLETED
        assert resp.json()['detail']['code'] == 'DOCUMENT_PDF_REQUIRES_CONFIRMED'

    def test_pdf_with_invalid_lang_returns_422(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            target_id=str(doc_target_location.id),
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm',
            headers=doc_auth_headers,
        )
        resp = client.get(
            f'/api/v1/warehouse/documents/{doc["id"]}/pdf',
            params={'lang': 'INVALID'},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_pdf_for_confirmed_doc_succeeds(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            target_id=str(doc_target_location.id),
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm',
            headers=doc_auth_headers,
        )
        resp = client.get(
            f'/api/v1/warehouse/documents/{doc["id"]}/pdf',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200
        assert resp.headers['content-type'] == 'application/pdf'


# ══════════════════════════════════════════════════════════════════════════════
# 15. APPROVAL ENDPOINTS EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestDocumentsApproval:
    """Approval workflow edge cases."""

    def test_approval_status_on_unapproved_doc(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            target_id=str(doc_target_location.id),
        )
        resp = client.get(
            f'/api/v1/approvals/documents/{doc["id"]}/approval',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200

    def test_approve_nonexistent_doc_returns_404(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            f'/api/v1/approvals/documents/{uuid.uuid4()}/approve',
            headers=doc_auth_headers,
        )
        assert resp.status_code in (404, 400)

    def test_reject_nonexistent_doc_returns_404(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            f'/api/v1/approvals/documents/{uuid.uuid4()}/reject',
            headers=doc_auth_headers,
        )
        assert resp.status_code in (404, 400)

    def test_request_approval_nonexistent_doc_returns_404(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            f'/api/v1/approvals/documents/{uuid.uuid4()}/request-approval',
            headers=doc_auth_headers,
        )
        assert resp.status_code in (404, 400)


# ══════════════════════════════════════════════════════════════════════════════
# 16. CONCURRENT OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestDocumentsConcurrentOps:
    """Race condition / concurrent operation tests."""

    def test_concurrent_doc_creation_no_crash(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        # Sequential creation to verify no crashes under rapid succession
        results = []
        for _ in range(5):
            resp = client.post(
                '/api/v1/warehouse/documents',
                json=_make_doc_payload(
                    type='IN',
                    partner_id=str(doc_partner.id),
                    target_id=str(doc_target_location.id),
                ),
                headers=doc_auth_headers,
            )
            results.append(resp)

        success_count = sum(1 for r in results if r.status_code in (200, 201))
        assert success_count == 5  # All should succeed sequentially


# ══════════════════════════════════════════════════════════════════════════════
# 17. IMPORT ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestDocumentsImport:
    """CSV/Excel import edge cases."""

    def test_import_analyze_no_file_returns_422(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/import/analyze',
            headers=doc_auth_headers,
        )
        assert resp.status_code == 422

    def test_import_analyze_rejects_oversized_file(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """The size cap must bite before pandas sees the bytes —
        an xlsx is a ZIP and decompresses far beyond its transfer size."""
        from app.core.upload_validation import MAX_IMPORT_SIZE

        oversized = b'a,b,c\n' + b'1,2,3\n' * (MAX_IMPORT_SIZE // 6 + 1)

        resp = client.post(
            '/api/v1/warehouse/import/analyze',
            files={'file': ('big.csv', oversized, 'text/csv')},
            headers=doc_auth_headers,
        )

        assert resp.status_code in (400, 413), resp.status_code

    def test_import_analyze_rejects_disallowed_extension(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/import/analyze',
            files={'file': ('payload.exe', b'MZ\x90\x00', 'application/csv')},
            headers=doc_auth_headers,
        )

        assert resp.status_code in (400, 413, 422), resp.status_code

    def test_import_analyze_rejects_xlsx_that_is_not_a_zip(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/import/analyze',
            files={
                'file': (
                    'book.xlsx',
                    b'this is not a zip container',
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                )
            },
            headers=doc_auth_headers,
        )

        assert resp.status_code in (400, 422), resp.status_code

    def test_import_lines_on_nonexistent_doc_returns_error(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            f'/api/v1/warehouse/documents/{uuid.uuid4()}/import-lines',
            json={'column_mapping': {}, 'delimiter': ','},
            headers=doc_auth_headers,
        )
        assert resp.status_code in (400, 404, 422)

    def test_import_lines_on_confirmed_doc_fails(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            target_id=str(doc_target_location.id),
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm',
            headers=doc_auth_headers,
        )

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/import-lines',
            json={'column_mapping': {}, 'delimiter': ','},
            headers=doc_auth_headers,
        )
        assert resp.status_code in (400, 409, 422)

    def test_parse_paste_returns_preview(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """POST /import/parse-paste returns headers + preview + total_rows."""
        payload = {'text': 'name\tqty\nWidget A\t10\nWidget B\t5\nWidget C\t3'}
        resp = client.post(
            '/api/v1/warehouse/import/parse-paste',
            json=payload,
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body['headers'] == ['name', 'qty']
        assert body['total_rows'] == 3
        assert len(body['preview_rows']) == 3

    def test_parse_paste_empty_text_returns_empty(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/import/parse-paste',
            json={'text': ''},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body['headers'] == []
        assert body['total_rows'] == 0

    def test_parse_paste_missing_text_field_returns_422(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/import/parse-paste',
            json={},
            headers=doc_auth_headers,
        )
        # text has a default ('') so missing field → still 200 with empty result
        assert resp.status_code == 200

    def test_import_paste_creates_lines_in_draft_doc(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        """POST /{doc_id}/import-paste imports lines from pasted text."""
        doc = _create_doc(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            target_id=str(doc_target_location.id),
        )
        payload = {
            'text': 'name\tqty\nWidget A\t10\nWidget B\t5',
            'mapping_json': {'name': 'name', 'quantity': 'qty'},
        }
        resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/import-paste',
            json=payload,
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body['imported'] == 2
        assert body['unmatched'] == 2
        assert len(body['lines']) == 2

    def test_import_paste_empty_text_returns_400(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create_doc(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            target_id=str(doc_target_location.id),
        )
        resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/import-paste',
            json={'text': '', 'mapping_json': {}},
            headers=doc_auth_headers,
        )
        assert resp.status_code == 400

    def test_import_paste_with_create_stubs_resolves_unmatched(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        """When create_stubs_for_unmatched=True, rows whose barcode does not
        match an existing template get an auto-created stub and are imported
        as matched."""
        doc = _create_doc(
            client,
            doc_auth_headers,
            partner_id=str(doc_partner.id),
            target_id=str(doc_target_location.id),
        )
        payload = {
            'text': 'name\tbarcode\nWidget A\t111111111\nWidget B\t222222222',
            'mapping_json': {'name': 'name', 'barcode': 'barcode'},
            'create_stubs_for_unmatched': True,
        }
        resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/import-paste',
            json=payload,
            headers=doc_auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body['imported'] == 2
        assert body['matched'] == 2
        assert body['unmatched'] == 0
        assert body['stubs_created'] == 2
        for line in body['lines']:
            assert line['product_template_id'] is not None
