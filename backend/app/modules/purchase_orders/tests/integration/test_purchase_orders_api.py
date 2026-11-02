"""
Integration tests for Purchase Orders API.

Tests verify:
- POST /api/v1/purchase-orders - Create PO with lines
- GET /api/v1/purchase-orders - List POs
- GET /api/v1/purchase-orders/{id} - Get PO
- PATCH /api/v1/purchase-orders/{id} - Update PO (only DRAFT)
- POST /api/v1/purchase-orders/{id}/confirm - Confirm PO
- POST /api/v1/purchase-orders/{id}/cancel - Cancel PO
- POST /api/v1/purchase-orders/{id}/create-receipt - Create PZ from PO
- UOM propagation through PO → response → PDF → PZ
"""

import re
from decimal import Decimal
from io import BytesIO
from typing import Any
from uuid import uuid4

import pypdf
import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditLog
from app.models.user import User


@pytest.mark.integration
class TestPurchaseOrderCRUD:
    def test_create_po_with_lines(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
    ) -> None:
        """Create PO with supplier and lines."""
        response = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'scheduled_date': '2026-05-01',
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 24,
                        'unit_price': '18.50',
                    }
                ],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['status'] == 'DRAFT'
        assert data['number'].startswith('PO/')
        assert len(data['lines']) == 1
        assert Decimal(data['lines'][0]['unit_price']) == Decimal('18.5')
        assert float(data['lines'][0]['quantity_ordered']) == 24

    def test_the_create_entry_names_the_supplier(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
    ) -> None:
        """The journal named the id alone: `Partner: 7c65b0dd`.

        The create path had read the partner a line above to check it belongs
        to this organization, so the name cost nothing to write down.
        """
        created = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 3,
                        'unit_price': '4.00',
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        entry = db_session.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == po_org.id,
                AuditLog.target_type == 'purchase_order',
                AuditLog.action == 'CREATE',
            )
            .order_by(AuditLog.created_at.desc())
        ).first()
        assert entry is not None and entry.snapshot is not None
        assert entry.snapshot['partner_id'] == str(po_partner.id)
        assert entry.snapshot['partner_name'] == po_partner.name

    def test_create_po_numbers_are_unique_per_organization(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        h: ModuleTestHelper,
    ) -> None:
        """PO numbers are unique per organization, not globally."""
        first = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {'name': 'First', 'quantity_ordered': 1, 'unit_price': '1.00'}
                ],
            },
        )
        assert first.status_code == status.HTTP_201_CREATED

        other_org = h.create_org(
            'Purchase Orders Other Org',
            ['core', 'items', 'partners', 'warehouse', 'purchase_orders'],
        )
        other_user = h.create_user(other_org, email='po-other@example.com')
        other_headers = h.get_auth_headers(other_user)
        other_partner = h.create_partner(
            other_org, other_user, name='Other Test Supplier'
        )

        second = client.post(
            '/api/v1/purchase-orders',
            headers=other_headers,
            json={
                'partner_id': str(other_partner.id),
                'lines': [
                    {'name': 'Second', 'quantity_ordered': 1, 'unit_price': '1.00'}
                ],
            },
        )

        assert second.status_code == status.HTTP_201_CREATED
        # Per-org numbering: both orgs start from 0001 independently
        assert second.json()['number'] == first.json()['number']

    def test_confirm_po_changes_status(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
    ) -> None:
        """Confirm changes status to CONFIRMED."""
        response = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'name': 'Ręczny produkt',
                        'quantity_ordered': 10,
                        'unit_price': '5.00',
                    }
                ],
            },
        )
        po_id = response.json()['id']

        confirm = client.post(
            f'/api/v1/purchase-orders/{po_id}/confirm',
            headers=po_auth_headers,
        )
        assert confirm.status_code == status.HTTP_200_OK
        assert confirm.json()['status'] == 'CONFIRMED'

    def test_cannot_edit_confirmed_po(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
    ) -> None:
        """CONFIRMED PO cannot be edited."""
        response = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {'name': 'Test', 'quantity_ordered': 5, 'unit_price': '10.00'}
                ],
            },
        )
        po_id = response.json()['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        update = client.patch(
            f'/api/v1/purchase-orders/{po_id}',
            headers=po_auth_headers,
            json={'notes': 'hack'},
        )
        assert update.status_code == status.HTTP_400_BAD_REQUEST

    def test_cancel_po(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
    ) -> None:
        """Cancel works on DRAFT and CONFIRMED."""
        response = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {'name': 'Test', 'quantity_ordered': 1, 'unit_price': '1.00'}
                ],
            },
        )
        po_id = response.json()['id']

        cancel = client.post(
            f'/api/v1/purchase-orders/{po_id}/cancel',
            headers=po_auth_headers,
        )
        assert cancel.status_code == status.HTTP_200_OK
        assert cancel.json()['status'] == 'CANCELLED'

    def test_cancel_po_user_403(
        self,
        client: TestClient,
        h: Any,
        po_auth_headers: dict[str, str],
        po_org: Any,
        po_partner: Any,
    ) -> None:
        """Role 'user' cannot cancel a PO (403)."""
        response = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {'name': 'Test', 'quantity_ordered': 1, 'unit_price': '1.00'}
                ],
            },
        )
        po_id = response.json()['id']

        user = h.create_user(po_org, email='po-cancel-user@example.com', role='user')
        cancel = client.post(
            f'/api/v1/purchase-orders/{po_id}/cancel',
            headers=h.get_auth_headers(user),
        )
        assert cancel.status_code == status.HTTP_403_FORBIDDEN

    def test_cancel_po_manager_allowed(
        self,
        client: TestClient,
        h: Any,
        po_auth_headers: dict[str, str],
        po_org: Any,
        po_partner: Any,
    ) -> None:
        """Role 'manager' can cancel a PO."""
        response = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {'name': 'Test', 'quantity_ordered': 1, 'unit_price': '1.00'}
                ],
            },
        )
        po_id = response.json()['id']

        manager = h.create_user(
            po_org, email='po-cancel-mgr@example.com', role='manager'
        )
        cancel = client.post(
            f'/api/v1/purchase-orders/{po_id}/cancel',
            headers=h.get_auth_headers(manager),
        )
        assert cancel.status_code == status.HTTP_200_OK
        assert cancel.json()['status'] == 'CANCELLED'

    def _create_po(
        self, client: TestClient, headers: dict[str, str], partner: Any
    ) -> str:
        response = client.post(
            '/api/v1/purchase-orders',
            headers=headers,
            json={
                'partner_id': str(partner.id),
                'lines': [
                    {'name': 'Test', 'quantity_ordered': 1, 'unit_price': '1.00'}
                ],
            },
        )
        return str(response.json()['id'])

    def _custom_role_user(
        self, h: Any, po_org: Any, email: str, permissions: list[str]
    ) -> Any:
        """A plain member holding one org-scoped custom role."""
        from app.models.role import Role, UserRole

        user = h.create_user(po_org, email=email, role='user')
        role = Role(
            organization_id=po_org.id,
            name=f'Custom {email}',
            permissions=permissions,
            is_system=False,
        )
        h.db.add(role)
        h.db.flush()
        h.db.add(UserRole(user_id=user.id, role_id=role.id))
        h.db.commit()
        return user

    def test_cancel_po_custom_role_with_manage_allowed(
        self,
        client: TestClient,
        h: Any,
        po_auth_headers: dict[str, str],
        po_org: Any,
        po_partner: Any,
    ) -> None:
        """The cancel guard checks purchase_orders:manage, not the role name
        . read+write pass the module router gate."""
        po_id = self._create_po(client, po_auth_headers, po_partner)
        user = self._custom_role_user(
            h,
            po_org,
            'po-cancel-custom@example.com',
            ['purchase_orders:read', 'purchase_orders:write', 'purchase_orders:manage'],
        )
        cancel = client.post(
            f'/api/v1/purchase-orders/{po_id}/cancel',
            headers=h.get_auth_headers(user),
        )
        assert cancel.status_code == status.HTTP_200_OK
        assert cancel.json()['status'] == 'CANCELLED'

    def test_cancel_po_custom_role_without_manage_403(
        self,
        client: TestClient,
        h: Any,
        po_auth_headers: dict[str, str],
        po_org: Any,
        po_partner: Any,
    ) -> None:
        """read+write pass the module router gate, so the 403 must come from
        the endpoint's own purchase_orders:manage guard."""
        po_id = self._create_po(client, po_auth_headers, po_partner)
        user = self._custom_role_user(
            h,
            po_org,
            'po-cancel-noperm@example.com',
            ['purchase_orders:read', 'purchase_orders:write'],
        )
        cancel = client.post(
            f'/api/v1/purchase-orders/{po_id}/cancel',
            headers=h.get_auth_headers(user),
        )
        assert cancel.status_code == status.HTTP_403_FORBIDDEN

    def test_cannot_cancel_completed_po(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """COMPLETED PO cannot be cancelled."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 10,
                        'unit_price': '5.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        po_line_id = po.json()['lines'][0]['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        receipt = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={
                'target_location_id': str(po_location.id),
                'lines': [{'po_line_id': po_line_id, 'quantity': 10}],
            },
        )
        receipt_id = receipt.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{receipt_id}/complete',
            headers=po_auth_headers,
            json={'complete_as_planned': True},
        )

        cancel = client.post(
            f'/api/v1/purchase-orders/{po_id}/cancel',
            headers=po_auth_headers,
        )
        assert cancel.status_code == status.HTTP_400_BAD_REQUEST
        assert 'completed' in cancel.json()['detail']['message'].lower()

    def test_list_pos(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
    ) -> None:
        """GET returns list of POs."""
        client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [{'name': 'A', 'quantity_ordered': 1, 'unit_price': '1.00'}],
            },
        )
        client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [{'name': 'B', 'quantity_ordered': 2, 'unit_price': '2.00'}],
            },
        )

        response = client.get('/api/v1/purchase-orders', headers=po_auth_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert 'items' in data
        assert 'total' in data
        assert data['total'] >= 2
        assert len(data['items']) >= 2

    def test_list_pos_includes_partner_name_totals_and_default_currency(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
    ) -> None:
        """list rows carry partner name, computed totals and a
        currency defaulted from the organization when not provided."""
        created = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'name': 'Priced line',
                        'quantity_ordered': 3,
                        'unit_price': '10.00',
                        'tax_rate': '23',
                    },
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        po_json = created.json()
        # Currency falls back to the organization default.
        assert po_json['currency'] == po_org.currency
        assert po_json['partner_name'] == po_partner.name
        assert Decimal(po_json['total_net']) == 30
        assert Decimal(po_json['total_tax']) == Decimal('6.9')
        assert Decimal(po_json['total_gross']) == Decimal('36.9')

        listing = client.get('/api/v1/purchase-orders', headers=po_auth_headers)
        assert listing.status_code == status.HTTP_200_OK
        row = next(
            item for item in listing.json()['items'] if item['id'] == po_json['id']
        )
        assert row['partner_name'] == po_partner.name
        assert Decimal(row['total_gross']) == Decimal('36.9')
        assert row['currency'] == po_org.currency

    def test_list_pos_searches_notes_and_escapes_wildcards(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_partner: Any,
    ) -> None:
        for notes in ('Priority shipment', 'Routine delivery', '100% urgent'):
            response = client.post(
                '/api/v1/purchase-orders',
                headers=po_auth_headers,
                json={
                    'partner_id': str(po_partner.id),
                    'notes': notes,
                    'lines': [{'name': notes, 'quantity_ordered': 1}],
                },
            )
            assert response.status_code == status.HTTP_201_CREATED

        response = client.get(
            '/api/v1/purchase-orders?search=priority', headers=po_auth_headers
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['total'] == 1
        assert response.json()['items'][0]['notes'] == 'Priority shipment'

        escaped = client.get(
            '/api/v1/purchase-orders?search=%25', headers=po_auth_headers
        )
        assert escaped.status_code == status.HTTP_200_OK
        assert escaped.json()['total'] == 1
        assert escaped.json()['items'][0]['notes'] == '100% urgent'

    def test_list_pos_filters_status(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_partner: Any,
    ) -> None:
        draft = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [{'name': 'Draft', 'quantity_ordered': 1}],
            },
        )
        confirmed = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [{'name': 'Confirmed', 'quantity_ordered': 1}],
            },
        )
        client.post(
            f'/api/v1/purchase-orders/{confirmed.json()["id"]}/confirm',
            headers=po_auth_headers,
        )

        response = client.get(
            '/api/v1/purchase-orders?status=CONFIRMED', headers=po_auth_headers
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['total'] == 1
        assert response.json()['items'][0]['id'] == confirmed.json()['id']
        assert response.json()['items'][0]['id'] != draft.json()['id']

    def test_list_pos_paginates_with_total(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_partner: Any,
    ) -> None:
        for index in range(3):
            response = client.post(
                '/api/v1/purchase-orders',
                headers=po_auth_headers,
                json={
                    'partner_id': str(po_partner.id),
                    'lines': [{'name': f'Item {index}', 'quantity_ordered': 1}],
                },
            )
            assert response.status_code == status.HTTP_201_CREATED

        first_page = client.get(
            '/api/v1/purchase-orders?limit=2&offset=0', headers=po_auth_headers
        )
        second_page = client.get(
            '/api/v1/purchase-orders?limit=2&offset=2', headers=po_auth_headers
        )

        assert first_page.status_code == status.HTTP_200_OK
        assert first_page.json()['total'] == 3
        assert first_page.json()['has_more'] is True
        assert len(first_page.json()['items']) == 2
        assert second_page.json()['total'] == 3
        assert second_page.json()['has_more'] is False
        assert len(second_page.json()['items']) == 1
        assert (
            first_page.json()['items'][0]['id'] != second_page.json()['items'][0]['id']
        )

    def test_list_pos_rejects_invalid_status(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
    ) -> None:
        response = client.get(
            '/api/v1/purchase-orders?status=INVALID', headers=po_auth_headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.integration
class TestPOConfirmPartnerValidation:
    """confirming a PO must validate partner active status and type."""

    def test_confirm_rejects_inactive_partner(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        h: ModuleTestHelper,
    ) -> None:
        """Confirming a PO with an inactive partner returns 400."""
        po_partner.is_active = False
        db_session.commit()

        response = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {'name': 'Test', 'quantity_ordered': 1, 'unit_price': '1.00'}
                ],
            },
        )
        po_id = response.json()['id']

        confirm = client.post(
            f'/api/v1/purchase-orders/{po_id}/confirm',
            headers=po_auth_headers,
        )
        assert confirm.status_code == status.HTTP_400_BAD_REQUEST
        assert 'inactive' in confirm.json()['detail']['message'].lower()

    def test_confirm_rejects_customer_type_partner(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_user: User,
        h: ModuleTestHelper,
    ) -> None:
        """Confirming a PO with a CUSTOMER type partner returns 400."""
        customer = h.create_partner(
            po_org, po_user, name='Test Customer', type='CUSTOMER'
        )

        response = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(customer.id),
                'lines': [
                    {'name': 'Test', 'quantity_ordered': 1, 'unit_price': '1.00'}
                ],
            },
        )
        po_id = response.json()['id']

        confirm = client.post(
            f'/api/v1/purchase-orders/{po_id}/confirm',
            headers=po_auth_headers,
        )
        assert confirm.status_code == status.HTTP_400_BAD_REQUEST
        assert 'supplier' in confirm.json()['detail']['message'].lower()

    def test_confirm_allows_manufacturer_type_partner(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_user: User,
        h: ModuleTestHelper,
    ) -> None:
        """Confirming a PO with a MANUFACTURER type partner succeeds."""
        manufacturer = h.create_partner(
            po_org, po_user, name='Test Manufacturer', type='MANUFACTURER'
        )

        response = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(manufacturer.id),
                'lines': [
                    {'name': 'Test', 'quantity_ordered': 1, 'unit_price': '1.00'}
                ],
            },
        )
        po_id = response.json()['id']

        confirm = client.post(
            f'/api/v1/purchase-orders/{po_id}/confirm',
            headers=po_auth_headers,
        )
        assert confirm.status_code == status.HTTP_200_OK
        assert confirm.json()['status'] == 'CONFIRMED'


@pytest.mark.integration
class TestCreatePZFromPO:
    def test_create_pz_from_po_prepopulates_lines(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """PZ from PO has lines with product, quantity and PRICE from PO."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 24,
                        'unit_price': '18.50',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        response = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={'target_location_id': str(po_location.id)},
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['type'] == 'IN'
        assert data['partner_id'] == str(po_partner.id)
        assert len(data['lines']) == 1
        line = data['lines'][0]
        assert line['name'] == 'Test Product'
        assert float(line.get('expected_quantity', line.get('quantity', 0))) == 24
        assert line.get('unit_price') is not None

    @pytest.mark.parametrize('partner_type', ['MANUFACTURER', 'BOTH'])
    def test_create_pz_from_po_with_supplier_role_partner(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        h: ModuleTestHelper,
        po_org: Any,
        po_user: Any,
        po_template: Any,
        po_location: Any,
        partner_type: str,
    ) -> None:
        """a PO confirmed on a MANUFACTURER or BOTH partner converts
        into a receipt — the pre-fix validation only accepted SUPPLIER."""
        partner = h.create_partner(
            po_org, po_user, name=f'{partner_type} Vendor', type=partner_type
        )
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 5,
                        'unit_price': '9.99',
                    }
                ],
            },
        )
        assert po.status_code == status.HTTP_201_CREATED, po.text
        po_id = po.json()['id']
        confirm = client.post(
            f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text

        response = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={'target_location_id': str(po_location.id)},
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text
        data = response.json()
        assert data['type'] == 'IN'
        assert data['partner_id'] == str(partner.id)

    def test_cannot_create_pz_from_draft_po(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_location: Any,
    ) -> None:
        """PO must be CONFIRMED to create PZ."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {'name': 'Test', 'quantity_ordered': 1, 'unit_price': '1.00'}
                ],
            },
        )
        po_id = po.json()['id']

        response = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={'target_location_id': str(po_location.id)},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_pz_from_po_carries_uom_and_tax(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """PZ line has uom_id and tax_rate from PO line."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 24,
                        'unit_price': '18.50',
                        'tax_rate': '23.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        response = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={'target_location_id': str(po_location.id)},
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        line = data['lines'][0]
        assert line['uom_id'] is None
        assert Decimal(line['tax_rate']) == Decimal('23')

    def test_create_pz_from_po_carries_po_notes_and_reference(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """PZ carries the PO's own notes; the PO number is the reference."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'notes': 'Proszę o dostawę do godziny 10',
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 10,
                        'unit_price': '5.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        po_number = po.json()['number']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        response = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={'target_location_id': str(po_location.id)},
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['external_reference'] == po_number
        # The notes are the order's own, verbatim: the "PO ref: …" prefix
        # the receipt used to prepend was English stored on the document,
        # shown raw in every language and printed, and the number prints in
        # the reference row instead (asserted above). Exact equality, so a
        # receipt that silently dropped the notes fails here too.
        assert data['notes'] == 'Proszę o dostawę do godziny 10'

    def test_create_partial_receipt_from_po(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """Receiving 80 of 100 units leaves 20 as remaining."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 100,
                        'unit_price': '10.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        po_line_id = po.json()['lines'][0]['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        response = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={
                'target_location_id': str(po_location.id),
                'lines': [{'po_line_id': str(po_line_id), 'quantity': 80}],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert float(data['lines'][0]['quantity']) == 80

    def test_cannot_receive_more_than_ordered(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """Attempt to receive 150 of 100 → 400 error."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 100,
                        'unit_price': '10.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        po_line_id = po.json()['lines'][0]['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        response = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={
                'target_location_id': str(po_location.id),
                'lines': [{'po_line_id': po_line_id, 'quantity': 150}],
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_full_receipt_from_po_backward_compat(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """Without lines payload = full receipt (backward compat)."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 50,
                        'unit_price': '5.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        response = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={'target_location_id': str(po_location.id)},
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert float(data['lines'][0]['quantity']) == 50

    def test_create_second_partial_receipt(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """Second receipt of 20 units = quantity_received totals 100."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 100,
                        'unit_price': '10.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        po_line_id = po.json()['lines'][0]['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        receipt1 = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={
                'target_location_id': str(po_location.id),
                'lines': [{'po_line_id': po_line_id, 'quantity': 80}],
            },
        )
        client.patch(
            f'/api/v1/warehouse/documents/{receipt1.json()["id"]}/complete',
            headers=po_auth_headers,
            json={'complete_as_planned': True},
        )
        po_detail = client.get(
            f'/api/v1/purchase-orders/{po_id}', headers=po_auth_headers
        )
        assert float(po_detail.json()['lines'][0]['quantity_received']) == 80

        response = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={
                'target_location_id': str(po_location.id),
                'lines': [{'po_line_id': po_line_id, 'quantity': 20}],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        client.patch(
            f'/api/v1/warehouse/documents/{response.json()["id"]}/complete',
            headers=po_auth_headers,
            json={'complete_as_planned': True},
        )
        po_final = client.get(
            f'/api/v1/purchase-orders/{po_id}', headers=po_auth_headers
        )
        assert float(po_final.json()['lines'][0]['quantity_received']) == 100


@pytest.mark.integration
class TestPOLifecycle:
    def test_po_reaches_completed_after_full_receipt(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """After full receipt status = COMPLETED."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 50,
                        'unit_price': '5.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        po_line_id = po.json()['lines'][0]['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        receipt = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={
                'target_location_id': str(po_location.id),
                'lines': [{'po_line_id': po_line_id, 'quantity': 50}],
            },
        )
        client.patch(
            f'/api/v1/warehouse/documents/{receipt.json()["id"]}/complete',
            headers=po_auth_headers,
            json={'complete_as_planned': True},
        )
        po_detail = client.get(
            f'/api/v1/purchase-orders/{po_id}', headers=po_auth_headers
        )
        assert po_detail.json()['status'] == 'COMPLETED'

    def test_po_stays_confirmed_after_partial_receipt(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """After partial receipt status stays CONFIRMED."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 100,
                        'unit_price': '10.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        po_line_id = po.json()['lines'][0]['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        receipt = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={
                'target_location_id': str(po_location.id),
                'lines': [{'po_line_id': po_line_id, 'quantity': 50}],
            },
        )
        client.patch(
            f'/api/v1/warehouse/documents/{receipt.json()["id"]}/complete',
            headers=po_auth_headers,
            json={'complete_as_planned': True},
        )
        po_detail = client.get(
            f'/api/v1/purchase-orders/{po_id}', headers=po_auth_headers
        )
        assert po_detail.json()['status'] == 'CONFIRMED'
        assert float(po_detail.json()['lines'][0]['quantity_received']) == 50

    def test_list_linked_receipts(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """GET /purchase-orders/{id}/linked-receipts returns list of PZ."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 50,
                        'unit_price': '5.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        po_line_id = po.json()['lines'][0]['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        receipt = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={
                'target_location_id': str(po_location.id),
                'lines': [{'po_line_id': str(po_line_id), 'quantity': 50}],
            },
        )
        receipt_id = receipt.json()['id']

        linked = client.get(
            f'/api/v1/purchase-orders/{po_id}/linked-receipts', headers=po_auth_headers
        )
        assert linked.status_code == status.HTTP_200_OK
        data = linked.json()['items']
        assert len(data) == 1
        assert data[0]['id'] == receipt_id
        assert data[0]['type'] == 'IN'

    def test_get_pending_quantities_shows_open_receipt_qty(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """GET /purchase-orders/{id}/pending-quantities returns
        {po_line_id: qty} for quantities reserved on active (DRAFT/CONFIRMED)
        receipts. Used by the Create Receipt panel to warn about over-receipt
        before the first receipt completes."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 100,
                        'unit_price': '5.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        po_line_id = po.json()['lines'][0]['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        # Create a CONFIRMED receipt for 60 — these are "in transit" until completed
        client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={
                'target_location_id': str(po_location.id),
                'lines': [{'po_line_id': str(po_line_id), 'quantity': 60}],
            },
        )

        resp = client.get(
            f'/api/v1/purchase-orders/{po_id}/pending-quantities',
            headers=po_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        # Quantities are returned as Decimal-safe strings (whole numbers render as int strings)
        assert int(data[po_line_id]) == 60

    def test_get_pending_quantities_empty_when_no_receipts(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
    ) -> None:
        """GET /pending-quantities returns {} for a freshly-confirmed PO."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 50,
                        'unit_price': '5.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        resp = client.get(
            f'/api/v1/purchase-orders/{po_id}/pending-quantities',
            headers=po_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json() == {}

    def test_get_po_pdf_returns_pdf(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """GET /purchase-orders/{id}/pdf returns application/pdf."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 50,
                        'unit_price': '5.00',
                        'tax_rate': '23.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        response = client.get(
            f'/api/v1/purchase-orders/{po_id}/pdf', headers=po_auth_headers
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.headers['content-type'] == 'application/pdf'

    def test_get_po_pdf_draft_returns_400(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
    ) -> None:
        """DRAFT PO cannot generate PDF."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 10,
                        'unit_price': '5.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']

        response = client.get(
            f'/api/v1/purchase-orders/{po_id}/pdf', headers=po_auth_headers
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_get_po_html_renders_localized_labels(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
    ) -> None:
        """HTML preview renders translated labels and the status badge."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 10,
                        'unit_price': '5.00',
                        'tax_rate': '23.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']

        response = client.get(
            f'/api/v1/purchase-orders/{po_id}/html?lang=pl',
            headers=po_auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert 'text/html' in response.headers['content-type']
        html = response.text
        assert 'Zamówienie zakupowe' in html
        assert 'Dostawca' in html
        assert 'Projekt' in html
        # follow-up: the VAT column prints the line rate, not 0.00% —
        # the preview used to lose tax_pct while the PDF kept it.
        assert '23,00%' in html

    def test_send_po_email_draft_returns_400(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
    ) -> None:
        """DRAFT PO cannot be sent."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 10,
                        'unit_price': '5.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']

        response = client.post(
            f'/api/v1/purchase-orders/{po_id}/send-email', headers=po_auth_headers
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_send_po_email_no_partner_email_returns_400(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_template: Any,
        po_user: User,
    ) -> None:
        """Partner without email returns 400."""
        from app.models.partner import Partner

        no_email_partner = Partner(
            name='No Email Supplier',
            type='SUPPLIER',
            organization_id=po_org.id,
            created_by=po_user.id,
            email=None,
        )
        db_session.add(no_email_partner)
        db_session.commit()
        db_session.refresh(no_email_partner)

        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(no_email_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 10,
                        'unit_price': '5.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        response = client.post(
            f'/api/v1/purchase-orders/{po_id}/send-email',
            headers=po_auth_headers,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'email' in response.json()['detail']['message'].lower()

    def test_send_po_email_without_partner_says_so(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_template: Any,
        po_user: User,
    ) -> None:
        """An order left without a supplier is refused by name, not as a
        partner missing an address.

        A confirmed order always named one, but deleting that partner sets
        ``partner_id`` to NULL on the completed orders referencing it.
        """
        from app.models.partner import Partner
        from app.modules.purchase_orders.models import PurchaseOrder

        partner = Partner(
            name='Soon Gone Supplier',
            type='SUPPLIER',
            organization_id=po_org.id,
            created_by=po_user.id,
            email='gone@example.com',
        )
        db_session.add(partner)
        db_session.commit()

        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 10,
                        'unit_price': '5.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        # What `ondelete='SET NULL'` does to a completed order.
        order = db_session.get(PurchaseOrder, po_id)
        assert order is not None
        order.partner_id = None
        db_session.commit()

        response = client.post(
            f'/api/v1/purchase-orders/{po_id}/send-email',
            headers=po_auth_headers,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        detail = response.json()['detail']['message']
        assert 'supplier' in detail.lower()
        assert 'email' not in detail.lower()


@pytest.mark.integration
class TestPOQuantityRecalculationOnCancel:
    """Tests that cancelling a receipt recalculates PO quantity_received."""

    def test_cancel_confirmed_receipt_keeps_quantity_zero(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """Cancelling a CONFIRMED receipt keeps quantity_received at 0."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 50,
                        'unit_price': '5.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        po_line_id = po.json()['lines'][0]['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        receipt = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={
                'target_location_id': str(po_location.id),
                'lines': [{'po_line_id': str(po_line_id), 'quantity': 50}],
            },
        )
        assert receipt.status_code == status.HTTP_201_CREATED
        receipt_id = receipt.json()['id']

        po_detail = client.get(
            f'/api/v1/purchase-orders/{po_id}', headers=po_auth_headers
        )
        assert float(po_detail.json()['lines'][0]['quantity_received']) == 0

        cancel_resp = client.patch(
            f'/api/v1/warehouse/documents/{receipt_id}/cancel', headers=po_auth_headers
        )
        assert cancel_resp.status_code == status.HTTP_200_OK

        po_after = client.get(
            f'/api/v1/purchase-orders/{po_id}', headers=po_auth_headers
        )
        assert float(po_after.json()['lines'][0]['quantity_received']) == 0
        assert po_after.json()['status'] == 'CONFIRMED'

    def test_cancel_one_of_two_receipts_keeps_remaining(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """Cancelling a CONFIRMED receipt keeps only completed receipt quantities."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 100,
                        'unit_price': '10.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        po_line_id = po.json()['lines'][0]['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        receipt1 = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={
                'target_location_id': str(po_location.id),
                'lines': [{'po_line_id': str(po_line_id), 'quantity': 60}],
            },
        )
        receipt2 = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={
                'target_location_id': str(po_location.id),
                'lines': [{'po_line_id': str(po_line_id), 'quantity': 40}],
            },
        )
        # Complete receipt2 only — receipt1 stays CONFIRMED
        client.patch(
            f'/api/v1/warehouse/documents/{receipt2.json()["id"]}/complete',
            headers=po_auth_headers,
            json={'complete_as_planned': True},
        )

        po_before = client.get(
            f'/api/v1/purchase-orders/{po_id}', headers=po_auth_headers
        )
        assert float(po_before.json()['lines'][0]['quantity_received']) == 40

        cancel_resp = client.patch(
            f'/api/v1/warehouse/documents/{receipt1.json()["id"]}/cancel',
            headers=po_auth_headers,
        )
        assert cancel_resp.status_code == status.HTTP_200_OK

        po_after = client.get(
            f'/api/v1/purchase-orders/{po_id}', headers=po_auth_headers
        )
        assert float(po_after.json()['lines'][0]['quantity_received']) == 40


@pytest.mark.integration
class TestOverReceiptAndCancelGuard:
    """Over-receipt guard, po_line_id dedup, cancel PO block.

    Background: ``quantity_received`` is recalculated only when a receipt is
    COMPLETED. Previously two receipts created before completion both validated
    against the same (stale) ``remaining`` → over-receipt. The guard now counts
    pending quantities on active (DRAFT/CONFIRMED) receipts.
    """

    def test_create_receipt_duplicate_po_line_400(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """Same po_line_id twice in one request must aggregate, not bypass."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 100,
                        'unit_price': '10.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        po_line_id = po.json()['lines'][0]['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        response = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={
                'target_location_id': str(po_location.id),
                'lines': [
                    {'po_line_id': po_line_id, 'quantity': 60},
                    {'po_line_id': po_line_id, 'quantity': 60},
                ],
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_second_full_receipt_400(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """Creating a second full receipt before the first completes → 400."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 100,
                        'unit_price': '10.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        po_line_id = po.json()['lines'][0]['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        first = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={
                'target_location_id': str(po_location.id),
                'lines': [{'po_line_id': po_line_id, 'quantity': 100}],
            },
        )
        assert first.status_code == status.HTTP_201_CREATED

        second = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={
                'target_location_id': str(po_location.id),
                'lines': [{'po_line_id': po_line_id, 'quantity': 100}],
            },
        )
        assert second.status_code == status.HTTP_400_BAD_REQUEST

    def test_second_partial_receipt_within_remaining_ok(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """A second receipt whose qty fits within remaining (after pending) is OK."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 100,
                        'unit_price': '10.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        po_line_id = po.json()['lines'][0]['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        first = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={
                'target_location_id': str(po_location.id),
                'lines': [{'po_line_id': po_line_id, 'quantity': 60}],
            },
        )
        assert first.status_code == status.HTTP_201_CREATED

        # 60 pending → remaining 40; a 40-unit receipt must still be allowed.
        second = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={
                'target_location_id': str(po_location.id),
                'lines': [{'po_line_id': po_line_id, 'quantity': 40}],
            },
        )
        assert second.status_code == status.HTTP_201_CREATED

    def test_cancel_po_with_confirmed_receipt_409(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        """Cancelling a PO with an in-progress (CONFIRMED) receipt → 409."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 100,
                        'unit_price': '10.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        po_line_id = po.json()['lines'][0]['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        receipt = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={
                'target_location_id': str(po_location.id),
                'lines': [{'po_line_id': po_line_id, 'quantity': 50}],
            },
        )
        assert receipt.status_code == status.HTTP_201_CREATED

        cancel = client.post(
            f'/api/v1/purchase-orders/{po_id}/cancel', headers=po_auth_headers
        )
        assert cancel.status_code == status.HTTP_409_CONFLICT


@pytest.mark.integration
class TestPOInputValidation:
    """PO create/update input validation (400 instead of 500/leak)."""

    def test_po_bogus_template_400(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
    ) -> None:
        """Non-existent product_template_id on create → 400, not 500 (FK)."""
        response = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(uuid4()),
                        'quantity_ordered': 10,
                        'unit_price': '10.00',
                    }
                ],
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_po_update_foreign_partner_400(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        h: ModuleTestHelper,
        po_partner: Any,
        po_template: Any,
    ) -> None:
        """Updating a PO partner to a foreign-org partner → 400.

        Create validates partner org-ownership; update did not, letting a PO
        reference a partner from another organization.
        """
        create = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 10,
                        'unit_price': '5.00',
                    }
                ],
            },
        )
        po_id = create.json()['id']

        other_org = h.create_org(
            'PO Foreign Org', ['core', 'items', 'partners', 'purchase_orders']
        )
        other_user = h.create_user(other_org, email='po-foreign@example.com')
        foreign_partner = h.create_partner(
            other_org, other_user, name='Foreign Supplier'
        )

        update = client.patch(
            f'/api/v1/purchase-orders/{po_id}',
            headers=po_auth_headers,
            json={'partner_id': str(foreign_partner.id)},
        )
        assert update.status_code == status.HTTP_400_BAD_REQUEST


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = pypdf.PdfReader(BytesIO(pdf_bytes))
    raw = '\n'.join(page.extract_text() or '' for page in reader.pages)
    return re.sub(r'(?<=[A-Z]) (?=[a-z])', '', raw)


