"""An approval from three months ago does not clear a rejection from today.

The guard asked one question first -- "is there an approved request for this
target" -- and returned the moment it found one, before it ever looked at
PENDING, IN_PROGRESS or REJECTED. Approval rows are an audit trail, so the
old one stays in the table forever: once a target had been approved, every
later submission was decorative. Resubmit, get rejected, and the target went
through anyway.

The rule written down here is that **the newest request that says something
decides**. A withdrawn request says nothing, so cancelling a resubmission
falls back to the decision before it; that is the only case where "newest"
needs qualifying, and leaving it unqualified would let a withdrawal block a
target its owner had already approved.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import error_message_pattern
from app.models.organization import Organization
from app.models.user import User
from app.modules.approvals.exceptions import ApprovalRequiredError
from app.modules.approvals.models import ApprovalRequest
from app.modules.approvals.services import (
    approve_stage,
    cancel_request,
    check_and_block,
    create_workflow,
    reject_request,
    request_approval,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def guarded_target(
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


async def _submit(
    db: AsyncSession, org: Organization, requester: User, target_id: uuid.UUID
) -> ApprovalRequest:
    request = await request_approval(db, org.id, 'document', target_id, requester.id)
    # Each submission is a request of its own and commits; inside one
    # transaction ``now()`` stands still, and "newest" would be a tie.
    await db.commit()
    return request


class TestAnApprovalDoesNotOutliveALaterDecision:
    async def test_a_rejection_after_an_approval_blocks(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        async_approver: User,
        guarded_target: uuid.UUID,
    ) -> None:
        db, org = real_async_db_session, async_approval_org

        first = await _submit(db, org, async_requester, guarded_target)
        await approve_stage(db, org.id, first.id, async_approver.id)
        second = await _submit(db, org, async_requester, guarded_target)
        await reject_request(db, org.id, second.id, async_approver.id)

        with pytest.raises(
            ApprovalRequiredError,
            match=error_message_pattern('approval_required_after_rejection'),
        ):
            await check_and_block(db, org.id, 'document', guarded_target)

    async def test_a_resubmission_still_waiting_blocks(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        async_approver: User,
        guarded_target: uuid.UUID,
    ) -> None:
        db, org = real_async_db_session, async_approval_org

        first = await _submit(db, org, async_requester, guarded_target)
        await approve_stage(db, org.id, first.id, async_approver.id)
        await _submit(db, org, async_requester, guarded_target)

        with pytest.raises(ApprovalRequiredError):
            await check_and_block(db, org.id, 'document', guarded_target)


class TestTheNewestDecisionCutsBothWays:
    async def test_an_approval_after_a_rejection_lets_it_through(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        async_approver: User,
        guarded_target: uuid.UUID,
    ) -> None:
        db, org = real_async_db_session, async_approval_org

        first = await _submit(db, org, async_requester, guarded_target)
        await reject_request(db, org.id, first.id, async_approver.id)
        second = await _submit(db, org, async_requester, guarded_target)
        await approve_stage(db, org.id, second.id, async_approver.id)

        await check_and_block(db, org.id, 'document', guarded_target)

    async def test_a_lone_approval_still_lets_it_through(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        async_approver: User,
        guarded_target: uuid.UUID,
    ) -> None:
        """The control: the ordinary case must stay ordinary."""
        db, org = real_async_db_session, async_approval_org

        first = await _submit(db, org, async_requester, guarded_target)
        await approve_stage(db, org.id, first.id, async_approver.id)

        await check_and_block(db, org.id, 'document', guarded_target)


class TestAWithdrawnRequestSaysNothing:
    async def test_cancelling_a_resubmission_falls_back_to_the_approval(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        async_approver: User,
        guarded_target: uuid.UUID,
    ) -> None:
        db, org = real_async_db_session, async_approval_org

        first = await _submit(db, org, async_requester, guarded_target)
        await approve_stage(db, org.id, first.id, async_approver.id)
        second = await _submit(db, org, async_requester, guarded_target)
        await cancel_request(db, org.id, second.id, async_requester.id)

        await check_and_block(db, org.id, 'document', guarded_target)


class TestNothingHasBeenAskedAtAll:
    async def test_the_target_is_blocked(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        guarded_target: uuid.UUID,
    ) -> None:
        with pytest.raises(
            ApprovalRequiredError,
            match=error_message_pattern('approval_required_first'),
        ):
            await check_and_block(
                real_async_db_session,
                async_approval_org.id,
                'document',
                guarded_target,
            )
