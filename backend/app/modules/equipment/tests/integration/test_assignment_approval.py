"""Checkout approvals gate.

Covers the wiring of ``approvals_api.check_and_block`` into equipment
``checkout()``. Without a workflow the gate is a no-op (so the existing
~406 equipment tests stay green). When a workflow exists and no APPROVED
request is on record for the item, ``/equipment/assignments`` returns 409.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.user import User


@pytest.fixture
def approval_org(h: ModuleTestHelper) -> dict[str, Any]:
    """An organisation with the approvals module enabled."""
    org = h.create_org(
        'Equip+Approvals Org',
        ['core', 'items', 'locations', 'categories', 'equipment', 'approvals'],
    )
    admin = h.create_user(org, email=f'adm_{uuid4().hex[:6]}@test.com', role='admin')
    return {'org': org, 'admin': admin, 'h': h}


@pytest.mark.integration
class TestCheckoutApprovalsGate:
    """Checkout must be blocked when an approvals workflow exists
    but no APPROVED request has been recorded for the asset."""

    def test_checkout_passes_when_no_workflow_configured(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        """``approvals`` module enabled but no workflow for target_type →
        ``check_and_block`` short-circuits and checkout succeeds."""
        response = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assigned_to_name': 'Alice'},
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_checkout_blocks_when_workflow_exists_without_request(
        self,
        client: TestClient,
        approval_org: dict[str, Any],
        db_session: Session,
    ) -> None:
        """Configure a single-stage workflow; checkout without an APPROVED
        request must return HTTP 409 with the approvals message."""
        from app.models.category import Category
        from app.models.item import Item as ItemModel

        org = approval_org['org']
        admin = approval_org['admin']
        h: ModuleTestHelper = approval_org['h']

        st_type = h.create_storage_type('IT Storage', 'IT_STORAGE')
        loc = h.create_storage_location(org, st_type, admin, name='Loc')
        cat = Category(
            name='Laptop',
            code='LAPTOP',
            context_tag='equipment',
            organization_id=None,
            field_definitions=[],
        )
        db_session.add(cat)
        db_session.commit()
        db_session.refresh(cat)
        item = ItemModel(
            name='ThinkPad X1',
            organization_id=org.id,
            storage_location_id=loc.id,
            category_id=cat.id,
            quantity=1,
            meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        # Approvals services are async-only — seed the workflow via the
        # HTTP API instead of the service layer.
        admin_auth = h.get_auth_headers(admin)
        wf_resp = client.post(
            '/api/v1/approvals/workflows',
            headers=admin_auth,
            json={
                'target_type': 'equipment_checkout',
                'requester_scope': {'everyone': True},
                'name': 'Default Equipment Checkout Approval',
                'stages': [
                    {
                        'order': 1,
                        'role': 'manager',
                        'label': 'Manager Approval',
                        'approver_user_ids': [],
                    }
                ],
                'is_active': True,
                'expected_scope': {'holds': 'all'},
            },
        )
        assert wf_resp.status_code == status.HTTP_201_CREATED, wf_resp.text

        user = h.create_user(org, email=f'usr_{uuid4().hex[:6]}@test.com')
        auth = h.get_auth_headers(user)

        resp = client.post(
            '/api/v1/equipment/assignments',
            headers=auth,
            json={'item_id': str(item.id), 'assigned_to_name': 'Bob'},
        )

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        assert 'approval' in resp.text.lower()

    def test_checkout_passes_when_approved_request_exists(
        self,
        client: TestClient,
        approval_org: dict[str, Any],
        db_session: Session,
    ) -> None:
        """Configure a workflow AND record an APPROVED request for the
        item — checkout must succeed."""
        from app.models.category import Category
        from app.models.item import Item as ItemModel

        org = approval_org['org']
        admin: User = approval_org['admin']
        h: ModuleTestHelper = approval_org['h']

        st_type2 = h.create_storage_type('IT Storage 2', 'IT_STORAGE_2')
        loc = h.create_storage_location(org, st_type2, admin, name='Loc2')
        cat = Category(
            name='Server',
            code='SRV',
            context_tag='equipment',
            organization_id=None,
            field_definitions=[],
        )
        db_session.add(cat)
        db_session.commit()
        db_session.refresh(cat)
        item = ItemModel(
            name='PowerEdge R750',
            organization_id=org.id,
            storage_location_id=loc.id,
            category_id=cat.id,
            quantity=1,
            meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        # Approvals services are async-only — seed workflow/request/
        # approval via the HTTP API instead of the service layer.
        admin_auth = h.get_auth_headers(admin)
        wf_resp = client.post(
            '/api/v1/approvals/workflows',
            headers=admin_auth,
            json={
                'target_type': 'equipment_checkout',
                'requester_scope': {'everyone': True},
                'name': 'Default Equipment Checkout Approval',
                'stages': [
                    {
                        'order': 1,
                        'role': 'manager',
                        'label': 'Manager Approval',
                        'approver_user_ids': [],
                    }
                ],
                'is_active': True,
                'expected_scope': {'holds': 'all'},
            },
        )
        assert wf_resp.status_code == status.HTTP_201_CREATED, wf_resp.text

        requester = h.create_user(org, email=f'req_{uuid4().hex[:6]}@test.com')
        approver = h.create_user(
            org, email=f'mgr_{uuid4().hex[:6]}@test.com', role='admin'
        )
        db_session.commit()

        req_resp = client.post(
            '/api/v1/approvals/requests',
            headers=h.get_auth_headers(requester),
            json={
                'target_type': 'equipment_checkout',
                'target_id': str(item.id),
            },
        )
        assert req_resp.status_code == status.HTTP_201_CREATED, req_resp.text
        req_id = req_resp.json()['id']

        approve_resp = client.post(
            f'/api/v1/approvals/requests/{req_id}/approve',
            headers=h.get_auth_headers(approver),
            json={'notes': 'ok'},
        )
        assert approve_resp.status_code == status.HTTP_200_OK, approve_resp.text

        auth = h.get_auth_headers(requester)
        resp = client.post(
            '/api/v1/equipment/assignments',
            headers=auth,
            json={'item_id': str(item.id), 'assigned_to_name': 'Carol'},
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text

    def test_queue_describes_the_equipment_it_asks_about(
        self,
        client: TestClient,
        approval_org: dict[str, Any],
        db_session: Session,
    ) -> None:
        """The approvals queue used to show an equipment checkout as a truncated
        UUID, with no asset name and no link."""
        from app.models.category import Category
        from app.models.item import Item as ItemModel

        org = approval_org['org']
        admin: User = approval_org['admin']
        h: ModuleTestHelper = approval_org['h']

        st_type = h.create_storage_type('IT Storage Q', 'IT_STORAGE_Q')
        loc = h.create_storage_location(org, st_type, admin, name='LocQ')
        cat = Category(
            name='Laptop',
            code='LAPTOP',
            context_tag='equipment',
            organization_id=None,
            field_definitions=[],
        )
        db_session.add(cat)
        db_session.commit()
        db_session.refresh(cat)
        item = ItemModel(
            name='ThinkPad X1',
            organization_id=org.id,
            storage_location_id=loc.id,
            category_id=cat.id,
            quantity=1,
            serial_number='SN-Q-123',
            meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        admin_auth = h.get_auth_headers(admin)
        wf_resp = client.post(
            '/api/v1/approvals/workflows',
            headers=admin_auth,
            json={
                'target_type': 'equipment_checkout',
                'requester_scope': {'everyone': True},
                'name': 'Default Equipment Checkout Approval',
                'stages': [
                    {
                        'order': 1,
                        'role': 'manager',
                        'label': 'Manager Approval',
                        'approver_user_ids': [],
                    }
                ],
                'is_active': True,
                'expected_scope': {'holds': 'all'},
            },
        )
        assert wf_resp.status_code == status.HTTP_201_CREATED, wf_resp.text

        requester = h.create_user(org, email=f'req_{uuid4().hex[:6]}@test.com')
        db_session.commit()

        req_resp = client.post(
            f'/api/v1/equipment/{item.id}/request-approval',
            headers=h.get_auth_headers(requester),
        )
        assert req_resp.status_code == status.HTTP_200_OK, req_resp.text

        queue = client.get(
            '/api/v1/approvals/requests?target_type=equipment_checkout',
            headers=admin_auth,
        )
        assert queue.status_code == status.HTTP_200_OK, queue.text
        rows = queue.json()['items']
        assert rows, 'the request just raised is missing from the queue'

        summary = rows[0]['target_summary']
        assert summary is not None, 'an equipment checkout must describe itself'
        assert summary['number'] == 'ThinkPad X1'
        assert summary['serial_number'] == 'SN-Q-123'
