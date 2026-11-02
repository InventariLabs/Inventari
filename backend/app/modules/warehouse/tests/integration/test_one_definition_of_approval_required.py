"""The scanner and the panel answer the same question about the same document.

They used to answer different ones. Starting a WMS session refused whenever
the organization had an active approval workflow for documents, whatever the
profile said; completing the document asked the profile. In an organization
that had configured *who* signs off but never said *what* needs signing off,
the warehouse terminal refused every document while the panel beside it
completed those same documents — with no approval request anywhere in the
database.

Two corrections, in order. The two scanning directions were made to agree
with each other, and then all three were made to agree on the rule itself —
which the next review split again, because "a workflow alone gates" had
quietly become "a workflow overrides the profile". The rule the settings
screens promise is the one here: the profile says *what* needs signing off
(a listed type, or a value over the threshold), the workflow says *who*
approves, and the workflow stands in for the profile only while the profile
names nothing — naming the approvers without listing anything is the
statement that everything is approved. A configured threshold filters again
under an active workflow instead of showing up only as a refusal when no
workflow exists. This file asks all three about one document at a time.
"""

import uuid
from datetime import date
from typing import cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.approvals.models import ApprovalWorkflow
from app.modules.warehouse.models import DocumentStatus
from app.modules.warehouse.tests.integration._records import sow as _sow

#: What the requirement says about the stage when nobody is in its way.
_SOLVABLE: dict[str, object] = {
    'approval_solvable': True,
    'undecidable_reason': None,
    'undecidable_stage': None,
}


def _confirm(client: TestClient, headers: dict[str, str], doc_id: str) -> None:
    resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text


def _create_in(
    client: TestClient,
    headers: dict[str, str],
    target_location_id: uuid.UUID,
    partner_id: uuid.UUID,
    template_id: uuid.UUID,
    *,
    unit_price: str | None = None,
) -> str:
    line: dict[str, object] = {
        'product_template_id': str(template_id),
        'expected_quantity': 4,
    }
    if unit_price is not None:
        line['unit_price'] = unit_price
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(target_location_id),
            'lines': [line],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(str, resp.json()['id'])


