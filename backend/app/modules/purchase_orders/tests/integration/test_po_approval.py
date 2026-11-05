"""Integration tests for the PO approval flow.

Covers: PO settings CRUD, threshold-triggered PENDING_APPROVAL, full
approve flow → CONFIRMED → receipt unblocked, reject → back to DRAFT,
cancel cascade, graceful degradation without a workflow, manual
request-approval.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.user import User

PO_URL = '/api/v1/purchase-orders'


def _create_po(
    client: TestClient,
    headers: dict[str, str],
    partner: Any,
    template: Any,
    *,
    unit_price: str | None = '100.00',
    quantity: int = 2,
) -> dict[str, Any]:
    line: dict[str, Any] = {
        'product_template_id': str(template.id),
        'quantity_ordered': quantity,
    }
    if unit_price is not None:
        line['unit_price'] = unit_price
    resp = client.post(
        PO_URL,
        headers=headers,
        json={'partner_id': str(partner.id), 'lines': [line]},
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    data: dict[str, Any] = resp.json()
    return data


def _set_settings(
    client: TestClient,
    headers: dict[str, str],
    *,
    approval_required: bool | None = None,
    approval_threshold: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if approval_required is not None:
        payload['approval_required'] = approval_required
    if approval_threshold is not None:
        payload['approval_threshold'] = approval_threshold
    resp = client.put(f'{PO_URL}/settings', headers=headers, json=payload)
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


def _create_po_with_currency(
    client: TestClient,
    headers: dict[str, str],
    partner: Any,
    template: Any,
    currency: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """_create_po variant that posts an explicit order currency."""
    resp = client.post(
        PO_URL,
        headers=headers,
        json={
            'partner_id': str(partner.id),
            'currency': currency,
            'lines': [
                {
                    'product_template_id': str(template.id),
                    'quantity_ordered': kwargs.get('quantity', 2),
                    'unit_price': kwargs.get('unit_price', '100.00'),
                }
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    data: dict[str, Any] = resp.json()
    return data


@pytest.fixture
def approval_org(h: ModuleTestHelper) -> Organization:
    org = h.create_org(
        'PO Approval Test Org',
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
    # One user raises and approves in these scenarios; admin self-approval is
    # an organization setting since, off by default.
    h.set_module_settings(org, 'approvals', {'allow_admin_self_approve': True})
    return org


@pytest.fixture
def approval_user(h: ModuleTestHelper, approval_org: Organization) -> User:
    return h.create_user(approval_org, email='po-approval@example.com')


@pytest.fixture
def approval_headers(h: ModuleTestHelper, approval_user: User) -> dict[str, str]:
    return h.get_auth_headers(approval_user)


@pytest.fixture
def approval_partner(
    h: ModuleTestHelper, approval_org: Organization, approval_user: User
) -> Any:
    return h.create_partner(approval_org, approval_user, name='Approval Supplier')


@pytest.fixture
def approval_template(h: ModuleTestHelper, approval_org: Organization) -> Any:
    return h.create_template(
        approval_org, name='Approval Product', sku='PO-APPROVAL-001'
    )


@pytest.fixture
def approval_location(
    h: ModuleTestHelper,
    approval_org: Organization,
    approval_user: User,
) -> Any:
    storage_type = h.create_storage_type('Warehouse', 'WAREHOUSE')
    return h.create_storage_location(
        approval_org,
        storage_type,
        approval_user,
        name='Approval Warehouse',
    )


@pytest.fixture
def approval_workflow(client: TestClient, approval_headers: dict[str, str]) -> None:
    """Seed a single-stage purchase_order workflow via the HTTP API."""
    resp = client.post(
        '/api/v1/approvals/workflows',
        headers=approval_headers,
        json={
            'target_type': 'purchase_order',
            'requester_scope': {'everyone': True},
            'is_active': True,
            'expected_scope': {'holds': 'nothing'},
            'name': 'Test PO Approval',
            'stages': [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'Manager Approval',
                    'approver_user_ids': [],
                },
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text


@pytest.mark.integration
class TestPOSettingsAPI:
    def test_get_settings_returns_defaults(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_org: Organization,
        db_session: Session,
    ) -> None:
        resp = client.get(f'{PO_URL}/settings', headers=approval_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body['organization_id'] == str(approval_org.id)
        assert body['approval_required'] is False
        assert body['approval_threshold'] is None

    def test_put_settings_persists(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
    ) -> None:
        updated = _set_settings(client, approval_headers, approval_threshold='500.00')
        assert Decimal(updated['approval_threshold']) == 500

        fetched = client.get(f'{PO_URL}/settings', headers=approval_headers)
        assert Decimal(fetched.json()['approval_threshold']) == 500

        forced = _set_settings(client, approval_headers, approval_required=True)
        assert forced['approval_required'] is True

    def test_put_settings_clears_the_threshold_with_an_explicit_null(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
    ) -> None:
        """A cleared field is an instruction, not an absence.

        The user who once set a threshold has to be able to take it back:
        the settings screen sends ``approval_threshold: null`` when the
        field is emptied, and the API used to read that as "leave
        unchanged" — the old value survived, and orders above it kept
        routing to approval with no way to stop it.
        """
        _set_settings(client, approval_headers, approval_threshold='500.00')
        resp = client.put(
            f'{PO_URL}/settings',
            headers=approval_headers,
            json={'approval_threshold': None},
        )
        assert resp.status_code == 200
        assert resp.json()['approval_threshold'] is None

        fetched = client.get(f'{PO_URL}/settings', headers=approval_headers)
        assert fetched.json()['approval_threshold'] is None

    def test_put_settings_without_the_field_leaves_the_threshold(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
    ) -> None:
        """An absent field is a no-op for that field: a payload that names
        only the switch must not silently clear the stored threshold."""
        _set_settings(client, approval_headers, approval_threshold='500.00')
        updated = _set_settings(client, approval_headers, approval_required=True)

        assert updated['approval_required'] is True
        assert Decimal(updated['approval_threshold']) == 500

    def test_stored_zero_and_cleared_stay_two_different_states(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
    ) -> None:
        """0.00 and null are different answers the API must be able to
        hold apart: one names a threshold, the other says there is none.
        Clearing therefore writes null — never a zero dressed up as one."""
        zeroed = _set_settings(client, approval_headers, approval_threshold='0.00')
        assert Decimal(zeroed['approval_threshold']) == 0

        cleared = client.put(
            f'{PO_URL}/settings',
            headers=approval_headers,
            json={'approval_threshold': None},
        )
        assert cleared.json()['approval_threshold'] is None


@pytest.mark.integration
@pytest.mark.integration
class TestPOApprovalFlow:
    def test_confirm_without_supplier_is_refused(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_template: Any,
    ) -> None:
        """The supplier is demanded where it can still be added.

        It used to be optional through confirmation and required by the
        receipt — the one screen with no way to add one.
        """
        created = client.post(
            PO_URL,
            headers=approval_headers,
            json={
                'lines': [
                    {
                        'product_template_id': str(approval_template.id),
                        'quantity_ordered': 1,
                        'unit_price': '10.00',
                    }
                ]
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        confirm = client.post(
            f'{PO_URL}/{created.json()["id"]}/confirm', headers=approval_headers
        )
        assert confirm.status_code == status.HTTP_400_BAD_REQUEST, confirm.text
        assert 'supplier' in str(confirm.json()['detail']).lower()

    def test_confirm_without_workflow_is_refused(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
    ) -> None:
        """Approval required with no workflow → refuse, do not confirm silently.

               This used to confirm the PO and call it graceful degradation, so the
               setting a manager switched on to control spending did nothing and said
        nothing. Refusing names the missing piece instead.
        """
        po = _create_po(client, approval_headers, approval_partner, approval_template)
        _set_settings(client, approval_headers, approval_required=True)

        resp = client.post(f'{PO_URL}/{po["id"]}/confirm', headers=approval_headers)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert 'workflow' in str(resp.json()['detail']).lower()

        # The PO stays where it was — nothing was released.
        after = client.get(f'{PO_URL}/{po["id"]}', headers=approval_headers)
        assert after.json()['status'] == 'DRAFT'

    def test_confirm_over_threshold_without_workflow_is_refused(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
    ) -> None:
        """The threshold path reaches the same gate as the blanket setting."""
        po = _create_po(
            client,
            approval_headers,
            approval_partner,
            approval_template,
            unit_price='100.00',
            quantity=2,
        )
        _set_settings(client, approval_headers, approval_threshold='50.00')

        resp = client.post(f'{PO_URL}/{po["id"]}/confirm', headers=approval_headers)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text

    def test_a_zero_threshold_gates_every_priced_order(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
    ) -> None:
        """A stored 0.00 names a threshold, it is not the cleared state —
        an order priced above zero goes to approval, so a missing workflow
        refuses the confirm instead of waving it through. The controls: a positive
        threshold refuses the same order, and a genuinely cleared one
        (explicit null) lets it through — three different readings, one
        column."""
        _set_settings(client, approval_headers, approval_threshold='0.00')
        po = _create_po(
            client,
            approval_headers,
            approval_partner,
            approval_template,
            unit_price='10.00',
            quantity=1,
        )
        resp = client.post(f'{PO_URL}/{po["id"]}/confirm', headers=approval_headers)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text

        _set_settings(client, approval_headers, approval_threshold='50.00')
        po_over = _create_po(
            client,
            approval_headers,
            approval_partner,
            approval_template,
        )
        resp_over = client.post(
            f'{PO_URL}/{po_over["id"]}/confirm', headers=approval_headers
        )
        assert resp_over.status_code == status.HTTP_400_BAD_REQUEST, resp_over.text

        cleared = client.put(
            f'{PO_URL}/settings',
            headers=approval_headers,
            json={'approval_threshold': None},
        )
        assert cleared.status_code == 200, cleared.text
        po_under = _create_po(
            client,
            approval_headers,
            approval_partner,
            approval_template,
            unit_price='10.00',
            quantity=1,
        )
        resp_under = client.post(
            f'{PO_URL}/{po_under["id"]}/confirm', headers=approval_headers
        )
        assert resp_under.status_code == 200, resp_under.text
        assert resp_under.json()['status'] == 'CONFIRMED'

    def test_confirm_below_threshold_without_workflow_succeeds(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
    ) -> None:
        """No approval is due for this PO, so a missing workflow is irrelevant."""
        po = _create_po(
            client,
            approval_headers,
            approval_partner,
            approval_template,
            unit_price='10.00',
            quantity=1,
        )
        _set_settings(client, approval_headers, approval_threshold='5000.00')

        resp = client.post(f'{PO_URL}/{po["id"]}/confirm', headers=approval_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()['status'] == 'CONFIRMED'

    def test_threshold_parks_po_in_pending_approval(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
        approval_workflow: None,
    ) -> None:
        """PO net total above threshold → PENDING_APPROVAL on confirm."""
        _set_settings(client, approval_headers, approval_threshold='150.00')
        # Net = 2 × 100.00 = 200.00 > 150.00 → approval required.
        po = _create_po(client, approval_headers, approval_partner, approval_template)

        resp = client.post(f'{PO_URL}/{po["id"]}/confirm', headers=approval_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()['status'] == 'PENDING_APPROVAL'

    def test_below_threshold_confirms_directly(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
        approval_workflow: None,
    ) -> None:
        _set_settings(client, approval_headers, approval_threshold='500.00')
        po = _create_po(client, approval_headers, approval_partner, approval_template)

        resp = client.post(f'{PO_URL}/{po["id"]}/confirm', headers=approval_headers)
        assert resp.status_code == 200
        assert resp.json()['status'] == 'CONFIRMED'

    def test_an_order_with_no_prices_is_not_below_the_threshold(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
        approval_workflow: None,
    ) -> None:
        """A total nobody stated used to read as zero and pass under any limit."""
        _set_settings(client, approval_headers, approval_threshold='500.00')
        po = _create_po(
            client,
            approval_headers,
            approval_partner,
            approval_template,
            unit_price=None,
        )

        resp = client.post(f'{PO_URL}/{po["id"]}/confirm', headers=approval_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()['status'] == 'PENDING_APPROVAL'

    def test_an_order_priced_at_zero_is_below_the_threshold(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
        approval_workflow: None,
    ) -> None:
        """The control: somebody said zero, and zero is under five hundred."""
        _set_settings(client, approval_headers, approval_threshold='500.00')
        po = _create_po(
            client,
            approval_headers,
            approval_partner,
            approval_template,
            unit_price='0.00',
        )

        resp = client.post(f'{PO_URL}/{po["id"]}/confirm', headers=approval_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()['status'] == 'CONFIRMED'

    def test_foreign_currency_po_always_requires_approval(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
        approval_workflow: None,
    ) -> None:
        """The threshold is denominated in the org currency and there is no FX
               conversion — a PO in any other currency goes to approval even when its
        number would pass below the threshold."""
        _set_settings(client, approval_headers, approval_threshold='5000.00')
        # Net = 10.00 EUR, far below 5000.00 USD — still parked.
        po = _create_po_with_currency(
            client,
            approval_headers,
            approval_partner,
            approval_template,
            'EUR',
            unit_price='10.00',
            quantity=1,
        )

        resp = client.post(f'{PO_URL}/{po["id"]}/confirm', headers=approval_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()['status'] == 'PENDING_APPROVAL'

    def test_approve_flow_confirm_and_receipt(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
        approval_workflow: None,
        approval_location: Any,
        db_session: Session,
    ) -> None:
        _set_settings(client, approval_headers, approval_required=True)
        po = _create_po(client, approval_headers, approval_partner, approval_template)

        confirm = client.post(f'{PO_URL}/{po["id"]}/confirm', headers=approval_headers)
        assert confirm.json()['status'] == 'PENDING_APPROVAL'

        approval = client.get(f'{PO_URL}/{po["id"]}/approval', headers=approval_headers)
        assert approval.status_code == 200
        assert approval.json() is not None

        approve = client.post(f'{PO_URL}/{po["id"]}/approve', headers=approval_headers)
        assert approve.status_code == 200, approve.text
        assert approve.json()['status'] == 'APPROVED'

        confirmed = client.get(f'{PO_URL}/{po["id"]}', headers=approval_headers)
        assert confirmed.json()['status'] == 'CONFIRMED'

        # Receipt creation is unblocked on CONFIRMED.
        lines = confirmed.json()['lines']
        receipt = client.post(
            f'{PO_URL}/{po["id"]}/create-receipt',
            headers=approval_headers,
            json={
                'target_location_id': str(approval_location.id),
                'lines': [{'po_line_id': lines[0]['id'], 'quantity': 2}],
            },
        )
        assert receipt.status_code == 201, receipt.text

    def test_approve_flow_refuses_a_po_without_a_supplier(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_template: Any,
        approval_workflow: None,
    ) -> None:
        """No road reaches Confirmed past the supplier control.

        Confirm refuses a PO whose supplier is missing; the approval road
        used to carry such an order from Draft through PENDING_APPROVAL
        straight into Confirmed — the one road with no way left to fill
        the supplier in.
        """
        _set_settings(client, approval_headers, approval_required=True)
        created = client.post(
            PO_URL,
            headers=approval_headers,
            json={
                'lines': [
                    {
                        'product_template_id': str(approval_template.id),
                        'quantity_ordered': 1,
                        'unit_price': '10.00',
                    }
                ]
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        po_id = created.json()['id']

        parked = client.post(
            f'{PO_URL}/{po_id}/request-approval', headers=approval_headers
        )
        assert parked.status_code == 200, parked.text

        approve = client.post(f'{PO_URL}/{po_id}/approve', headers=approval_headers)
        assert approve.status_code == status.HTTP_400_BAD_REQUEST, approve.text
        assert 'supplier' in str(approve.json()['detail']).lower()

        confirmed = client.get(f'{PO_URL}/{po_id}', headers=approval_headers)
        assert confirmed.json()['status'] != 'CONFIRMED'

    def test_reject_returns_po_to_draft(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
        approval_workflow: None,
    ) -> None:
        _set_settings(client, approval_headers, approval_required=True)
        po = _create_po(client, approval_headers, approval_partner, approval_template)
        client.post(f'{PO_URL}/{po["id"]}/confirm', headers=approval_headers)

        reject = client.post(
            f'{PO_URL}/{po["id"]}/reject',
            headers=approval_headers,
            json={'notes': 'price too high'},
        )
        assert reject.status_code == 200, reject.text
        assert reject.json()['status'] == 'REJECTED'

        fetched = client.get(f'{PO_URL}/{po["id"]}', headers=approval_headers)
        assert fetched.json()['status'] == 'DRAFT'

        # Re-submission works after reject (rework loop).
        re_confirm = client.post(
            f'{PO_URL}/{po["id"]}/confirm', headers=approval_headers
        )
        assert re_confirm.status_code == 200
        assert re_confirm.json()['status'] == 'PENDING_APPROVAL'

    def test_cancel_cascades_to_approval_request(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
        approval_workflow: None,
    ) -> None:
        _set_settings(client, approval_headers, approval_required=True)
        po = _create_po(client, approval_headers, approval_partner, approval_template)
        client.post(f'{PO_URL}/{po["id"]}/confirm', headers=approval_headers)

        cancel = client.post(f'{PO_URL}/{po["id"]}/cancel', headers=approval_headers)
        assert cancel.status_code == 200, cancel.text
        assert cancel.json()['status'] == 'CANCELLED'

        approval = client.get(f'{PO_URL}/{po["id"]}/approval', headers=approval_headers)
        assert approval.status_code == 200
        assert approval.json()['status'] == 'CANCELLED'

    def test_withdrawn_request_leaves_the_po_a_way_out(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
        approval_workflow: None,
    ) -> None:
        """A withdrawn request used to strand the PO.

        Every offered action answered 409: approve and reject found no active
        request, and request-approval insisted on DRAFT. The PO stays in
        PENDING_APPROVAL by design, so asking again has to be allowed.
        """
        po = _create_po(client, approval_headers, approval_partner, approval_template)
        request = client.post(
            f'{PO_URL}/{po["id"]}/request-approval', headers=approval_headers
        )
        assert request.status_code == 200, request.text

        withdrawn = client.post(
            f'/api/v1/approvals/requests/{request.json()["id"]}/cancel',
            headers=approval_headers,
        )
        assert withdrawn.status_code == 200, withdrawn.text

        # The PO is still parked, and now has nothing pending on it.
        assert (
            client.get(f'{PO_URL}/{po["id"]}', headers=approval_headers).json()[
                'status'
            ]
            == 'PENDING_APPROVAL'
        )

        again = client.post(
            f'{PO_URL}/{po["id"]}/request-approval', headers=approval_headers
        )
        assert again.status_code == 200, again.text
        assert again.json()['status'] in ('PENDING', 'IN_PROGRESS')

    def test_request_approval_twice_is_refused(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
        approval_workflow: None,
    ) -> None:
        """Re-asking is for a PO with nothing pending, not for queue-jumping."""
        po = _create_po(client, approval_headers, approval_partner, approval_template)
        client.post(f'{PO_URL}/{po["id"]}/request-approval', headers=approval_headers)

        again = client.post(
            f'{PO_URL}/{po["id"]}/request-approval', headers=approval_headers
        )
        assert again.status_code == status.HTTP_409_CONFLICT, again.text

    def test_pending_approval_po_can_still_be_cancelled(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
        approval_workflow: None,
    ) -> None:
        """The other way out of PENDING_APPROVAL, which the UI never offered."""
        po = _create_po(client, approval_headers, approval_partner, approval_template)
        client.post(f'{PO_URL}/{po["id"]}/request-approval', headers=approval_headers)

        cancelled = client.post(f'{PO_URL}/{po["id"]}/cancel', headers=approval_headers)
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()['status'] == 'CANCELLED'

    def test_queue_describes_the_order_it_asks_about(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
        approval_workflow: None,
    ) -> None:
        """The approvals queue used to show eight characters of a UUID."""
        po = _create_po(
            client,
            approval_headers,
            approval_partner,
            approval_template,
            unit_price='100.00',
            quantity=3,
        )
        client.post(f'{PO_URL}/{po["id"]}/request-approval', headers=approval_headers)

        queue = client.get(
            '/api/v1/approvals/requests?target_type=purchase_order',
            headers=approval_headers,
        )
        assert queue.status_code == 200, queue.text
        rows = queue.json()['items']
        assert rows, 'the request just raised is missing from the queue'

        summary = rows[0]['target_summary']
        assert summary is not None, 'a purchase order must describe itself'
        assert summary['number'] == po['number']
        assert summary['partner_name'] == approval_partner.name
        assert Decimal(summary['total_value']) == Decimal('300.00')
        assert summary['lines_count'] == 1

    def test_the_queue_total_says_only_what_the_threshold_can_know(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
        approval_workflow: None,
    ) -> None:
        """The card and the rule that raised the request speak about one number.

        The card's ``total_value`` is documented as the figure the approval
        threshold is compared against. The threshold answers "cannot be
        known" for an order with an unpriced line; the card used to answer a
        partial sum — so an approver read "300.00" about an order the rule
        refused to call below 500, and the two answers looked like a
        disagreement rather than one fact.
        """
        resp = client.post(
            PO_URL,
            headers=approval_headers,
            json={
                'partner_id': str(approval_partner.id),
                'lines': [
                    {
                        'product_template_id': str(approval_template.id),
                        'quantity_ordered': 3,
                        'unit_price': '100.00',
                    },
                    {
                        'product_template_id': str(approval_template.id),
                        'quantity_ordered': 1,
                    },
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        po = resp.json()

        raised = client.post(
            f'{PO_URL}/{po["id"]}/request-approval', headers=approval_headers
        )
        assert raised.status_code == 200, raised.text

        queue = client.get(
            '/api/v1/approvals/requests?target_type=purchase_order',
            headers=approval_headers,
        )
        assert queue.status_code == 200, queue.text
        rows = queue.json()['items']
        assert rows, 'the request just raised is missing from the queue'

        summary = rows[0]['target_summary']
        assert summary['total_value'] is None, (
            'an order whose worth is not written down has no total — '
            f'the card said {summary["total_value"]!r}'
        )
        assert summary['lines_count'] == 2

    def test_manual_request_approval_parks_po(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
        approval_workflow: None,
    ) -> None:
        po = _create_po(client, approval_headers, approval_partner, approval_template)

        request = client.post(
            f'{PO_URL}/{po["id"]}/request-approval', headers=approval_headers
        )
        assert request.status_code == 200, request.text

        fetched = client.get(f'{PO_URL}/{po["id"]}', headers=approval_headers)
        assert fetched.json()['status'] == 'PENDING_APPROVAL'

        approve = client.post(f'{PO_URL}/{po["id"]}/approve', headers=approval_headers)
        assert approve.status_code == 200
        assert approve.json()['status'] == 'APPROVED'

        confirmed = client.get(f'{PO_URL}/{po["id"]}', headers=approval_headers)
        assert confirmed.json()['status'] == 'CONFIRMED'


@pytest.mark.integration
class TestSwitchingTheWorkflowOff:
    def test_deactivating_the_workflow_releases_a_parked_order(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
        approval_workflow: None,
    ) -> None:
        """An order waiting on a workflow that is switched off goes on, confirmed."""
        _set_settings(client, approval_headers, approval_required=True)
        po = _create_po(client, approval_headers, approval_partner, approval_template)
        parked = client.post(f'{PO_URL}/{po["id"]}/confirm', headers=approval_headers)
        assert parked.json()['status'] == 'PENDING_APPROVAL'
        workflow_id = client.get(
            '/api/v1/approvals/workflows', headers=approval_headers
        ).json()['items'][0]['id']

        waiting = client.get(
            f'/api/v1/approvals/workflows/{workflow_id}/waiting',
            headers=approval_headers,
        ).json()
        assert waiting['waiting'] == [{'target_type': 'purchase_order', 'count': 1}]
        assert waiting['settings_requiring_approval'] == ['approval_required']

        off = client.patch(
            f'/api/v1/approvals/workflows/{workflow_id}',
            headers=approval_headers,
            json={'is_active': False},
        )
        assert off.status_code == 200, off.text

        after = client.get(f'{PO_URL}/{po["id"]}', headers=approval_headers).json()
        assert after['status'] == 'CONFIRMED'
        approval = client.get(f'{PO_URL}/{po["id"]}/approval', headers=approval_headers)
        assert approval.json()['status'] == 'CANCELLED'

    def test_the_released_order_requester_is_told_the_order_goes_on(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
        approval_workflow: None,
    ) -> None:
        """The order setting still demands approval of orders — of new ones.

        A released order is already confirmed and nothing gates it again, so
        its requester is told the order goes on even while the setting that
        parked it stands.
        """
        _set_settings(client, approval_headers, approval_required=True)
        po = _create_po(client, approval_headers, approval_partner, approval_template)
        parked = client.post(f'{PO_URL}/{po["id"]}/confirm', headers=approval_headers)
        assert parked.json()['status'] == 'PENDING_APPROVAL'
        workflow_id = client.get(
            '/api/v1/approvals/workflows', headers=approval_headers
        ).json()['items'][0]['id']

        off = client.patch(
            f'/api/v1/approvals/workflows/{workflow_id}',
            headers=approval_headers,
            json={'is_active': False},
        )
        assert off.status_code == 200, off.text

        notices = client.get('/api/v1/notifications', headers=approval_headers)
        assert notices.status_code == status.HTTP_200_OK, notices.text
        rows = notices.json()['items']
        closed = [
            n
            for n in rows
            if (n.get('meta_data') or {}).get('kind') == 'approval_closed'
        ]
        assert len(closed) == 1, closed
        content = closed[0]['content']
        assert po['number'] in content
        assert 'goes on without approval' in content
        assert 'Still requiring approval' not in content

    def test_a_withdrawn_request_does_not_confirm_the_order(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
        approval_workflow: None,
    ) -> None:
        """Pulling the request back is not an approval; only a release is."""
        _set_settings(client, approval_headers, approval_required=True)
        po = _create_po(client, approval_headers, approval_partner, approval_template)
        client.post(f'{PO_URL}/{po["id"]}/confirm', headers=approval_headers)
        request = client.get(f'{PO_URL}/{po["id"]}/approval', headers=approval_headers)

        withdrawn = client.post(
            f'/api/v1/approvals/requests/{request.json()["id"]}/cancel',
            headers=approval_headers,
        )
        assert withdrawn.status_code == 200, withdrawn.text
        after = client.get(f'{PO_URL}/{po["id"]}', headers=approval_headers).json()
        assert after['status'] == 'PENDING_APPROVAL'


@pytest.mark.integration
class TestApprovalActsAreJournalledOnTheOrder:
    """The approvals module journals its own request row, which names the
    request and not the order; the order's history has to say it too."""

    def _acts(
        self, db_session: Session, org: Organization, po_id: str
    ) -> list[dict[str, Any]]:
        from uuid import UUID

        from sqlalchemy import select

        from app.models.audit_log import AuditLog

        db_session.expire_all()
        rows = db_session.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == org.id,
                AuditLog.target_type == 'purchase_order',
                AuditLog.target_id == UUID(po_id),
                AuditLog.action == 'UPDATE',
            )
            .order_by(AuditLog.created_at)
        )
        return [
            row.snapshot for row in rows if row.snapshot and 'approval' in row.snapshot
        ]

    def test_request_and_approve_each_write_an_entry(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
        approval_workflow: None,
        approval_org: Organization,
        db_session: Session,
    ) -> None:
        po = _create_po(client, approval_headers, approval_partner, approval_template)
        requested = client.post(
            f'{PO_URL}/{po["id"]}/request-approval',
            headers=approval_headers,
            json={'notes': 'please check'},
        )
        assert requested.status_code == 200, requested.text
        approved = client.post(f'{PO_URL}/{po["id"]}/approve', headers=approval_headers)
        assert approved.status_code == 200, approved.text

        request_act, approve_act = self._acts(db_session, approval_org, po['id'])
        assert request_act['approval'] == 'requested'
        assert request_act['notes'] == 'please check'
        assert request_act['before'] == {'status': 'DRAFT'}
        assert request_act['after'] == {'status': 'PENDING_APPROVAL'}
        assert approve_act['approval'] == 'approved'
        assert approve_act['before'] == {'status': 'PENDING_APPROVAL'}
        assert approve_act['after'] == {'status': 'CONFIRMED'}

    def test_a_rejection_records_the_reason_and_the_return_to_draft(
        self,
        client: TestClient,
        approval_headers: dict[str, str],
        approval_partner: Any,
        approval_template: Any,
        approval_workflow: None,
        approval_org: Organization,
        db_session: Session,
    ) -> None:
        po = _create_po(client, approval_headers, approval_partner, approval_template)
        client.post(f'{PO_URL}/{po["id"]}/request-approval', headers=approval_headers)
        rejected = client.post(
            f'{PO_URL}/{po["id"]}/reject',
            headers=approval_headers,
            json={'notes': 'too dear'},
        )
        assert rejected.status_code == 200, rejected.text

        _, reject_act = self._acts(db_session, approval_org, po['id'])
        assert reject_act['approval'] == 'rejected'
        assert reject_act['notes'] == 'too dear'
        assert reject_act['before'] == {'status': 'PENDING_APPROVAL'}
        assert reject_act['after'] == {'status': 'DRAFT'}
