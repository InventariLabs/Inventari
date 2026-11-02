import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import error_message_pattern
from app.models.organization import Organization
from app.models.user import User
from app.modules.approvals.exceptions import ApprovalError, ApprovalRequiredError
from app.modules.approvals.models import ApprovalDecision
from app.modules.approvals.services import (
    approve_stage,
    check_and_block,
    create_workflow,
    delete_workflow,
    get_active_workflow,
    reject_request,
    request_approval,
    update_workflow,
)


@pytest.mark.integration
class TestApprovalWorkflowCrud:
    async def test_create_workflow_success(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        wf = await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        assert wf.id is not None
        assert wf.organization_id == async_approval_org.id
        assert wf.target_type == 'document'
        assert len(wf.stages) == 1
        assert wf.is_active is True

    async def test_create_workflow_without_stages_raises(
        self, real_async_db_session: AsyncSession, async_approval_org: Organization
    ) -> None:
        with pytest.raises(ApprovalError, match='at least one stage'):
            await create_workflow(
                real_async_db_session,
                async_approval_org.id,
                'document',
                'No Stages',
                [],
                is_active=True,
            )

    async def test_create_workflow_rejects_approver_from_other_org(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
    ) -> None:
        # The cross-tenant guard. A workflow must not be saved with an
        # approver_user_ids list that references a user outside the
        # caller's organization (or a non-existent user).
        foreign_id = uuid.uuid4()
        with pytest.raises(
            ApprovalError, match=error_message_pattern('approval_unknown_approvers')
        ):
            await create_workflow(
                real_async_db_session,
                async_approval_org.id,
                'document',
                'Cross Tenant',
                [
                    {
                        'order': 1,
                        'role': 'manager',
                        'label': 'Manager Approval',
                        'approver_user_ids': [str(foreign_id)],
                    }
                ],
                is_active=True,
            )

    async def test_create_workflow_accepts_own_org_member(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
    ) -> None:
        # Happy-path: the same validation must let through a real
        # member of the organisation.
        wf = await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            'document',
            'Own Member',
            [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'Manager Approval',
                    'approver_user_ids': [str(async_approver.id)],
                }
            ],
            is_active=True,
        )
        assert wf.id is not None
        assert wf.stages[0]['approver_user_ids'] == [str(async_approver.id)]

    async def test_update_workflow_rejects_approver_from_other_org(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        # The cross-tenant guard must also run on update — otherwise an
        # existing workflow could be silently pointed at a foreign user.
        wf = await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        with pytest.raises(
            ApprovalError, match=error_message_pattern('approval_unknown_approvers')
        ):
            await update_workflow(
                real_async_db_session,
                async_approval_org.id,
                wf.id,
                stages=[
                    {
                        'order': 1,
                        'role': 'manager',
                        'label': 'Manager Approval',
                        'approver_user_ids': [str(uuid.uuid4())],
                    }
                ],
            )

    async def test_create_workflow_duplicate_target_type_updates_existing(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        first = await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        second = await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            'Updated Name',
            [
                {
                    'order': 1,
                    'role': 'admin',
                    'label': 'New Stage',
                    'approver_user_ids': [],
                }
            ],
            is_active=True,
        )
        assert second.id == first.id
        assert second.name == 'Updated Name'
        assert len(second.stages) == 1
        assert second.stages[0]['label'] == 'New Stage'

    async def test_update_workflow_stages(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        wf = await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        new_stages = [
            {
                'order': 1,
                'role': 'admin',
                'label': 'Admin Only',
                'approver_user_ids': [],
            },
        ]
        updated = await update_workflow(
            real_async_db_session, async_approval_org.id, wf.id, stages=new_stages
        )
        assert len(updated.stages) == 1
        assert updated.stages[0]['role'] == 'admin'

    async def test_delete_workflow(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        wf = await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        await delete_workflow(real_async_db_session, async_approval_org.id, wf.id)
        assert (
            await get_active_workflow(
                real_async_db_session, async_approval_org.id, 'document'
            )
            is None
        )


@pytest.mark.integration
class TestApprovalRequestFlow:
    async def test_request_approval_creates_pending_decision(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        target_id = uuid.uuid4()
        req = await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            target_id,
            async_requester.id,
        )
        assert req.status == 'PENDING'
        assert req.current_stage == 1
        assert req.total_stages == 1
        assert len(req.decisions) == 1
        assert req.decisions[0].status == 'PENDING'

    async def test_request_approval_no_workflow_raises(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
    ) -> None:
        target_id = uuid.uuid4()
        with pytest.raises(ApprovalError, match='No active approval workflow'):
            await request_approval(
                real_async_db_session,
                async_approval_org.id,
                'document',
                target_id,
                async_requester.id,
            )

    async def test_approve_single_stage_completes_request(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
        async_requester: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        target_id = uuid.uuid4()
        req = await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            target_id,
            async_requester.id,
        )
        result = await approve_stage(
            real_async_db_session,
            async_approval_org.id,
            req.id,
            async_approver.id,
            'Looks good',
        )
        assert result.status == 'APPROVED'
        dec = (
            await real_async_db_session.scalars(
                select(ApprovalDecision).where(
                    ApprovalDecision.approval_request_id == req.id
                )
            )
        ).first()
        assert dec is not None
        assert dec.status == 'APPROVED'
        assert dec.approver_id == async_approver.id
        assert dec.notes == 'Looks good'

    async def test_approve_first_stage_moves_to_next(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
        async_approver2: User,
        async_requester: User,
        multi_stage_workflow_payload: dict[str, Any],
    ) -> None:
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            multi_stage_workflow_payload['target_type'],
            multi_stage_workflow_payload['name'],
            multi_stage_workflow_payload['stages'],
            is_active=True,
        )
        target_id = uuid.uuid4()
        req = await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            target_id,
            async_requester.id,
        )
        result = await approve_stage(
            real_async_db_session, async_approval_org.id, req.id, async_approver.id
        )
        assert result.status == 'IN_PROGRESS'
        assert result.current_stage == 2
        decisions = (
            await real_async_db_session.scalars(
                select(ApprovalDecision)
                .where(ApprovalDecision.approval_request_id == req.id)
                .order_by(ApprovalDecision.stage_order)
            )
        ).all()
        assert len(decisions) == 2
        assert decisions[0].status == 'APPROVED'
        assert decisions[0].stage_order == 1
        assert decisions[1].status == 'PENDING'
        assert decisions[1].stage_order == 2

    async def test_approve_last_stage_marks_approved(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
        async_approver2: User,
        async_requester: User,
        multi_stage_workflow_payload: dict[str, Any],
    ) -> None:
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            multi_stage_workflow_payload['target_type'],
            multi_stage_workflow_payload['name'],
            multi_stage_workflow_payload['stages'],
            is_active=True,
        )
        target_id = uuid.uuid4()
        req = await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            target_id,
            async_requester.id,
        )
        await approve_stage(
            real_async_db_session, async_approval_org.id, req.id, async_approver.id
        )
        result = await approve_stage(
            real_async_db_session, async_approval_org.id, req.id, async_approver2.id
        )
        assert result.status == 'APPROVED'

    async def test_reject_sets_request_rejected(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
        async_requester: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        target_id = uuid.uuid4()
        req = await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            target_id,
            async_requester.id,
        )
        result = await reject_request(
            real_async_db_session,
            async_approval_org.id,
            req.id,
            async_approver.id,
            'Not right',
        )
        assert result.status == 'REJECTED'
        dec = (
            await real_async_db_session.scalars(
                select(ApprovalDecision).where(
                    ApprovalDecision.approval_request_id == req.id
                )
            )
        ).first()
        assert dec is not None
        assert dec.status == 'REJECTED'

    async def test_cannot_approve_already_approved(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
        async_requester: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        target_id = uuid.uuid4()
        req = await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            target_id,
            async_requester.id,
        )
        await approve_stage(
            real_async_db_session, async_approval_org.id, req.id, async_approver.id
        )
        with pytest.raises(
            ApprovalError,
            match=error_message_pattern('approval_approve_invalid_status'),
        ):
            await approve_stage(
                real_async_db_session, async_approval_org.id, req.id, async_approver.id
            )

    async def test_cannot_approve_rejected(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
        async_requester: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        target_id = uuid.uuid4()
        req = await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            target_id,
            async_requester.id,
        )
        await reject_request(
            real_async_db_session, async_approval_org.id, req.id, async_approver.id
        )
        with pytest.raises(
            ApprovalError,
            match=error_message_pattern('approval_approve_invalid_status'),
        ):
            await approve_stage(
                real_async_db_session, async_approval_org.id, req.id, async_approver.id
            )