def _create_out(
    client: TestClient,
    headers: dict[str, str],
    source_location_id: uuid.UUID,
    target_location_id: uuid.UUID,
    partner_id: uuid.UUID,
    template_id: uuid.UUID,
    item_id: uuid.UUID,
) -> str:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'OUT',
            'partner_id': str(partner_id),
            'source_location_id': str(source_location_id),
            'target_location_id': str(target_location_id),
            'lines': [
                {
                    'item_id': str(item_id),
                    'product_template_id': str(template_id),
                    'expected_quantity': 2,
                }
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(str, resp.json()['id'])


def _add_document_workflow(client: TestClient, headers: dict[str, str]) -> None:
    """Put an active approval workflow for documents in place, mid-test.

    An organization switching approvals on has documents in flight; creating
    the workflow after confirmation is how this file asks what happens to
    them.
    """
    resp = client.post(
        '/api/v1/approvals/workflows',
        headers=headers,
        json={
            'target_type': 'document',
            'requester_scope': {'everyone': True},
            'is_active': True,
            'expected_scope': {'holds': 'all'},
            'name': 'Workflow arrived late',
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


def _set_approval_rule(
    client: TestClient,
    headers: dict[str, str],
    *,
    threshold: str | None = None,
    types: list[str] | None = None,
) -> None:
    """Write the profile's *what*: a threshold, a type list, or neither."""
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
            # A priced document has to be a stated one; the profile refuses to
            # keep prices nobody records.
            'value_tracking_enabled': True,
        },
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text


def _require_approval_for(
    client: TestClient, headers: dict[str, str], types: list[str]
) -> None:
    _set_approval_rule(client, headers, types=types)


def _todo_next_action(
    client: TestClient, headers: dict[str, str], doc_id: str
) -> str | None:
    """What To do offers for this document's row, as the work item says."""
    resp = client.get(
        '/api/v1/warehouse/todo',
        headers=headers,
        params={'date_to': date.today().isoformat(), 'limit': 50},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    items = cast(list[dict[str, object]], resp.json()['work_items']['items'])
    row = next(item for item in items if item['key'] == f'document:{doc_id}:ship')
    return cast(str | None, row['next_action'])


@pytest.mark.integration
class TestAWorkflowAloneDemandsApproval:
    """An active workflow for documents is the rule on its own — while the profile is silent.

    The profile can say *what* needs signing off. An organization that
    configured *who* signs off and listed nothing has said "everything", and
    it used to say nothing at all: documents confirmed and executed with no
    request anywhere. The moment the profile names a threshold or a type,
    that is the filter — see ``TestAProfileThatSpeaksIsTheFilter``.
    """

    def test_receiving_start_and_the_panel_both_wait(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_approval_workflow: ApprovalWorkflow,
    ) -> None:
        doc_id = _create_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
        assert confirm.json()['status'] == DocumentStatus.PENDING_APPROVAL.value

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        assert start.status_code != status.HTTP_201_CREATED, start.text

        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code != status.HTTP_200_OK, done.text

        # The approval is the way through, and both doors open after it.
        approved = client.post(
            f'/api/v1/approvals/documents/{doc_id}/approve', headers=doc_auth_headers
        )
        assert approved.status_code == status.HTTP_200_OK, approved.text

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        assert start.status_code == status.HTTP_201_CREATED, start.text
        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{start.json()["id"]}/cancel',
            headers=doc_auth_headers,
        )
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code == status.HTTP_200_OK, done.text

    def test_picking_start_and_the_panel_both_wait(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_approval_workflow: ApprovalWorkflow,
    ) -> None:
        template_id = doc_item.template_id or doc_template.id
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '20',
        )

        doc_id = _create_out(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
        assert confirm.json()['status'] == DocumentStatus.PENDING_APPROVAL.value

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        assert start.status_code != status.HTTP_201_CREATED, start.text

        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code != status.HTTP_200_OK, done.text

        approved = client.post(
            f'/api/v1/approvals/documents/{doc_id}/approve', headers=doc_auth_headers
        )
        assert approved.status_code == status.HTTP_200_OK, approved.text

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        assert start.status_code == status.HTTP_201_CREATED, start.text
        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{start.json()["id"]}/cancel',
            headers=doc_auth_headers,
        )
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code == status.HTTP_200_OK, done.text


@pytest.mark.integration
class TestThePanelNamesTheDeadEnd:
    """A parked request nobody can decide is not "nothing waiting"."""

    def test_the_document_panel_marks_the_stage_nobody_can_decide(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """The request an administrator saved deliberately, said out loud.

        The stage names somebody who cannot see approvals, the workflow was
        saved with the consent flag — and the document's approval panel
        carries that verdict, so the request does not read as one waiting its
        turn on a screen whose whole promise is "what you can act on".
        """
        blind = h.create_user(doc_org, email='blind@example.com', role='user')
        workflow = client.post(
            '/api/v1/approvals/workflows',
            headers=doc_auth_headers,
            json={
                'target_type': 'document',
                'requester_scope': {'everyone': True},
                'is_active': True,
                'expected_scope': {'holds': 'all'},
                'name': 'Named and locked out',
                'stages': [
                    {
                        'order': 1,
                        'role': 'manager',
                        'label': 'Peer review',
                        'approver_user_ids': [str(blind.id)],
                    }
                ],
                'allow_undecidable_stages': True,
            },
        )
        assert workflow.status_code == status.HTTP_201_CREATED, workflow.text

        doc_id = _create_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        _confirm(client, doc_auth_headers, doc_id)

        approval = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval', headers=doc_auth_headers
        )
        assert approval.status_code == status.HTTP_200_OK, approval.text
        body = approval.json()
        assert body['status'] == 'PENDING'
        assert body['solvable'] is False
        assert body['undecidable_reason'] == 'named_approvers_cannot_decide'


@pytest.mark.integration
class TestTheProfileClosesBothDoorsTogether:
    """When approval really is required, neither door opens."""

    def test_a_type_the_profile_guards_stops_both(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_approval_workflow: ApprovalWorkflow,
    ) -> None:
        """Confirming such a document parks it in PENDING_APPROVAL.

        So the scanner refuses one step earlier than the gate — the document
        is not CONFIRMED — and completion refuses at the gate. Two different
        sentences, one outcome, which is what matters: nothing moves without
        the sign-off.
        """
        _require_approval_for(client, doc_auth_headers, ['IN'])
        doc_id = _create_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        _confirm(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        assert start.status_code != status.HTTP_201_CREATED, start.text

        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code != status.HTTP_200_OK, done.text

    def test_a_request_raised_by_hand_stops_both(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """The case the gate itself decides, on a document confirmed earlier.

        Somebody asked for sign-off on a document no rule demanded it for.
        Completion already honours that; the scanner has to
        honour the same thing, or the request means nothing to whoever is
        holding the terminal. The document here was confirmed before the
        workflow existed — the workflow arrived while it was already in
        flight, which is how an organization switching approvals on will
        find its documents.
        """
        doc_id = _create_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        # No workflow yet, so confirmation has nothing to park behind.
        _confirm(client, doc_auth_headers, doc_id)
        _add_document_workflow(client, doc_auth_headers)

        requested = client.post(
            f'/api/v1/approvals/documents/{doc_id}/request-approval',
            headers=doc_auth_headers,
        )
        assert requested.status_code == status.HTTP_200_OK, requested.text

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        assert start.status_code != status.HTTP_201_CREATED, start.text

        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code != status.HTTP_200_OK, done.text


@pytest.mark.integration
class TestTheDialogIsToldTheSameAnswerTheConfirmWillActOn:
    """The sentence beside the button, asked a step before the button.

    The page used to answer this itself from the workflow list and the
    profile, which was a second definition of the rule — and one that could
    name a consequence confirmation would not carry out. The endpoint asks
    the rule the confirmation asks, about the document a draft is about to
    become, and the page reads that answer.
    """

    def test_a_draft_under_an_active_workflow_is_told_it_will_wait(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_approval_workflow: ApprovalWorkflow,
    ) -> None:
        doc_id = _create_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        # Still a draft: the rule is asked about the document confirmation
        # would write, not about the one sitting on the screen.
        told = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval-requirement',
            headers=doc_auth_headers,
        )
        assert told.status_code == status.HTTP_200_OK, told.text
        assert told.json() == {
            'approval_required': True,
            'workflow_configured': True,
            **_SOLVABLE,
        }

        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
        assert confirm.json()['status'] == DocumentStatus.PENDING_APPROVAL.value

    def test_a_document_no_rule_covers_is_told_it_will_not_wait(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        told = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval-requirement',
            headers=doc_auth_headers,
        )
        assert told.status_code == status.HTTP_200_OK, told.text
        assert told.json() == {
            'approval_required': False,
            'workflow_configured': False,
            **_SOLVABLE,
        }

    def test_a_type_the_profile_lists_is_told(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """The profile half on its own, which is what a draft can meet."""
        _require_approval_for(client, doc_auth_headers, ['IN'])
        doc_id = _create_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        told = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval-requirement',
            headers=doc_auth_headers,
        )
        assert told.status_code == status.HTTP_200_OK, told.text
        assert told.json() == {
            'approval_required': True,
            'workflow_configured': False,
            **_SOLVABLE,
        }


@pytest.mark.integration
class TestAProfileThatSpeaksIsTheFilter:
    """The workflow answers *who*; the profile answers *what*.

    An active workflow used to demand approval for every confirmed document
    whatever the profile said, so a threshold of 100 and a workflow together
    parked a receipt worth 2.20 — the screen promised "documents above this
    value", and the threshold filtered anything only in a state with no
    workflow, where the document it did filter was refused instead. The type
    list read the same way: a workflow made "never approve OUT" and "always
    approve OUT" mean the same thing.
    """

    def test_a_value_under_the_threshold_confirms_with_a_workflow(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_approval_workflow: ApprovalWorkflow,
    ) -> None:
        _set_approval_rule(client, doc_auth_headers, threshold='100.00')
        doc_id = _create_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            unit_price='0.55',
        )
        # The dialog asks about the document the confirm is about to write,
        # and it gets the same answer the confirm then acts on.
        told = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval-requirement',
            headers=doc_auth_headers,
        )
        assert told.status_code == status.HTTP_200_OK, told.text
        assert told.json() == {
            'approval_required': False,
            'workflow_configured': True,
            **_SOLVABLE,
        }, told.text

        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
        assert confirm.json()['status'] == DocumentStatus.CONFIRMED.value

    def test_a_value_over_the_threshold_still_parks_with_a_workflow(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_approval_workflow: ApprovalWorkflow,
    ) -> None:
        _set_approval_rule(client, doc_auth_headers, threshold='100.00')
        doc_id = _create_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            unit_price='31.25',
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
        assert confirm.json()['status'] == DocumentStatus.PENDING_APPROVAL.value

    def test_a_type_outside_the_list_confirms_with_a_workflow(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_approval_workflow: ApprovalWorkflow,
    ) -> None:
        _set_approval_rule(client, doc_auth_headers, types=['OUT'])
        doc_id = _create_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
        assert confirm.json()['status'] == DocumentStatus.CONFIRMED.value

    def test_without_a_workflow_a_listed_type_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """The profile asks; nothing can carry it out — and it says which.

        No workflow fixture here: an approval due with no workflow is a
        configuration error, not a document that sails through.
        """
        _set_approval_rule(client, doc_auth_headers, types=['IN'])
        doc_id = _create_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_400_BAD_REQUEST, confirm.text
        assert 'workflow' in confirm.json()['detail']['message'].lower()


