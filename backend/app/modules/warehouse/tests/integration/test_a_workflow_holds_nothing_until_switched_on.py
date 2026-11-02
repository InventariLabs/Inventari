"""A workflow holds nothing until somebody switches it on, knowing what it will hold.

A document workflow used to come into force the moment it was saved. With
the document profile naming neither a threshold nor a type list, that meant
every confirmed document from then on waited for an approval — and nothing
on the form said so. An organization that set one up to look at the feature
found, months later, its first receipt parked behind a stage nobody could
decide, with no memory of having asked for any control at all.

So a new workflow is saved switched off, and switching it on is its own act.
The list says, for every workflow, what it holds — the same answer the gate
gives a document, worked out by the module that owns the gate, so the
sentence the administrator reads before switching on cannot promise one
thing while confirmation does another.
"""

from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import DocumentStatus

WORKFLOWS = '/api/v1/approvals/workflows'


def _stage() -> dict[str, object]:
    return {
        'order': 1,
        'role': 'manager',
        'label': 'Manager Approval',
        'approver_user_ids': [],
    }


def _create_workflow(
    client: TestClient, headers: dict[str, str], **extra: object
) -> dict[str, Any]:
    """Save a document workflow; ``is_active=True`` switches it on the way a client must.

    Saved off first, then switched on under the scope the list shows for it.
    """
    switch_on = extra.pop('is_active', False)
    resp = client.post(
        WORKFLOWS,
        headers=headers,
        json={
            'target_type': 'document',
            'requester_scope': {'everyone': True},
            'name': 'Receipts sign-off',
            'stages': [_stage()],
            **extra,
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    created = cast(dict[str, Any], resp.json())
    if not switch_on:
        return created
    shown = _listed(client, headers, created['id'])['scope']
    on = client.patch(
        f'{WORKFLOWS}/{created["id"]}',
        headers=headers,
        json={'is_active': True, 'expected_scope': shown},
    )
    assert on.status_code == status.HTTP_200_OK, on.text
    return cast(dict[str, Any], on.json())


def _listed(
    client: TestClient, headers: dict[str, str], workflow_id: str
) -> dict[str, Any]:
    resp = client.get(WORKFLOWS, headers=headers)
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return next(row for row in resp.json()['items'] if row['id'] == workflow_id)


def _confirmed_receipt_status(
    client: TestClient,
    headers: dict[str, str],
    location: StorageLocation,
    partner: Partner,
    template: ProductTemplate,
    *,
    unit_price: str = '2.50',
) -> str:
    """Create a receipt of four units, confirm it, and say where it landed."""
    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(location.id),
            'lines': [
                {
                    'product_template_id': str(template.id),
                    'expected_quantity': 4,
                    'unit_price': unit_price,
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = created.json()['id']
    confirmed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    return cast(str, confirmed.json()['status'])


def _set_profile_rule(
    client: TestClient,
    headers: dict[str, str],
    *,
    threshold: str | None = None,
    types: list[str] | None = None,
) -> None:
    profile = client.get('/api/v1/warehouse/profile', headers=headers).json()
    resp = client.put(
        '/api/v1/warehouse/profile',
        headers=headers,
        json={
            **{
                k: v
                for k, v in profile.items()
                if k not in ('id', 'organization_id', 'created_at', 'updated_at')
            },
            'approval_threshold': threshold,
            'approval_required_for_types': types or [],
            'value_tracking_enabled': True,
        },
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text


@pytest.mark.integration
class TestANewWorkflowStartsSwitchedOff:
    def test_a_workflow_saved_without_saying_so_holds_nothing_until_switched_on(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        workflow = _create_workflow(client, doc_auth_headers)
        assert workflow['is_active'] is False

        # Saved, switched off: the silent profile does not turn it into
        # "every document" behind the administrator's back.
        assert (
            _confirmed_receipt_status(
                client, doc_auth_headers, doc_target_location, doc_partner, doc_template
            )
            == DocumentStatus.CONFIRMED.value
        )

        switched_on = client.patch(
            f'{WORKFLOWS}/{workflow["id"]}',
            headers=doc_auth_headers,
            json={
                'is_active': True,
                'expected_scope': _listed(client, doc_auth_headers, workflow['id'])[
                    'scope'
                ],
            },
        )
        assert switched_on.status_code == status.HTTP_200_OK, switched_on.text
        assert switched_on.json()['is_active'] is True

        assert (
            _confirmed_receipt_status(
                client, doc_auth_headers, doc_target_location, doc_partner, doc_template
            )
            == DocumentStatus.PENDING_APPROVAL.value
        )

    def test_editing_a_workflow_that_is_on_leaves_it_on(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        """Workflows already in force stay in force: only a new one starts off."""
        workflow = _create_workflow(client, doc_auth_headers, is_active=True)
        assert workflow['is_active'] is True

        edited = client.patch(
            f'{WORKFLOWS}/{workflow["id"]}',
            headers=doc_auth_headers,
            json={
                'name': 'Receipts sign-off, renamed',
                'stages': [{**_stage(), 'label': 'Warehouse lead'}],
            },
        )
        assert edited.status_code == status.HTTP_200_OK, edited.text
        assert edited.json()['is_active'] is True


@pytest.mark.integration
class TestTheListedScopeIsWhatTheGateDoes:
    """What the list says a workflow holds is what confirmation then does."""

    def test_a_silent_profile_means_every_confirmed_document(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        workflow = _create_workflow(client, doc_auth_headers, is_active=True)

        scope = _listed(client, doc_auth_headers, workflow['id'])['scope']
        assert scope['holds'] == 'all'
        assert scope['conditions'] == []
        # Nothing in the settings asks: the workflow itself is the rule.
        assert scope['required_by_settings'] == []

        assert (
            _confirmed_receipt_status(
                client, doc_auth_headers, doc_target_location, doc_partner, doc_template
            )
            == DocumentStatus.PENDING_APPROVAL.value
        )

    def test_a_threshold_holds_only_what_is_above_it(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        _set_profile_rule(client, doc_auth_headers, threshold='100')
        workflow = _create_workflow(client, doc_auth_headers, is_active=True)

        scope = _listed(client, doc_auth_headers, workflow['id'])['scope']
        assert scope['holds'] == 'some'
        [condition] = scope['conditions']
        assert condition['kind'] == 'value_above'
        assert Decimal(condition['amount']) == Decimal('100')
        assert condition['unpriced_included'] is True
        assert scope['required_by_settings'] == ['approval_threshold']

        # 4 x 2.50 = 10 is below the line; 4 x 50 = 200 is above it.
        assert (
            _confirmed_receipt_status(
                client,
                doc_auth_headers,
                doc_target_location,
                doc_partner,
                doc_template,
                unit_price='2.50',
            )
            == DocumentStatus.CONFIRMED.value
        )
        assert (
            _confirmed_receipt_status(
                client,
                doc_auth_headers,
                doc_target_location,
                doc_partner,
                doc_template,
                unit_price='50',
            )
            == DocumentStatus.PENDING_APPROVAL.value
        )

    def test_a_type_list_holds_only_those_types(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        _set_profile_rule(client, doc_auth_headers, types=['OUT'])
        workflow = _create_workflow(client, doc_auth_headers, is_active=True)

        scope = _listed(client, doc_auth_headers, workflow['id'])['scope']
        assert scope['holds'] == 'some'
        assert scope['conditions'] == [
            {
                'kind': 'document_types',
                'document_types': ['OUT'],
                'amount': None,
                'currency': None,
                'unpriced_included': False,
            }
        ]
        assert scope['required_by_settings'] == ['approval_required_for_types']

        # A receipt is not on the list, so it is confirmed without a request.
        assert (
            _confirmed_receipt_status(
                client, doc_auth_headers, doc_target_location, doc_partner, doc_template
            )
            == DocumentStatus.CONFIRMED.value
        )

    def test_the_scope_is_listed_for_a_workflow_that_is_off_too(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        """The switch-on dialog reads what the workflow *would* hold."""
        workflow = _create_workflow(client, doc_auth_headers)
        row = _listed(client, doc_auth_headers, workflow['id'])
        assert row['is_active'] is False
        assert row['scope']['holds'] == 'all'


@pytest.mark.integration
class TestSwitchingOnAgreesWithWhatWasShown:
    """Consent is to the rule the reader saw, not to whatever holds at the click.

    The switch-on dialog shows a scope read when it opened. If the document
    settings move while it is open — another tab, another administrator — a
    switch-on that ignored that would put in force a rule nobody agreed to:
    the dialog said "documents above 100", the workflow then held every
    receipt. The dialog sends the scope it showed, and the server refuses
    when the live one differs.
    """

    def test_a_switch_on_carrying_the_scope_it_showed_goes_through(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        _set_profile_rule(client, doc_auth_headers, threshold='100')
        workflow = _create_workflow(client, doc_auth_headers)
        shown = _listed(client, doc_auth_headers, workflow['id'])['scope']

        switched_on = client.patch(
            f'{WORKFLOWS}/{workflow["id"]}',
            headers=doc_auth_headers,
            json={'is_active': True, 'expected_scope': shown},
        )
        assert switched_on.status_code == status.HTTP_200_OK, switched_on.text
        assert switched_on.json()['is_active'] is True

    def test_a_switch_on_is_refused_when_the_settings_moved_since(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        _set_profile_rule(client, doc_auth_headers, threshold='100')
        workflow = _create_workflow(client, doc_auth_headers)
        shown = _listed(client, doc_auth_headers, workflow['id'])['scope']
        assert shown['holds'] == 'some'

        # Somebody clears the threshold while the dialog is open: the live
        # rule is now "every confirmed document".
        _set_profile_rule(client, doc_auth_headers)

        refused = client.patch(
            f'{WORKFLOWS}/{workflow["id"]}',
            headers=doc_auth_headers,
            json={'is_active': True, 'expected_scope': shown},
        )
        assert refused.status_code == status.HTTP_409_CONFLICT, refused.text
        assert refused.json()['detail']['code'] == 'APPROVAL_SCOPE_CHANGED'

        assert _listed(client, doc_auth_headers, workflow['id'])['is_active'] is False
        # Nothing was put in force: a cheap receipt is confirmed outright.
        assert (
            _confirmed_receipt_status(
                client, doc_auth_headers, doc_target_location, doc_partner, doc_template
            )
            == DocumentStatus.CONFIRMED.value
        )
