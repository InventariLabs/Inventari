"""A purchase-order workflow holds the orders of the people it names.

"Every order needs approval" used to mean every order by anybody, the
administrator's included. The workflow now says whose orders it holds, and
an order confirmed by somebody it does not name goes straight to CONFIRMED,
whatever the settings ask of everybody else's.
"""

import pytest
from fastapi import status
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.modules.purchase_orders.tests.integration.test_po_approval import (
    PO_URL,
    _create_po,
    _set_settings,
)


@pytest.mark.integration
class TestAPurchaseOrderWorkflowHoldsOnlyItsRequesters:
    def test_the_named_buyer_waits_and_the_administrator_does_not(
        self,
        client: TestClient,
        h: ModuleTestHelper,
    ) -> None:
        approval_org = h.create_org(
            'PO Requesters Org',
            [
                'core',
                'items',
                'locations',
                'categories',
                'purchase_orders',
                'approvals',
            ],
        )
        h.set_module_settings(
            approval_org, 'approvals', {'allow_admin_self_approve': True}
        )
        approval_user = h.create_user(approval_org, email='po-admin@example.com')
        approval_headers = h.get_auth_headers(approval_user)
        approval_partner = h.create_partner(
            approval_org, approval_user, name='Requesters Supplier'
        )
        approval_template = h.create_template(
            approval_org, name='Requesters Product', sku='PO-REQ-001'
        )
        buyer = h.create_user(approval_org, email='buyer@example.com')
        buyer_headers = h.get_auth_headers(buyer)
        _set_settings(client, approval_headers, approval_required=True)
        created = client.post(
            '/api/v1/approvals/workflows',
            headers=approval_headers,
            json={
                'target_type': 'purchase_order',
                'name': "The buyer's orders",
                'requester_scope': {
                    'everyone': False,
                    'user_ids': [str(buyer.id)],
                    'role_ids': [],
                },
                'is_active': True,
                'expected_scope': {
                    'holds': 'all',
                    'required_by_settings': ['approval_required'],
                },
                'stages': [
                    {
                        'order': 1,
                        'role': 'manager',
                        'label': 'Manager Approval',
                        # Open to any holder of the grant: a stage naming the
                        # administrator alone would decide their own order on
                        # their behalf and hide whether it was held at all.
                        'approver_user_ids': [],
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        own = _create_po(client, approval_headers, approval_partner, approval_template)
        bought = _create_po(client, buyer_headers, approval_partner, approval_template)

        mine = client.post(f'{PO_URL}/{own["id"]}/confirm', headers=approval_headers)
        theirs = client.post(f'{PO_URL}/{bought["id"]}/confirm', headers=buyer_headers)

        assert mine.status_code == status.HTTP_200_OK, mine.text
        assert mine.json()['status'] == 'CONFIRMED'
        assert theirs.status_code == status.HTTP_200_OK, theirs.text
        assert theirs.json()['status'] == 'PENDING_APPROVAL'
