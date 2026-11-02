"""Switching an approval workflow off lets what waited on it go on.

A workflow is a control someone switched on; switching it off must not leave a
document parked behind it. The deactivate and delete refusals used to tell the
admin to resolve the requests first, and a request on a stage nobody can decide
cannot be resolved by anyone — so the admin had no move left. Now the open
requests are closed as the admin, the documents leave PENDING_APPROVAL, and the
requester is told why.
"""

from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.models.item import Item
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.modules.approvals.models import ApprovalWorkflow
from app.modules.warehouse.models import DocumentStatus

PROFILE = '/api/v1/warehouse/profile'


def _park_a_document(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    location: StorageLocation,
    item: Item,
    *,
    threshold: str | None = '100.00',
) -> str:
    """A confirmed document parked in PENDING_APPROVAL.

    ``threshold`` sets the profile's approval threshold first, so the
    profile itself is what parks the document; without it the profile
    names nothing and the active workflow alone holds it.
    """
    if threshold is not None:
        profile = client.get(PROFILE, headers=headers).json()
        kept = {
            k: v
            for k, v in profile.items()
            if k not in ('id', 'organization_id', 'created_at', 'updated_at')
        }
        put = client.put(
            PROFILE,
            headers=headers,
            json={
                **kept,
                'approval_threshold': threshold,
                'value_tracking_enabled': True,
            },
        )
        assert put.status_code == status.HTTP_200_OK, put.text
    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(location.id),
            'lines': [
                {'item_id': str(item.id), 'expected_quantity': 5, 'unit_price': '50.00'}
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = cast(str, created.json()['id'])
    confirmed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirmed.json()['status'] == DocumentStatus.PENDING_APPROVAL.value
    return doc_id


def _clear_the_threshold(client: TestClient, headers: dict[str, str]) -> None:
    profile = client.get(PROFILE, headers=headers).json()
    kept = {
        k: v
        for k, v in profile.items()
        if k not in ('id', 'organization_id', 'created_at', 'updated_at')
    }
    put = client.put(
        PROFILE, headers=headers, json={**kept, 'approval_threshold': None}
    )
    assert put.status_code == status.HTTP_200_OK, put.text


def _document(client: TestClient, headers: dict[str, str], doc_id: str) -> Any:
    return client.get(f'/api/v1/warehouse/documents/{doc_id}', headers=headers).json()


def _closed_notice(client: TestClient, headers: dict[str, str]) -> Any:
    """The one closure notice the requester of a released request got."""
    notices = client.get('/api/v1/notifications', headers=headers)
    assert notices.status_code == status.HTTP_200_OK, notices.text
    rows = notices.json()['items']
    closed = [
        n for n in rows if (n.get('meta_data') or {}).get('kind') == 'approval_closed'
    ]
    assert len(closed) == 1, closed
    return closed[0]


@pytest.mark.integration
class TestSwitchingAWorkflowOff:
    def test_deactivating_releases_the_waiting_document(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        doc_id = _park_a_document(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )
        request = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval', headers=doc_auth_headers
        ).json()

        resp = client.patch(
            f'/api/v1/approvals/workflows/{doc_approval_workflow.id}',
            headers=doc_auth_headers,
            json={'is_active': False},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['is_active'] is False

        closed = client.get(
            f'/api/v1/approvals/requests/{request["id"]}', headers=doc_auth_headers
        ).json()
        assert closed['status'] == 'CANCELLED'
        assert closed['cancelled_by'] is not None
        assert closed['meta_data']['closed_reason'] == 'workflow deactivated'
        assert _document(client, doc_auth_headers, doc_id)['status'] == (
            DocumentStatus.CONFIRMED.value
        )

        # Nothing asks for an approval any more once the setting that did is cleared.
        _clear_the_threshold(client, doc_auth_headers)
        completed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert completed.status_code == status.HTTP_200_OK, completed.text

    def test_deleting_releases_and_archives_with_the_history_kept(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        doc_id = _park_a_document(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )
        request = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval', headers=doc_auth_headers
        ).json()

        resp = client.delete(
            f'/api/v1/approvals/workflows/{doc_approval_workflow.id}',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json() == {'archived': True, 'requests_kept': 1}

        closed = client.get(
            f'/api/v1/approvals/requests/{request["id"]}', headers=doc_auth_headers
        ).json()
        assert closed['status'] == 'CANCELLED'
        assert closed['meta_data']['closed_reason'] == 'workflow deleted'
        assert _document(client, doc_auth_headers, doc_id)['status'] == (
            DocumentStatus.CONFIRMED.value
        )

    def test_the_dialog_is_told_how_many_wait_and_what_still_demands_approval(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        url = f'/api/v1/approvals/workflows/{doc_approval_workflow.id}/waiting'
        empty = client.get(url, headers=doc_auth_headers).json()
        assert empty['total'] == 0
        assert empty['settings_requiring_approval'] == []

        _park_a_document(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )
        waiting = client.get(url, headers=doc_auth_headers).json()
        assert waiting['total'] == 1
        assert waiting['waiting'] == [{'target_type': 'document', 'count': 1}]
        assert waiting['settings_requiring_approval'] == ['approval_threshold']

    def test_the_requester_is_told_why_the_request_closed(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        doc_id = _park_a_document(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )
        client.patch(
            f'/api/v1/approvals/workflows/{doc_approval_workflow.id}',
            headers=doc_auth_headers,
            json={'is_active': False},
        )
        closed = _closed_notice(client, doc_auth_headers)
        assert closed['meta_data']['reason'] == 'workflow deactivated'
        number = _document(client, doc_auth_headers, doc_id)['number']
        assert number in closed['content']

    def test_the_requester_is_told_the_document_still_requires_approval(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Closing the request is not permission to execute the document.

        The threshold that parked the document still stands after the
        workflow is switched off, so completion is refused until it is
        cleared — the notice must not tell the requester the item goes on.
        """
        doc_id = _park_a_document(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_item
        )
        off = client.patch(
            f'/api/v1/approvals/workflows/{doc_approval_workflow.id}',
            headers=doc_auth_headers,
            json={'is_active': False},
        )
        assert off.status_code == status.HTTP_200_OK, off.text

        closed = _closed_notice(client, doc_auth_headers)
        content = closed['content']
        number = _document(client, doc_auth_headers, doc_id)['number']
        assert number in content
        assert 'the approval threshold' in content
        assert 'goes on without approval' not in content

        # What the notice warns about is real: completion is refused, by the
        # approvals module's pre-post check.
        refused = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert refused.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT, (
            refused.text
        )
        assert refused.json()['detail']['code'] == 'APPROVAL_REQUIRED'

    def test_the_requester_is_told_the_item_goes_on_when_nothing_demands_approval(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """With the profile naming nothing the workflow alone held the
        document, so once it is off nothing stands in the way and the
        notice keeps its promise that the item goes on."""
        doc_id = _park_a_document(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_item,
            threshold=None,
        )
        off = client.patch(
            f'/api/v1/approvals/workflows/{doc_approval_workflow.id}',
            headers=doc_auth_headers,
            json={'is_active': False},
        )
        assert off.status_code == status.HTTP_200_OK, off.text

        closed = _closed_notice(client, doc_auth_headers)
        content = closed['content']
        number = _document(client, doc_auth_headers, doc_id)['number']
        assert number in content
        assert 'goes on without approval' in content

        completed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert completed.status_code == status.HTTP_200_OK, completed.text