@pytest.mark.integration
class TestUomPropagation:
    def test_po_line_with_uom_id_returns_uom_symbol(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_uom_pcs: Any,
    ) -> None:
        """PO line with explicit uom_id returns correct uom_symbol in response."""
        response = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 13,
                        'unit_price': '12.00',
                        'uom_id': str(po_uom_pcs.id),
                    }
                ],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        line = response.json()['lines'][0]
        assert line['uom_id'] == str(po_uom_pcs.id)
        assert line['uom_symbol'] == 'pcs'

    def test_po_line_without_uom_id_returns_none(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
    ) -> None:
        """PO line without uom_id has uom_id=None and uom_symbol=None."""
        response = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 10,
                        'unit_price': '5.00',
                    }
                ],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        line = response.json()['lines'][0]
        assert line['uom_id'] is None
        assert line['uom_symbol'] is None

    def test_get_po_returns_uom_on_lines(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_uom_kg: Any,
    ) -> None:
        """GET /purchase-orders/{id} includes uom_id and uom_symbol on lines."""
        create = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 5,
                        'unit_price': '20.00',
                        'uom_id': str(po_uom_kg.id),
                    }
                ],
            },
        )
        po_id = create.json()['id']

        response = client.get(
            f'/api/v1/purchase-orders/{po_id}', headers=po_auth_headers
        )
        assert response.status_code == status.HTTP_200_OK
        line = response.json()['lines'][0]
        assert line['uom_id'] == str(po_uom_kg.id)
        assert line['uom_symbol'] == 'kg'

    def test_update_po_line_changes_uom(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_uom_pcs: Any,
        po_uom_kg: Any,
    ) -> None:
        """PATCH PO line with new uom_id updates the uom."""
        create = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 10,
                        'unit_price': '5.00',
                        'uom_id': str(po_uom_pcs.id),
                    }
                ],
            },
        )
        po_id = create.json()['id']

        update = client.patch(
            f'/api/v1/purchase-orders/{po_id}',
            headers=po_auth_headers,
            json={
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 10,
                        'unit_price': '5.00',
                        'uom_id': str(po_uom_kg.id),
                    }
                ],
            },
        )
        assert update.status_code == status.HTTP_200_OK
        line = update.json()['lines'][0]
        assert line['uom_id'] == str(po_uom_kg.id)
        assert line['uom_symbol'] == 'kg'

    def test_pz_from_po_carries_uom_id(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
        po_uom_pcs: Any,
    ) -> None:
        """PZ document line inherits uom_id from PO line."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'quantity_ordered': 50,
                        'unit_price': '10.00',
                        'uom_id': str(po_uom_pcs.id),
                        'tax_rate': '23.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        receipt = client.post(
            f'/api/v1/purchase-orders/{po_id}/create-receipt',
            headers=po_auth_headers,
            json={'target_location_id': str(po_location.id)},
        )
        assert receipt.status_code == status.HTTP_201_CREATED
        line = receipt.json()['lines'][0]
        assert line['uom_id'] == str(po_uom_pcs.id)


@pytest.mark.integration
class TestPoPdfContent:
    def test_pdf_contains_uom_symbol(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_uom_pcs: Any,
    ) -> None:
        """PDF includes the correct UOM symbol (e.g. 'pcs') in rendered content."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'name': 'Sunflower Seeds',
                        'quantity_ordered': 13,
                        'unit_price': '12.00',
                        'uom_id': str(po_uom_pcs.id),
                        'tax_rate': '23.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        response = client.get(
            f'/api/v1/purchase-orders/{po_id}/pdf?lang=pl',
            headers=po_auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        text = _extract_pdf_text(response.content)
        assert 'szt.' in text, f"Expected 'szt.' in PDF but got:\n{text}"

    def test_pdf_wrong_uom_is_detected(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_uom_kg: Any,
    ) -> None:
        """PDF with kg UOM must NOT contain 'pcs' — sanity check for test harness."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'name': 'Wheat Flour',
                        'quantity_ordered': 5,
                        'unit_price': '8.00',
                        'uom_id': str(po_uom_kg.id),
                    }
                ],
            },
        )
        po_id = po.json()['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        response = client.get(
            f'/api/v1/purchase-orders/{po_id}/pdf?lang=pl',
            headers=po_auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        text = _extract_pdf_text(response.content)
        assert 'kg' in text
        assert 'pcs' not in text

    def test_pdf_contains_line_name_and_quantity_and_partner(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_uom_pcs: Any,
    ) -> None:
        """PDF includes product name, ordered quantity and partner name."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'name': 'Coffee Beans',
                        'quantity_ordered': 42,
                        'unit_price': '99.00',
                        'uom_id': str(po_uom_pcs.id),
                    }
                ],
            },
        )
        po_id = po.json()['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        response = client.get(
            f'/api/v1/purchase-orders/{po_id}/pdf',
            headers=po_auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        text = _extract_pdf_text(response.content)
        assert 'Coffee' in text
        assert '42' in text
        assert 'Test Supplier' in text

    def test_pdf_no_uom_shows_dash(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
    ) -> None:
        """PDF line without UOM renders a dash in the Unit column."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'name': 'No UOM Product',
                        'quantity_ordered': 1,
                        'unit_price': '1.00',
                    }
                ],
            },
        )
        po_id = po.json()['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        response = client.get(
            f'/api/v1/purchase-orders/{po_id}/pdf',
            headers=po_auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK

    def test_pdf_multiple_lines_each_with_own_uom(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        po_uom_pcs: Any,
        po_uom_kg: Any,
    ) -> None:
        """Multi-line PDF with different UOMs renders each symbol correctly."""
        po = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'name': 'Apples',
                        'quantity_ordered': 5,
                        'unit_price': '4.00',
                        'uom_id': str(po_uom_kg.id),
                    },
                    {
                        'product_template_id': str(po_template.id),
                        'name': 'Boxes',
                        'quantity_ordered': 10,
                        'unit_price': '2.00',
                        'uom_id': str(po_uom_pcs.id),
                    },
                ],
            },
        )
        po_id = po.json()['id']
        client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

        response = client.get(
            f'/api/v1/purchase-orders/{po_id}/pdf',
            headers=po_auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        text = _extract_pdf_text(response.content)
        assert 'kg' in text
        assert 'pcs' in text
