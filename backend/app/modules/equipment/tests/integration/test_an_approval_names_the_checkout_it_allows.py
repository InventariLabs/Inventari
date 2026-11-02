"""A checkout approval says who the asset goes to, and covers only that.

The request used to carry the asset alone: the approver decided without
knowing who would get it or until when, and the approval was then spent by
whichever checkout came next — granted on one person's request and used by
somebody else's hand-out to a third person. The request now names the
checkout it asks for, the approvals queue shows it, and a checkout to anybody
else needs a request of its own. The queue's search finds the request by the
asset name its card shows.
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
def org_with_checkout_workflow(
    h: ModuleTestHelper, client: TestClient, db_session: Session
) -> dict[str, Any]:
    from app.models.category import Category

    org = h.create_org(
        'Named Checkout Org',
        ['core', 'items', 'locations', 'categories', 'equipment', 'approvals'],
    )
    admin = h.create_user(org, email=f'adm_{uuid4().hex[:6]}@test.com', role='admin')
    requester = h.create_user(org, email=f'req_{uuid4().hex[:6]}@test.com')
    st_type = h.create_storage_type(f'IT {uuid4().hex[:4]}', f'IT_{uuid4().hex[:6]}')
    loc = h.create_storage_location(org, st_type, admin, name='IT Storage')
    cat = Category(
        name='Laptop',
        code=f'LAPTOP_{uuid4().hex[:6]}',
        context_tag='equipment',
        organization_id=None,
        field_definitions=[],
    )
    db_session.add(cat)
    db_session.commit()
    item = Item(
        name='Family laptop',
        organization_id=org.id,
        storage_location_id=loc.id,
        category_id=cat.id,
        quantity=1,
        meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    created = client.post(
        '/api/v1/approvals/workflows',
        headers=h.get_auth_headers(admin),
        json={
            'target_type': 'equipment_checkout',
            'requester_scope': {'everyone': True},
            'name': 'Laptop checkout',
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
    assert created.status_code == status.HTTP_201_CREATED, created.text
    return {
        'h': h,
        'org': org,
        'admin': admin,
        'requester': requester,
        'item': item,
    }


def _request_for(
    client: TestClient, ctx: dict[str, Any], body: dict[str, Any] | None
) -> str:
    h: ModuleTestHelper = ctx['h']
    item: Item = ctx['item']
    raised = client.post(
        f'/api/v1/equipment/{item.id}/request-approval',
        headers=h.get_auth_headers(ctx['requester']),
        json=body,
    )
    assert raised.status_code == status.HTTP_200_OK, raised.text
    return str(raised.json()['request_id'])


def _approve(client: TestClient, ctx: dict[str, Any], request_id: str) -> None:
    h: ModuleTestHelper = ctx['h']
    approved = client.post(
        f'/api/v1/approvals/requests/{request_id}/approve',
        headers=h.get_auth_headers(ctx['admin']),
        json={'notes': 'ok'},
    )
    assert approved.status_code == status.HTTP_200_OK, approved.text


def _checkout(client: TestClient, ctx: dict[str, Any], name: str, **holder: str) -> Any:
    h: ModuleTestHelper = ctx['h']
    admin: User = ctx['admin']
    return client.post(
        '/api/v1/equipment/assignments',
        headers=h.get_auth_headers(admin),
        json={'item_id': str(ctx['item'].id), 'assigned_to_name': name, **holder},
    )


@pytest.mark.integration
class TestAnApprovalNamesTheCheckoutItAllows:
    def test_the_queue_card_says_who_gets_the_asset_and_until_when(
        self, client: TestClient, org_with_checkout_workflow: dict[str, Any]
    ) -> None:
        ctx = org_with_checkout_workflow
        h: ModuleTestHelper = ctx['h']
        _request_for(
            client,
            ctx,
            {
                'assigned_to_name': 'Kasia Kowalska',
                'expected_return_at': '2026-11-05T12:00:00Z',
            },
        )

        queue = client.get(
            '/api/v1/approvals/requests', headers=h.get_auth_headers(ctx['admin'])
        )
        assert queue.status_code == status.HTTP_200_OK, queue.text
        (card,) = queue.json()['items']
        asked = card['meta_data']['checkout']
        assert asked['holder'] == 'Kasia Kowalska'
        assert asked['expected_return_at'].startswith('2026-11-05')

    def test_a_checkout_to_somebody_else_is_not_covered(
        self, client: TestClient, org_with_checkout_workflow: dict[str, Any]
    ) -> None:
        ctx = org_with_checkout_workflow
        request_id = _request_for(client, ctx, {'assigned_to_name': 'Kasia Kowalska'})
        _approve(client, ctx, request_id)

        elsewhere = _checkout(client, ctx, 'Piotr Kowalski')
        assert elsewhere.status_code == status.HTTP_409_CONFLICT, elsewhere.text
        assert 'Kasia Kowalska' in elsewhere.text

        # The refusal spent nothing: the checkout it was granted for still goes.
        granted = _checkout(client, ctx, '  kasia kowalska ')
        assert granted.status_code == status.HTTP_201_CREATED, granted.text

    def test_the_name_typed_beside_another_partner_is_not_covered(
        self, client: TestClient, org_with_checkout_workflow: dict[str, Any]
    ) -> None:
        # The asset goes to the partner record when one is picked, whatever
        # the name field says — so the name alone cannot stand in for the
        # holder the request named.
        ctx = org_with_checkout_workflow
        h: ModuleTestHelper = ctx['h']
        request_id = _request_for(client, ctx, {'assigned_to_name': 'Kasia'})
        _approve(client, ctx, request_id)
        piotr = h.create_partner(
            ctx['org'], ctx['admin'], name='Piotr Other', type='EMPLOYEE'
        )

        to_piotr = _checkout(client, ctx, 'Kasia', assignee_partner_id=str(piotr.id))
        assert to_piotr.status_code == status.HTTP_409_CONFLICT, to_piotr.text

        granted = _checkout(client, ctx, 'Kasia')
        assert granted.status_code == status.HTTP_201_CREATED, granted.text

    def test_a_request_naming_nobody_covers_the_next_checkout(
        self, client: TestClient, org_with_checkout_workflow: dict[str, Any]
    ) -> None:
        ctx = org_with_checkout_workflow
        request_id = _request_for(client, ctx, None)
        _approve(client, ctx, request_id)

        assert _checkout(client, ctx, 'Anybody').status_code == status.HTTP_201_CREATED

    def test_the_queue_search_finds_the_request_by_the_asset_name(
        self, client: TestClient, org_with_checkout_workflow: dict[str, Any]
    ) -> None:
        ctx = org_with_checkout_workflow
        h: ModuleTestHelper = ctx['h']
        _request_for(client, ctx, {'assigned_to_name': 'Kasia Kowalska'})

        found = client.get(
            '/api/v1/approvals/requests',
            params={'search': 'laptop'},
            headers=h.get_auth_headers(ctx['admin']),
        )
        assert found.status_code == status.HTTP_200_OK, found.text
        assert found.json()['total'] == 1

        missed = client.get(
            '/api/v1/approvals/requests',
            params={'search': 'printer'},
            headers=h.get_auth_headers(ctx['admin']),
        )
        assert missed.json()['total'] == 0
