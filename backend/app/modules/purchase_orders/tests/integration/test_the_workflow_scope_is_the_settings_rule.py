"""What the workflow list says a purchase-order workflow holds is what confirming does.

A purchase-order workflow carries out an approval the order settings ask
for; on its own it holds nothing (``_service_workflow._is_approval_required``
reads the settings, never the workflow). The workflow screen tells an
administrator so before they switch it on — and the sentence comes from this
module, so it cannot drift from the rule confirmation applies.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.user import User

PO_URL = '/api/v1/purchase-orders'
WORKFLOWS = '/api/v1/approvals/workflows'


@pytest.fixture
def org(h: ModuleTestHelper) -> Organization:
    org = h.create_org(
        'PO Scope Org',
        [
            'core',
            'items',
            'locations',
            'categories',
            'warehouse',
            'purchase_orders',
            'approvals',
        ],
    )
    h.set_module_settings(org, 'approvals', {'allow_admin_self_approve': True})
    return org


@pytest.fixture
def user(h: ModuleTestHelper, org: Organization) -> User:
    return h.create_user(org, email='po-scope@example.com')


@pytest.fixture
def headers(h: ModuleTestHelper, user: User) -> dict[str, str]:
    return h.get_auth_headers(user)


@pytest.fixture
def partner(h: ModuleTestHelper, org: Organization, user: User) -> Any:
    return h.create_partner(org, user, name='Scope Supplier')


@pytest.fixture
def template(h: ModuleTestHelper, org: Organization) -> Any:
    return h.create_template(org, name='Scope Product', sku='PO-SCOPE-001')


@pytest.fixture
def workflow_id(client: TestClient, headers: dict[str, str]) -> str:
    resp = client.post(
        WORKFLOWS,
        headers=headers,
        json={
            'target_type': 'purchase_order',
            'requester_scope': {'everyone': True},
            'name': 'Purchase sign-off',
            'is_active': True,
            'expected_scope': {'holds': 'nothing'},
            'stages': [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'Manager Approval',
                    'approver_user_ids': [],
                }
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return str(resp.json()['id'])


def _scope(client: TestClient, headers: dict[str, str], workflow_id: str) -> Any:
    listed = client.get(WORKFLOWS, headers=headers)
    assert listed.status_code == status.HTTP_200_OK, listed.text
    return next(row for row in listed.json()['items'] if row['id'] == workflow_id)[
        'scope'
    ]


def _confirmed_status(
    client: TestClient,
    headers: dict[str, str],
    partner: Any,
    template: Any,
    unit_price: str,
) -> str:
    created = client.post(
        PO_URL,
        headers=headers,
        json={
            'partner_id': str(partner.id),
            'lines': [
                {
                    'product_template_id': str(template.id),
                    'quantity_ordered': 2,
                    'unit_price': unit_price,
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    confirmed = client.post(f'{PO_URL}/{created.json()["id"]}/confirm', headers=headers)
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    return str(confirmed.json()['status'])


def _put_settings(client: TestClient, headers: dict[str, str], **payload: Any) -> None:
    resp = client.put(f'{PO_URL}/settings', headers=headers, json=payload)
    assert resp.status_code == status.HTTP_200_OK, resp.text


@pytest.mark.integration
class TestThePurchaseOrderWorkflowScope:
    def test_without_settings_the_workflow_holds_nothing(
        self,
        client: TestClient,
        headers: dict[str, str],
        partner: Any,
        template: Any,
        workflow_id: str,
    ) -> None:
        scope = _scope(client, headers, workflow_id)
        assert scope == {
            'holds': 'nothing',
            'conditions': [],
            'required_by_settings': [],
        }
        assert (
            _confirmed_status(client, headers, partner, template, '100') == 'CONFIRMED'
        )

    def test_approval_required_holds_every_order(
        self,
        client: TestClient,
        headers: dict[str, str],
        partner: Any,
        template: Any,
        workflow_id: str,
    ) -> None:
        _put_settings(client, headers, approval_required=True)
        scope = _scope(client, headers, workflow_id)
        assert scope['holds'] == 'all'
        assert scope['required_by_settings'] == ['approval_required']
        assert (
            _confirmed_status(client, headers, partner, template, '1')
            == 'PENDING_APPROVAL'
        )

    def test_a_threshold_holds_what_is_above_it_and_foreign_currency(
        self,
        client: TestClient,
        headers: dict[str, str],
        partner: Any,
        template: Any,
        workflow_id: str,
    ) -> None:
        _put_settings(client, headers, approval_threshold='500')
        scope = _scope(client, headers, workflow_id)
        assert scope['holds'] == 'some'
        assert scope['required_by_settings'] == ['approval_threshold']
        above, foreign = scope['conditions']
        assert above['kind'] == 'value_above'
        assert Decimal(above['amount']) == Decimal('500')
        assert above['unpriced_included'] is True
        assert above['currency']
        assert foreign['kind'] == 'foreign_currency'

        # 2 x 100 = 200 stays below the line; 2 x 1000 = 2000 is above it.
        assert (
            _confirmed_status(client, headers, partner, template, '100') == 'CONFIRMED'
        )
        assert (
            _confirmed_status(client, headers, partner, template, '1000')
            == 'PENDING_APPROVAL'
        )