@pytest.mark.integration
class TestTheQueueDoesNotOfferAStartApprovalBlocks:
    """To do and the picking gate answer the same question about a document.

    A rule added after a document was confirmed reaches it: the session
    refuses to start until an approval releases it. The queue still offered
    that document as a plain Pick, so the floor learned the truth only after
    the tap — and the way out, sending it back for a signature, read as the
    action that had just failed. The row now says what it asks for.
    """

    def test_a_confirmed_dispatch_the_rule_now_covers_asks_for_approval(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        template_id = doc_item.template_id or doc_template.id
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '20',
        )
        doc_id = _create_out(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm(client, doc_auth_headers, doc_id)
        # No rule yet: the queue offers the pick it always did.
        assert _todo_next_action(client, doc_auth_headers, doc_id) == 'pick'

        _require_approval_for(client, doc_auth_headers, ['OUT'])

        # The rule reached a document confirmed before it: the row no longer
        # promises a start the session will refuse.
        assert _todo_next_action(client, doc_auth_headers, doc_id) == 'request_approval'

    def test_a_dispatch_outside_the_list_keeps_its_pick(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """The rule names receipts: the dispatch beside them is untouched."""
        template_id = doc_item.template_id or doc_template.id
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '20',
        )
        doc_id = _create_out(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm(client, doc_auth_headers, doc_id)

        _require_approval_for(client, doc_auth_headers, ['IN'])

        assert _todo_next_action(client, doc_auth_headers, doc_id) == 'pick'