@pytest.mark.integration
class TestApprovalGuard:
    async def test_check_and_block_raises_when_pending(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        target_id = uuid.uuid4()
        await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            target_id,
            async_requester.id,
        )
        with pytest.raises(ApprovalRequiredError):
            await check_and_block(
                real_async_db_session, async_approval_org.id, 'document', target_id
            )

    async def test_check_and_block_raises_when_rejected(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
        async_requester: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        target_id = uuid.uuid4()
        req = await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            target_id,
            async_requester.id,
        )
        await reject_request(
            real_async_db_session, async_approval_org.id, req.id, async_approver.id
        )
        with pytest.raises(ApprovalRequiredError):
            await check_and_block(
                real_async_db_session, async_approval_org.id, 'document', target_id
            )

    async def test_check_and_block_passes_when_approved(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
        async_requester: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        target_id = uuid.uuid4()
        req = await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            target_id,
            async_requester.id,
        )
        await approve_stage(
            real_async_db_session, async_approval_org.id, req.id, async_approver.id
        )
        await check_and_block(
            real_async_db_session, async_approval_org.id, 'document', target_id
        )

    async def test_check_and_block_passes_when_no_request(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        target_id = uuid.uuid4()
        with pytest.raises(ApprovalRequiredError):
            await check_and_block(
                real_async_db_session, async_approval_org.id, 'document', target_id
            )

    async def test_check_and_block_noop_when_no_workflow(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
    ) -> None:
        target_id = uuid.uuid4()
        await check_and_block(
            real_async_db_session, async_approval_org.id, 'document', target_id
        )


@pytest.mark.integration
class TestSelfApprovalGuard:
    async def test_cannot_approve_own_request(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        target_id = uuid.uuid4()
        req = await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            target_id,
            async_approver.id,
        )
        with pytest.raises(ApprovalError, match='cannot approve your own request'):
            await approve_stage(
                real_async_db_session,
                async_approval_org.id,
                req.id,
                async_approver.id,
            )

    async def test_can_approve_own_request_when_the_org_allows_it(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver2: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        """self-approval is an organization setting, and only for admins."""
        from app.core.public_api import core_api
        from app.modules.approvals._settings import SELF_APPROVE_SETTING

        await core_api.settings.set_bulk_async(
            real_async_db_session,
            async_approval_org.id,
            'approvals',
            {SELF_APPROVE_SETTING: True},
        )
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        target_id = uuid.uuid4()
        req = await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            target_id,
            async_approver2.id,
        )
        result = await approve_stage(
            real_async_db_session,
            async_approval_org.id,
            req.id,
            async_approver2.id,
        )
        assert result.status == 'APPROVED'

    async def test_cannot_reject_own_request(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        target_id = uuid.uuid4()
        req = await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            target_id,
            async_approver.id,
        )
        with pytest.raises(
            ApprovalError,
            match=error_message_pattern('approval_cannot_reject_own_request'),
        ):
            await reject_request(
                real_async_db_session,
                async_approval_org.id,
                req.id,
                async_approver.id,
            )


@pytest.mark.integration
class TestWorkflowMutationGuard:
    async def test_cannot_update_workflow_with_active_requests(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        wf = await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        target_id = uuid.uuid4()
        await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            target_id,
            async_requester.id,
        )
        with pytest.raises(
            ApprovalError,
            match=error_message_pattern(
                'approval_workflow_modify_blocked',
                count=1,
                documents=str(target_id)[:8],
            ),
        ):
            await update_workflow(
                real_async_db_session,
                async_approval_org.id,
                wf.id,
                stages=[
                    {
                        'order': 1,
                        'role': 'admin',
                        'label': 'Changed',
                        'approver_user_ids': [],
                    },
                ],
            )

    async def test_cannot_delete_workflow_with_active_requests(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        wf = await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        target_id = uuid.uuid4()
        await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            target_id,
            async_requester.id,
        )
        with pytest.raises(
            ApprovalError,
            match=error_message_pattern(
                'approval_workflow_delete_blocked',
                count=1,
                documents=str(target_id)[:8],
            ),
        ):
            await delete_workflow(real_async_db_session, async_approval_org.id, wf.id)

    async def test_can_update_workflow_when_all_resolved(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
        async_requester: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        wf = await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        req = await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            uuid.uuid4(),
            async_requester.id,
        )
        await approve_stage(
            real_async_db_session, async_approval_org.id, req.id, async_approver.id
        )
        new_name = 'Updated Name'
        updated = await update_workflow(
            real_async_db_session, async_approval_org.id, wf.id, name=new_name
        )
        assert updated.name == new_name


@pytest.mark.integration
class TestMultiTenancy:
    async def test_cannot_access_other_org_workflow(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        other_org = Organization(
            name=f'Other Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core', 'approvals'],
        )
        real_async_db_session.add(other_org)
        await real_async_db_session.flush()
        await real_async_db_session.refresh(other_org)
        result = await get_active_workflow(
            real_async_db_session, other_org.id, 'document'
        )
        assert result is None

    async def test_cannot_approve_other_org_request(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
        async_requester: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        from app.modules.approvals.exceptions import ApprovalNotFoundError

        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        target_id = uuid.uuid4()
        req = await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            target_id,
            async_requester.id,
        )
        other_org = Organization(
            name=f'Other Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core', 'approvals'],
        )
        real_async_db_session.add(other_org)
        await real_async_db_session.flush()
        await real_async_db_session.refresh(other_org)
        # The request belongs to ``async_approval_org``; from ``other_org``'s
        # perspective the resource is not found.
        with pytest.raises(ApprovalNotFoundError, match='not found'):
            await approve_stage(
                real_async_db_session, other_org.id, req.id, async_approver.id
            )


@pytest.mark.integration
class TestConcurrency:
    async def test_concurrent_approve_second_gets_error(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
        async_requester: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        target_id = uuid.uuid4()
        req = await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            target_id,
            async_requester.id,
        )
        await approve_stage(
            real_async_db_session, async_approval_org.id, req.id, async_approver.id
        )
        with pytest.raises(
            ApprovalError,
            match=error_message_pattern('approval_approve_invalid_status'),
        ):
            await approve_stage(
                real_async_db_session, async_approval_org.id, req.id, async_approver.id
            )
