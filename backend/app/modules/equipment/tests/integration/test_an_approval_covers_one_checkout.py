"""One approved checkout buys one checkout, not every one from then on.

The gate used to ask only whether the newest request on the asset was
APPROVED. Nothing marked an approval as spent when the checkout it was
raised for happened, so the row stayed APPROVED on the table and its
answer never changed again: check out, check in, check out — the same
old approval kept the door open, for ever, for anybody. That is the
opposite of what the approvals module promises anywhere else: a decision
applies to a pending request, not to everything done after it.

So a checkout spends the approval it was raised for. The next checkout of
the same asset needs its own, and the asset card has to say which of the
two it is looking at — one waiting to be used, or one already used.
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
def checkout_approval_org(h: ModuleTestHelper) -> dict[str, Any]:
    org = h.create_org(
        'Checkout Approval Org',
        ['core', 'items', 'locations', 'categories', 'equipment', 'approvals'],
    )
    admin = h.create_user(org, email=f'adm_{uuid4().hex[:6]}@test.com', role='admin')
    return {'org': org, 'admin': admin, 'h': h}


def _make_item(h: ModuleTestHelper, org: Any, admin: User, db_session: Session) -> Item:
    from app.models.category import Category

    st_type = h.create_storage_type(f'IT {uuid4().hex[:4]}', f'IT_{uuid4().hex[:6]}')
    loc = h.create_storage_location(org, st_type, admin, name=f'Loc {uuid4().hex[:4]}')
    cat = Category(
        name='Laptop',
        code=f'LAPTOP_{uuid4().hex[:6]}',
        context_tag='equipment',
        organization_id=None,
        field_definitions=[],
    )
    db_session.add(cat)
    db_session.commit()
    db_session.refresh(cat)
    item = Item(
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
    return item


def _open_workflow(client: TestClient, h: ModuleTestHelper, admin: User) -> None:
    resp = client.post(
        '/api/v1/approvals/workflows',
        headers=h.get_auth_headers(admin),
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
    assert resp.status_code == status.HTTP_201_CREATED, resp.text


def _approve_a_checkout(
    client: TestClient, h: ModuleTestHelper, org: Any, admin: User, item: Item
) -> None:
    """Raise a checkout request for the asset and have the admin approve it."""
    requester = h.create_user(org, email=f'req_{uuid4().hex[:6]}@test.com')
    raised = client.post(
        '/api/v1/approvals/requests',
        headers=h.get_auth_headers(requester),
        json={'target_type': 'equipment_checkout', 'target_id': str(item.id)},
    )
    assert raised.status_code == status.HTTP_201_CREATED, raised.text
    req_id = raised.json()['id']

    approved = client.post(
        f'/api/v1/approvals/requests/{req_id}/approve',
        headers=h.get_auth_headers(admin),
        json={'notes': 'ok'},
    )
    assert approved.status_code == status.HTTP_200_OK, approved.text


@pytest.mark.integration
class TestAnApprovalCoversOneCheckout:
    def test_a_second_checkout_needs_its_own_approval(
        self,
        client: TestClient,
        checkout_approval_org: dict[str, Any],
        db_session: Session,
    ) -> None:
        org = checkout_approval_org['org']
        admin: User = checkout_approval_org['admin']
        h: ModuleTestHelper = checkout_approval_org['h']
        item = _make_item(h, org, admin, db_session)
        _open_workflow(client, h, admin)
        _approve_a_checkout(client, h, org, admin, item)

        issuer = h.create_user(org, email=f'issuer_{uuid4().hex[:6]}@test.com')
        auth = h.get_auth_headers(issuer)

        first = client.post(
            '/api/v1/equipment/assignments',
            headers=auth,
            json={'item_id': str(item.id), 'assigned_to_name': 'Carol'},
        )
        assert first.status_code == status.HTTP_201_CREATED, first.text

        returned = client.post(
            f'/api/v1/equipment/assignments/{first.json()["id"]}/checkin',
            headers=auth,
            json={},
        )
        assert returned.status_code == status.HTTP_200_OK, returned.text

        second = client.post(
            '/api/v1/equipment/assignments',
            headers=auth,
            json={'item_id': str(item.id), 'assigned_to_name': 'Dave'},
        )
        assert second.status_code == status.HTTP_409_CONFLICT, second.text
        assert 'approval' in second.text.lower()

        # A fresh approval opens the door for exactly one more checkout.
        _approve_a_checkout(client, h, org, admin, item)
        third = client.post(
            '/api/v1/equipment/assignments',
            headers=auth,
            json={'item_id': str(item.id), 'assigned_to_name': 'Erin'},
        )
        assert third.status_code == status.HTTP_201_CREATED, third.text

    def test_the_card_tells_a_waiting_approval_from_a_used_one(
        self,
        client: TestClient,
        checkout_approval_org: dict[str, Any],
        db_session: Session,
    ) -> None:
        org = checkout_approval_org['org']
        admin: User = checkout_approval_org['admin']
        h: ModuleTestHelper = checkout_approval_org['h']
        item = _make_item(h, org, admin, db_session)
        _open_workflow(client, h, admin)
        _approve_a_checkout(client, h, org, admin, item)

        issuer = h.create_user(org, email=f'issuer_{uuid4().hex[:6]}@test.com')
        auth = h.get_auth_headers(issuer)

        waiting = client.get(
            f'/api/v1/equipment/{item.id}/approval-status', headers=auth
        )
        assert waiting.status_code == status.HTTP_200_OK, waiting.text
        assert waiting.json()['status'] == 'APPROVED'
        assert waiting.json()['consumed'] is False

        checked_out = client.post(
            '/api/v1/equipment/assignments',
            headers=auth,
            json={'item_id': str(item.id), 'assigned_to_name': 'Carol'},
        )
        assert checked_out.status_code == status.HTTP_201_CREATED, checked_out.text

        used = client.get(f'/api/v1/equipment/{item.id}/approval-status', headers=auth)
        assert used.status_code == status.HTTP_200_OK, used.text
        assert used.json()['status'] == 'APPROVED'
        assert used.json()['consumed'] is True
