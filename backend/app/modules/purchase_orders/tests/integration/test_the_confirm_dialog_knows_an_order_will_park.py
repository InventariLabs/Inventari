"""The dialog behind Confirm says when nobody could decide the order's approval.

An order with no price, or above the threshold, goes to approval when it is
confirmed. In an organization whose one holder of the approve grant is the
person confirming, that parks it where nobody can answer: the door refuses a
self-decision. The dialog used to promise "the approval queue" for it, and the
reader learned the truth from the queue, afterwards. The answer is known before
the click, so the order answers the same question a document does.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import status
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.user import User

pytestmark = pytest.mark.integration

URL = '/api/v1/purchase-orders'


def _order(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    template: ProductTemplate,
    *,
    unit_price: str | None,
) -> dict[str, Any]:
    line: dict[str, Any] = {
        'product_template_id': str(template.id),
        'quantity_ordered': 1,
    }
    if unit_price is not None:
        line['unit_price'] = unit_price
    made = client.post(
        URL, headers=headers, json={'partner_id': str(partner.id), 'lines': [line]}
    )
    assert made.status_code == status.HTTP_201_CREATED, made.text
    return cast(dict[str, Any], made.json())


def _requirement(
    client: TestClient, headers: dict[str, str], po_id: str
) -> dict[str, Any]:
    told = client.get(f'{URL}/{po_id}/approval-requirement', headers=headers)
    assert told.status_code == status.HTTP_200_OK, told.text
    return cast(dict[str, Any], told.json())


@pytest.fixture
def po_org(h: ModuleTestHelper) -> Organization:
    return h.create_org(
        'Orders With Approvals',
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


@pytest.fixture
def workflow(client: TestClient, po_auth_headers: dict[str, str]) -> None:
    """A threshold of 1000 and one stage open to anyone holding the grant."""
    made = client.post(
        '/api/v1/approvals/workflows',
        headers=po_auth_headers,
        json={
            'target_type': 'purchase_order',
            'requester_scope': {'everyone': True},
            'name': 'Orders over the limit',
            'stages': [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'Team lead',
                    'approver_user_ids': [],
                }
            ],
            'is_active': True,
            'expected_scope': {'holds': 'nothing'},
            'allow_undecidable_stages': True,
        },
    )
    assert made.status_code == status.HTTP_201_CREATED, made.text
    saved = client.put(
        f'{URL}/settings',
        headers=po_auth_headers,
        json={'approval_threshold': '1000'},
    )
    assert saved.status_code == status.HTTP_200_OK, saved.text


@pytest.mark.usefixtures('workflow')
class TestTheOrderKnowsBeforeTheClick:
    @pytest.mark.parametrize('price', [None, '5000.00'], ids=['unpriced', 'over'])
    def test_the_only_holder_of_the_grant_is_told_it_would_park(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Partner,
        po_template: ProductTemplate,
        price: str | None,
    ) -> None:
        po = _order(client, po_auth_headers, po_partner, po_template, unit_price=price)

        told = _requirement(client, po_auth_headers, po['id'])

        assert told == {
            'approval_required': True,
            'approval_solvable': False,
            'undecidable_reason': 'only_the_requester_can_decide',
            'undecidable_stage': 'Team lead',
        }
        # The verdict is a promise about what the button does, so it does that.
        confirmed = client.post(f'{URL}/{po["id"]}/confirm', headers=po_auth_headers)
        assert confirmed.json()['status'] == 'PENDING_APPROVAL'

    def test_a_priced_order_under_the_limit_needs_no_approval_to_confirm(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Partner,
        po_template: ProductTemplate,
    ) -> None:
        po = _order(
            client, po_auth_headers, po_partner, po_template, unit_price='10.00'
        )

        told = _requirement(client, po_auth_headers, po['id'])

        assert told['approval_required'] is False
        confirmed = client.post(f'{URL}/{po["id"]}/confirm', headers=po_auth_headers)
        assert confirmed.json()['status'] == 'CONFIRMED'

    def test_asking_by_hand_where_no_rule_requires_it_is_judged_too(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Partner,
        po_template: ProductTemplate,
    ) -> None:
        """Fails without the fix: the verdict was skipped when no rule asked.

        Request approval parks an order whatever the rules say, so its dialog
        has the same question to put as Confirm, on an order under the limit.
        """
        po = _order(
            client, po_auth_headers, po_partner, po_template, unit_price='10.00'
        )

        told = _requirement(client, po_auth_headers, po['id'])

        assert told == {
            'approval_required': False,
            'approval_solvable': False,
            'undecidable_reason': 'only_the_requester_can_decide',
            'undecidable_stage': 'Team lead',
        }
        # The verdict is a promise about what the button does, so it does that.
        asked = client.post(
            f'{URL}/{po["id"]}/request-approval', headers=po_auth_headers
        )
        assert asked.status_code == status.HTTP_200_OK, asked.text
        parked = client.get(f'{URL}/{po["id"]}', headers=po_auth_headers)
        assert parked.json()['status'] == 'PENDING_APPROVAL'

    def test_a_second_holder_of_the_grant_makes_it_decidable(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
        po_auth_headers: dict[str, str],
        po_partner: Partner,
        po_template: ProductTemplate,
    ) -> None:
        second: User = h.create_user(po_org, email='second@example.com')
        assert second.organization_id == po_org.id
        po = _order(client, po_auth_headers, po_partner, po_template, unit_price=None)

        told = _requirement(client, po_auth_headers, po['id'])

        assert told['approval_required'] is True
        assert told['approval_solvable'] is True
        assert told['undecidable_stage'] is None

    def test_an_organization_that_lets_admins_decide_their_own_has_no_dead_end(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
        po_auth_headers: dict[str, str],
        po_partner: Partner,
        po_template: ProductTemplate,
    ) -> None:
        h.set_module_settings(po_org, 'approvals', {'allow_admin_self_approve': True})
        po = _order(client, po_auth_headers, po_partner, po_template, unit_price=None)

        told = _requirement(client, po_auth_headers, po['id'])

        assert told['approval_required'] is True
        assert told['approval_solvable'] is True

    def test_an_order_past_its_draft_has_nothing_left_to_confirm(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Partner,
        po_template: ProductTemplate,
    ) -> None:
        po = _order(client, po_auth_headers, po_partner, po_template, unit_price=None)
        client.post(f'{URL}/{po["id"]}/confirm', headers=po_auth_headers)

        told = _requirement(client, po_auth_headers, po['id'])

        assert told['approval_required'] is False
        assert told['approval_solvable'] is True

    def test_another_organizations_order_is_not_there(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_auth_headers: dict[str, str],
        po_partner: Partner,
        po_template: ProductTemplate,
    ) -> None:
        po = _order(client, po_auth_headers, po_partner, po_template, unit_price=None)
        other_org = h.create_org('Elsewhere', ['core', 'purchase_orders', 'approvals'])
        stranger = h.create_user(other_org, email='stranger@example.com')

        told = client.get(
            f'{URL}/{po["id"]}/approval-requirement',
            headers=h.get_auth_headers(stranger),
        )

        assert told.status_code == status.HTTP_404_NOT_FOUND


def _two_stage_workflow(
    client: TestClient, headers: dict[str, str], *, second: dict[str, Any]
) -> None:
    """Stage one is open; ``second`` is the stage the request reaches after it."""
    made = client.post(
        '/api/v1/approvals/workflows',
        headers=headers,
        json={
            'target_type': 'purchase_order',
            'requester_scope': {'everyone': True},
            'name': 'Two stages',
            'stages': [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'Team lead',
                    'approver_user_ids': [],
                },
                {'order': 2, **second},
            ],
            'is_active': True,
            'expected_scope': {'holds': 'nothing'},
            'allow_undecidable_stages': True,
        },
    )
    assert made.status_code == status.HTTP_201_CREATED, made.text


class TestALaterStageIsJudgedToo:
    def test_a_decidable_first_stage_does_not_hide_an_undecidable_second(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
        po_auth_headers: dict[str, str],
        po_partner: Partner,
        po_template: ProductTemplate,
    ) -> None:
        """Fails without the fix: only the first waiting stage was judged.

        A second holder of the grant makes the open first stage decidable; the
        second stage names somebody who cannot see approvals at all, so the
        request would park there one approval later, unannounced.
        """
        h.create_user(po_org, email='second@example.com')
        blind = h.create_user(po_org, email='blind@example.com', role='user')
        _two_stage_workflow(
            client,
            po_auth_headers,
            second={
                'role': 'director',
                'label': 'Director',
                'approver_user_ids': [str(blind.id)],
            },
        )
        po = _order(
            client, po_auth_headers, po_partner, po_template, unit_price='10.00'
        )

        told = _requirement(client, po_auth_headers, po['id'])

        assert told['approval_solvable'] is False
        assert told['undecidable_reason'] == 'named_approvers_cannot_decide'
        assert told['undecidable_stage'] == 'Director'

    def test_every_stage_decidable_is_a_clean_verdict(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
        po_auth_headers: dict[str, str],
        po_partner: Partner,
        po_template: ProductTemplate,
    ) -> None:
        h.create_user(po_org, email='second@example.com')
        _two_stage_workflow(
            client,
            po_auth_headers,
            second={'role': 'director', 'label': 'Director', 'approver_user_ids': []},
        )
        po = _order(
            client, po_auth_headers, po_partner, po_template, unit_price='10.00'
        )

        told = _requirement(client, po_auth_headers, po['id'])

        assert told['approval_solvable'] is True
        assert told['undecidable_stage'] is None


@pytest.mark.usefixtures('workflow')
class TestAParkedOrderWithNothingPendingIsAskedToo:
    def _parked(
        self,
        client: TestClient,
        headers: dict[str, str],
        partner: Partner,
        template: ProductTemplate,
    ) -> dict[str, Any]:
        po = _order(client, headers, partner, template, unit_price='10.00')
        asked = client.post(f'{URL}/{po["id"]}/request-approval', headers=headers)
        assert asked.status_code == status.HTTP_200_OK, asked.text
        return po

    def test_a_withdrawn_request_leaves_the_dead_end_named(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Partner,
        po_template: ProductTemplate,
    ) -> None:
        """Fails without the fix: only a DRAFT was answered."""
        po = self._parked(client, po_auth_headers, po_partner, po_template)
        request = client.get(f'{URL}/{po["id"]}/approval', headers=po_auth_headers)
        withdrawn = client.post(
            f'/api/v1/approvals/requests/{request.json()["id"]}/cancel',
            headers=po_auth_headers,
        )
        assert withdrawn.status_code == status.HTTP_200_OK, withdrawn.text

        told = _requirement(client, po_auth_headers, po['id'])

        assert told == {
            'approval_required': False,
            'approval_solvable': False,
            'undecidable_reason': 'only_the_requester_can_decide',
            'undecidable_stage': 'Team lead',
        }

    def test_an_order_whose_request_is_still_open_has_nothing_to_ask(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Partner,
        po_template: ProductTemplate,
    ) -> None:
        po = self._parked(client, po_auth_headers, po_partner, po_template)

        told = _requirement(client, po_auth_headers, po['id'])

        assert told['approval_required'] is False
        assert told['approval_solvable'] is True


def test_with_no_workflow_there_is_no_stage_to_blame(
    client: TestClient,
    po_auth_headers: dict[str, str],
    po_partner: Partner,
    po_template: ProductTemplate,
) -> None:
    client.put(
        f'{URL}/settings',
        headers=po_auth_headers,
        json={'approval_threshold': '1000'},
    )
    po = _order(client, po_auth_headers, po_partner, po_template, unit_price=None)

    told = _requirement(client, po_auth_headers, po['id'])

    assert told['approval_required'] is True
    assert told['approval_solvable'] is True
    assert told['undecidable_reason'] is None
