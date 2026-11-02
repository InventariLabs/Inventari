"""Approving and rejecting are acts, so they belong in the organization log.

They were the only acts here that were not. A stage skipped by the machine on
the requester's behalf was written down; the stage a person decided was not.
So the log showed a document going to approval and nothing after it -- and the
answer to "who released this payment, and why" lived in a table no screen
shows whole.

The approver's note is the reason. "Rejected" without "the supplier changed
the price list" is the kind of record that gets a right decision re-opened.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType
from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.models.user import User
from app.modules.approvals.services import (
    approve_stage,
    cancel_request,
    create_workflow,
    reject_request,
    request_approval,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def guarded_document(
    real_async_db_session: AsyncSession,
    async_approval_org: Organization,
    single_stage_workflow_payload: dict[str, Any],
) -> uuid.UUID:
    """A workflow over documents, and one document it guards."""
    await create_workflow(
        real_async_db_session,
        async_approval_org.id,
        single_stage_workflow_payload['target_type'],
        single_stage_workflow_payload['name'],
        single_stage_workflow_payload['stages'],
        is_active=True,
    )
    return uuid.uuid4()


async def _decisions(db: AsyncSession, org_id: uuid.UUID) -> list[AuditLog]:
    """The rows about answers, without the row about the question.

    Making the request is an act of its own and writes its own entry; these
    tests are about what happens after it.
    """
    return [e for e in await _entries(db, org_id) if e.action != AuditAction.CREATE]


async def _entries(db: AsyncSession, org_id: uuid.UUID) -> list[AuditLog]:
    rows = await db.scalars(
        select(AuditLog)
        .where(
            AuditLog.organization_id == org_id,
            AuditLog.target_type == AuditTargetType.APPROVAL_REQUEST,
        )
        .order_by(AuditLog.created_at.asc())
    )
    return list(rows.all())


class TestADecisionIsWrittenDown:
    async def test_an_approval_names_the_approver_and_the_reason(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        async_approver: User,
        guarded_document: uuid.UUID,
    ) -> None:
        db, org = real_async_db_session, async_approval_org
        request = await request_approval(
            db, org.id, 'document', guarded_document, async_requester.id
        )

        await approve_stage(
            db, org.id, request.id, async_approver.id, notes='Budget confirmed'
        )

        (entry,) = await _decisions(db, org.id)
        assert entry.user_id == async_approver.id
        assert entry.target_id == request.id
        assert entry.action == AuditAction.UPDATE
        assert entry.reason == 'Budget confirmed'
        assert entry.snapshot is not None
        assert entry.snapshot['decision'] == 'APPROVED'
        assert entry.snapshot['new_status'] == 'APPROVED'
        assert entry.snapshot['stage_order'] == 1

    async def test_the_entry_leads_with_the_decision_and_who_took_it(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        async_approver: User,
        guarded_document: uuid.UUID,
    ) -> None:
        # The journal row read "Stage order: 1 / Stages: 1", with the
        # decision behind "Show the whole change": the row shows the
        # snapshot's first fields, so the decision and its author come first.
        db, org = real_async_db_session, async_approval_org
        request = await request_approval(
            db, org.id, 'document', guarded_document, async_requester.id
        )

        await approve_stage(db, org.id, request.id, async_approver.id)

        (entry,) = await _decisions(db, org.id)
        assert entry.snapshot is not None
        assert list(entry.snapshot)[:2] == ['decision', 'decided_by']
        assert entry.snapshot['decided_by'] == (
            async_approver.full_name or async_approver.email
        )

    async def test_a_rejection_names_the_approver_and_the_reason(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        async_approver: User,
        guarded_document: uuid.UUID,
    ) -> None:
        db, org = real_async_db_session, async_approval_org
        request = await request_approval(
            db, org.id, 'document', guarded_document, async_requester.id
        )

        await reject_request(
            db, org.id, request.id, async_approver.id, notes='Price list changed'
        )

        (entry,) = await _decisions(db, org.id)
        assert entry.user_id == async_approver.id
        assert entry.reason == 'Price list changed'
        assert entry.snapshot is not None
        assert entry.snapshot['decision'] == 'REJECTED'
        assert entry.snapshot['new_status'] == 'REJECTED'

    async def test_the_entry_says_what_was_being_approved(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        async_approver: User,
        guarded_document: uuid.UUID,
    ) -> None:
        """The entry is about the request; the reader is after the document."""
        db, org = real_async_db_session, async_approval_org
        request = await request_approval(
            db, org.id, 'document', guarded_document, async_requester.id
        )

        await approve_stage(db, org.id, request.id, async_approver.id)

        (entry,) = await _decisions(db, org.id)
        assert entry.snapshot is not None
        assert entry.snapshot['approves'] == {
            'type': 'document',
            'id': str(guarded_document),
        }
        assert entry.reason is None


class TestTheLogNeverFailsTheDecision:
    async def test_a_note_longer_than_the_column_still_records(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        async_approver: User,
        guarded_document: uuid.UUID,
    ) -> None:
        """``notes`` is unbounded text, ``reason`` is 500 characters.

        A note nobody thought to keep short must not be able to roll back the
        decision it explains.
        """
        db, org = real_async_db_session, async_approval_org
        request = await request_approval(
            db, org.id, 'document', guarded_document, async_requester.id
        )

        await approve_stage(db, org.id, request.id, async_approver.id, notes='x' * 900)

        (entry,) = await _decisions(db, org.id)
        assert entry.reason is not None
        assert len(entry.reason) == 500
        assert entry.reason.endswith('…')


class TestAStageTheMachineSkipsIsStillTheMachines:
    async def test_a_self_only_stage_is_not_credited_to_the_approver(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        async_approver: User,
        multi_stage_workflow_payload: dict[str, Any],
    ) -> None:
        """Two entries, and only the first one has a person behind it."""
        db, org = real_async_db_session, async_approval_org
        stages = [
            dict(multi_stage_workflow_payload['stages'][0]),
            {
                **multi_stage_workflow_payload['stages'][1],
                'approver_user_ids': [str(async_requester.id)],
            },
        ]
        await create_workflow(
            db, org.id, 'document', 'Two Stage', stages, is_active=True
        )
        target = uuid.uuid4()
        request = await request_approval(
            db, org.id, 'document', target, async_requester.id
        )

        await approve_stage(
            db, org.id, request.id, async_approver.id, notes='Stage one'
        )

        decided, skipped = await _decisions(db, org.id)
        assert decided.user_id == async_approver.id
        assert decided.reason == 'Stage one'
        assert decided.snapshot is not None
        assert decided.snapshot['decision'] == 'APPROVED'
        assert skipped.user_id == async_requester.id
        assert skipped.snapshot is not None
        assert skipped.snapshot['auto_skipped'] is True


class TestTheQuestionIsWrittenDownToo:
    async def test_asking_leaves_an_entry_naming_who_and_what_for(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        guarded_document: uuid.UUID,
    ) -> None:
        """An answer with no question above it is half a record.

        A request nobody has decided yet is the sharper case: it is the
        reason a document will not move, and the log said nothing at all.
        """
        db, org = real_async_db_session, async_approval_org

        request = await request_approval(
            db, org.id, 'document', guarded_document, async_requester.id
        )

        (entry,) = await _entries(db, org.id)
        assert entry.action == AuditAction.CREATE
        assert entry.user_id == async_requester.id
        assert entry.target_id == request.id
        assert entry.snapshot is not None
        assert entry.snapshot['new_status'] == 'PENDING'
        assert entry.snapshot['approves'] == {
            'type': 'document',
            'id': str(guarded_document),
        }

    async def test_the_question_and_the_answer_read_as_a_pair(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        async_approver: User,
        guarded_document: uuid.UUID,
    ) -> None:
        db, org = real_async_db_session, async_approval_org
        request = await request_approval(
            db, org.id, 'document', guarded_document, async_requester.id
        )

        await approve_stage(
            db, org.id, request.id, async_approver.id, notes='Budget confirmed'
        )

        asked, answered = await _entries(db, org.id)
        assert asked.target_id == answered.target_id
        assert asked.user_id == async_requester.id
        assert answered.user_id == async_approver.id
        assert asked.snapshot is not None and answered.snapshot is not None
        assert asked.snapshot['approves'] == answered.snapshot['approves']

    async def test_withdrawing_says_the_question_was_taken_back(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        guarded_document: uuid.UUID,
    ) -> None:
        db, org = real_async_db_session, async_approval_org
        request = await request_approval(
            db, org.id, 'document', guarded_document, async_requester.id
        )

        await cancel_request(db, org.id, request.id, async_requester.id)

        _asked, withdrawn = await _entries(db, org.id)
        assert withdrawn.user_id == async_requester.id
        assert withdrawn.snapshot is not None
        assert withdrawn.snapshot['decision'] == 'CANCELLED'
        assert withdrawn.snapshot['old_status'] == 'PENDING'
        # Somebody withdrew it, so nothing marks it as a follow-on cleanup.
        assert withdrawn.meta_data is None

    async def test_a_cascade_says_it_was_the_target_going_away(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        async_approver: User,
        guarded_document: uuid.UUID,
    ) -> None:
        """The module that owns the target records its own cancellation.

        Neither that entry nor the request's own status says what became of
        the question standing in front of it, so this one is written as well
        -- flagged, so a reader can tell it from somebody changing their mind.
        """
        db, org = real_async_db_session, async_approval_org
        request = await request_approval(
            db, org.id, 'document', guarded_document, async_requester.id
        )

        await cancel_request(db, org.id, request.id, async_approver.id, cascade=True)

        _asked, withdrawn = await _entries(db, org.id)
        assert withdrawn.user_id == async_approver.id
        assert (withdrawn.meta_data or {})['cascade'] is True
