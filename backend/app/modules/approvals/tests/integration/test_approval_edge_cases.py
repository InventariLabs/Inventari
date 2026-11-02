"""Edge-case tests for the approvals service layer.

Targets the service helpers in ``_services_workflow`` and
``_services_request`` that are not exercised by the happy-path tests in
``test_approval_workflow.py``:

- request_approval without an active workflow
- request_approval with a workflow that has zero stages
- stages with auto-assigned order
- stages with restricted ``approver_user_ids`` (approve + reject)
- update_workflow with is_active=False and active requests
- delete_workflow with active requests (regression)
- approve/reject with no notes
- approve/reject on a multi-stage workflow where only one stage restricts
  the approver pool
"""

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import error_message_pattern
from app.models.organization import Organization
from app.models.user import User
from app.modules.approvals.exceptions import ApprovalError
from app.modules.approvals.services import (
    approve_stage,
    create_workflow,
    delete_workflow,
    reject_request,
    request_approval,
    update_workflow,
)


@pytest.mark.integration
class TestRequestApprovalEdgeCases:
    async def test_raises_when_no_active_workflow(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
    ) -> None:
        with pytest.raises(ApprovalError, match='No active approval workflow'):
            await request_approval(
                real_async_db_session,
                async_approval_org.id,
                'document',
                uuid.uuid4(),
                async_requester.id,
            )

    async def test_raises_when_workflow_has_no_stages(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
    ) -> None:
        # Bypass the create_workflow "no stages" guard by writing a workflow
        # row directly with an empty stages list. This emulates a corrupted or
        # pre-fix migration scenario.
        from app.modules.approvals.models import ApprovalWorkflow

        wf = ApprovalWorkflow(
            organization_id=async_approval_org.id,
            target_type='document',
            name='No Stages',
            stages=[],
            is_active=True,
        )
        real_async_db_session.add(wf)
        await real_async_db_session.flush()
        await real_async_db_session.refresh(wf)

        with pytest.raises(ApprovalError, match='no stages configured'):
            await request_approval(
                real_async_db_session,
                async_approval_org.id,
                'document',
                uuid.uuid4(),
                async_requester.id,
            )


@pytest.mark.integration
class TestStageOrderAutoAssignment:
    async def test_orders_are_auto_assigned_when_missing(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
    ) -> None:
        stages = [
            {'role': 'manager', 'label': 'First', 'approver_user_ids': []},
            {'role': 'admin', 'label': 'Second', 'approver_user_ids': []},
        ]
        wf = await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            'document',
            'Auto Order',
            stages,
            is_active=True,
        )
        assert wf.stages[0]['order'] == 1
        assert wf.stages[1]['order'] == 2

    async def test_existing_orders_are_preserved(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
    ) -> None:
        stages = [
            {'order': 5, 'role': 'a', 'label': 'A', 'approver_user_ids': []},
            {'order': 9, 'role': 'b', 'label': 'B', 'approver_user_ids': []},
        ]
        wf = await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            'document',
            'Custom Order',
            stages,
            is_active=True,
        )
        assert wf.stages[0]['order'] == 5
        assert wf.stages[1]['order'] == 9

    async def test_mixed_orders_auto_fill_blanks(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
    ) -> None:
        stages: list[dict[str, object]] = [
            {'order': 3, 'role': 'a', 'label': 'A', 'approver_user_ids': []},
            {'role': 'b', 'label': 'B', 'approver_user_ids': []},
            {'order': 7, 'role': 'c', 'label': 'C', 'approver_user_ids': []},
        ]
        wf = await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            'document',
            'Mixed Order',
            stages,
            is_active=True,
        )
        # Position-based: index 0 keeps 3, index 1 gets 2, index 2 keeps 7.
        # The current implementation overrides only when 'order' is None,
        # so positions 0 and 2 keep their explicit values.
        assert wf.stages[0]['order'] == 3
        assert wf.stages[1]['order'] == 2
        assert wf.stages[2]['order'] == 7


@pytest.mark.integration
class TestRestrictedApprovers:
    async def test_approve_rejects_unauthorized_approver(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        async_make_user: Any,
    ) -> None:
        allowed = await async_make_user(email='allowed@example.com', role='admin')
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            'document',
            'Restricted',
            [
                {
                    'order': 1,
                    'role': 'admin',
                    'label': 'Admin',
                    'approver_user_ids': [str(allowed.id)],
                }
            ],
            is_active=True,
        )
        req = await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            uuid.uuid4(),
            async_requester.id,
        )
        # The requester cannot be the approver (self-approval guard), so we
        # use a freshly generated UUID that is neither the requester nor the
        # allowed approver.
        with pytest.raises(
            ApprovalError, match=error_message_pattern('approval_not_stage_approver')
        ):
            await approve_stage(
                real_async_db_session, async_approval_org.id, req.id, uuid.uuid4()
            )

    async def test_approve_accepts_authorized_approver(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        async_make_user: Any,
    ) -> None:
        # Create an actual user (FK requires a real row) and put them in the
        # allowed list. The service normalises approver ids to strings before
        # comparison, so the test mirrors that.
        approver = await async_make_user(email='auth@example.com', role='admin')
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            'document',
            'Restricted',
            [
                {
                    'order': 1,
                    'role': 'admin',
                    'label': 'Admin',
                    'approver_user_ids': [str(approver.id)],
                }
            ],
            is_active=True,
        )
        req = await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            uuid.uuid4(),
            async_requester.id,
        )
        result = await approve_stage(
            real_async_db_session,
            async_approval_org.id,
            req.id,
            approver.id,
            notes='OK',
        )
        assert result.status == 'APPROVED'

    async def test_reject_rejects_unauthorized_approver(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        async_make_user: Any,
    ) -> None:
        allowed = await async_make_user(email='allowed-rej@example.com', role='admin')
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            'document',
            'Restricted',
            [
                {
                    'order': 1,
                    'role': 'admin',
                    'label': 'Admin',
                    'approver_user_ids': [str(allowed.id)],
                }
            ],
            is_active=True,
        )
        req = await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            uuid.uuid4(),
            async_requester.id,
        )
        with pytest.raises(
            ApprovalError, match=error_message_pattern('approval_not_stage_approver')
        ):
            await reject_request(
                real_async_db_session, async_approval_org.id, req.id, uuid.uuid4()
            )

    async def test_empty_approver_list_allows_anyone(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
        async_requester: User,
    ) -> None:
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            'document',
            'Open Stage',
            [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'Manager',
                    'approver_user_ids': [],
                }
            ],
            is_active=True,
        )
        req = await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            uuid.uuid4(),
            async_requester.id,
        )
        result = await approve_stage(
            real_async_db_session, async_approval_org.id, req.id, async_approver.id
        )
        assert result.status == 'APPROVED'

    async def test_only_first_stage_restricted(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
        async_approver2: User,
        async_requester: User,
    ) -> None:
        """Stage 1 has a restricted approver_user_ids list. Stage 2 is open.
        The first approver is allowed, so stage 1 passes; the second
        approver is not in stage 1's list, but they only need to approve
        stage 2 which is open.
        """
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            'document',
            'Multi Restricted',
            [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'Manager Only',
                    'approver_user_ids': [str(async_approver.id)],
                },
                {
                    'order': 2,
                    'role': 'admin',
                    'label': 'Admin',
                    'approver_user_ids': [],
                },
            ],
            is_active=True,
        )
        req = await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            uuid.uuid4(),
            async_requester.id,
        )
        # First stage: only approver (manager) is allowed.
        first = await approve_stage(
            real_async_db_session, async_approval_org.id, req.id, async_approver.id
        )
        assert first.status == 'IN_PROGRESS'
        # Second stage: open, approver2 (admin) can do it.
        second = await approve_stage(
            real_async_db_session, async_approval_org.id, req.id, async_approver2.id
        )
        assert second.status == 'APPROVED'


@pytest.mark.integration
class TestUpdateWorkflowEdgeCases:
    async def test_deactivate_with_active_requests_raises(
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
                real_async_db_session, async_approval_org.id, wf.id, is_active=False
            )

    async def test_deactivate_without_active_requests_succeeds(
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
        updated = await update_workflow(
            real_async_db_session, async_approval_org.id, wf.id, is_active=False
        )
        assert updated.is_active is False

    async def test_rename_with_active_requests_succeeds(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        # Name-only updates must NOT trigger the active-request guard.
        wf = await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            uuid.uuid4(),
            async_requester.id,
        )
        updated = await update_workflow(
            real_async_db_session, async_approval_org.id, wf.id, name='Just A Rename'
        )
        assert updated.name == 'Just A Rename'


@pytest.mark.integration
class TestDeleteWorkflowEdgeCases:
    async def test_delete_with_active_request_raises(
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

    async def test_delete_keeps_the_decisions_taken_under_the_workflow(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
        async_requester: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        """a workflow that ran is archived, and its history stays.

        Deleting used to wipe every request and decision raised under the
        workflow — who approved what, and when, gone from a settings screen.
        """
        from sqlalchemy import select

        from app.modules.approvals.models import (
            ApprovalDecision,
            ApprovalRequest,
            ApprovalWorkflow,
        )

        wf = await create_workflow(
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
        # Capture the id before deletion, since accessing ``req`` afterwards
        # raises ObjectDeletedError on a session that has flushed the delete.
        request_id = req.id
        # Approve the request so it is no longer "active", unblocking delete.
        await approve_stage(
            real_async_db_session, async_approval_org.id, request_id, async_approver.id
        )
        outcome = await delete_workflow(
            real_async_db_session, async_approval_org.id, wf.id
        )
        assert outcome == {'archived': True, 'requests_kept': 1}

        # The audit trail survives; the workflow is switched off instead.
        assert (
            await real_async_db_session.scalars(
                select(ApprovalRequest).where(ApprovalRequest.id == request_id)
            )
        ).first() is not None
        assert (
            await real_async_db_session.scalars(
                select(ApprovalDecision).where(
                    ApprovalDecision.approval_request_id == request_id
                )
            )
        ).first() is not None
        archived = (
            await real_async_db_session.scalars(
                select(ApprovalWorkflow).where(ApprovalWorkflow.id == wf.id)
            )
        ).first()
        assert archived is not None
        assert archived.is_active is False
        assert archived.archived_at is not None

    async def test_delete_removes_a_workflow_that_never_ran(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        """Nothing to preserve, so a mistyped workflow really does go away."""
        from sqlalchemy import select

        from app.modules.approvals.models import ApprovalWorkflow

        wf = await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            single_stage_workflow_payload['target_type'],
            single_stage_workflow_payload['name'],
            single_stage_workflow_payload['stages'],
            is_active=True,
        )
        outcome = await delete_workflow(
            real_async_db_session, async_approval_org.id, wf.id
        )
        assert outcome == {'archived': False, 'requests_kept': 0}
        assert (
            await real_async_db_session.scalars(
                select(ApprovalWorkflow).where(ApprovalWorkflow.id == wf.id)
            )
        ).first() is None


@pytest.mark.integration
class TestApprovalNotes:
    async def test_approve_with_no_notes(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
        async_requester: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        from sqlalchemy import select

        from app.modules.approvals.models import ApprovalDecision

        await create_workflow(
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
        result = await approve_stage(
            real_async_db_session, async_approval_org.id, req.id, async_approver.id
        )
        assert result.status == 'APPROVED'
        # Notes default to None
        dec = (
            await real_async_db_session.scalars(
                select(ApprovalDecision).where(
                    ApprovalDecision.approval_request_id == req.id
                )
            )
        ).one()
        assert dec.notes is None

    async def test_reject_with_no_notes(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
        async_requester: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        from sqlalchemy import select

        from app.modules.approvals.models import ApprovalDecision

        await create_workflow(
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
        result = await reject_request(
            real_async_db_session, async_approval_org.id, req.id, async_approver.id
        )
        assert result.status == 'REJECTED'
        dec = (
            await real_async_db_session.scalars(
                select(ApprovalDecision).where(
                    ApprovalDecision.approval_request_id == req.id
                )
            )
        ).one()
        assert dec.notes is None


# ---------------------------------------------------------------------------
# Bug-fix regression tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCreateWorkflowUpdateGuardsActiveRequests:
    """Bug fix: ``create_workflow`` previously silently overwrote an
    existing workflow's stages even when there were active requests, which
    could leave in-flight requests pointing at non-existent stage orders.
    The fix: refuse to overwrite if any active requests exist.
    """

    async def test_recreate_raises_when_active_requests_exist(
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
        # Seed an active request against the workflow's target_type.
        target_id = uuid.uuid4()
        await request_approval(
            real_async_db_session,
            async_approval_org.id,
            'document',
            target_id,
            async_requester.id,
        )
        # Re-creating with the same target_type must be refused.
        with pytest.raises(
            ApprovalError,
            match=error_message_pattern(
                'approval_workflow_modify_blocked',
                count=1,
                documents=str(target_id)[:8],
            ),
        ):
            await create_workflow(
                real_async_db_session,
                async_approval_org.id,
                'document',
                'Replacement',
                [
                    {
                        'order': 1,
                        'role': 'admin',
                        'label': 'Admin',
                        'approver_user_ids': [],
                    }
                ],
                is_active=True,
            )

    async def test_recreate_succeeds_when_no_active_requests(
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
        # No active requests, recreate must succeed and return the same id.
        second = await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            'document',
            'Updated',
            [
                {
                    'order': 1,
                    'role': 'admin',
                    'label': 'Admin',
                    'approver_user_ids': [],
                }
            ],
            is_active=True,
        )
        assert second.id == first.id
        assert second.name == 'Updated'


@pytest.mark.integration
class TestUpdateWorkflowRejectsEmptyStages:
    """Bug fix: ``update_workflow`` previously accepted ``stages=[]``,
    which would put the workflow into an unusable state.  The fix: reject
    empty stages with a clear error.
    """

    async def test_update_with_empty_stages_raises(
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
        with pytest.raises(ApprovalError, match='at least one stage'):
            await update_workflow(
                real_async_db_session, async_approval_org.id, wf.id, stages=[]
            )

    async def test_update_with_empty_stages_does_not_mutate_workflow(
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
        original_stages = list(wf.stages)
        with pytest.raises(ApprovalError):
            await update_workflow(
                real_async_db_session, async_approval_org.id, wf.id, stages=[]
            )
        # Stages on the existing workflow must be unchanged.
        await real_async_db_session.refresh(wf)
        assert wf.stages == original_stages


@pytest.mark.integration
class TestStagesListNotMutated:
    """Bug fix: the service previously mutated the caller's stages list/dict
    in place when auto-assigning ``order``.  The fix: work on a defensive
    copy so the caller's data is never modified.
    """

    async def test_create_does_not_mutate_caller_stages(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
    ) -> None:
        stages = [{'role': 'manager', 'label': 'M', 'approver_user_ids': []}]
        original = [dict(s) for s in stages]
        await create_workflow(
            real_async_db_session,
            async_approval_org.id,
            'document',
            'No Mutate',
            stages,
            is_active=True,
        )
        assert stages == original
        assert 'order' not in stages[0]

    async def test_update_does_not_mutate_caller_stages(
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
        new_stages = [{'role': 'admin', 'label': 'A', 'approver_user_ids': []}]
        original = [dict(s) for s in new_stages]
        await update_workflow(
            real_async_db_session, async_approval_org.id, wf.id, stages=new_stages
        )
        assert new_stages == original
        assert 'order' not in new_stages[0]


@pytest.mark.integration
class TestApprovalNotFoundError:
    """Bug fix: approve/reject/update/delete now raise
    ``ApprovalNotFoundError`` (a subclass of ``ApprovalError``) when the
    resource is missing for the org, so the router can return 404 instead
    of 400/409.
    """

    async def test_approve_unknown_request_raises_not_found(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
    ) -> None:
        from app.modules.approvals.exceptions import ApprovalNotFoundError

        with pytest.raises(ApprovalNotFoundError, match='not found'):
            await approve_stage(
                real_async_db_session,
                async_approval_org.id,
                uuid.uuid4(),
                async_approver.id,
            )

    async def test_reject_unknown_request_raises_not_found(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_approver: User,
    ) -> None:
        from app.modules.approvals.exceptions import ApprovalNotFoundError

        with pytest.raises(ApprovalNotFoundError, match='not found'):
            await reject_request(
                real_async_db_session,
                async_approval_org.id,
                uuid.uuid4(),
                async_approver.id,
            )

    async def test_update_unknown_workflow_raises_not_found(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
    ) -> None:
        from app.modules.approvals.exceptions import ApprovalNotFoundError

        with pytest.raises(ApprovalNotFoundError, match='[Ww]orkflow not found'):
            await update_workflow(
                real_async_db_session, async_approval_org.id, uuid.uuid4(), name='X'
            )

    async def test_delete_unknown_workflow_raises_not_found(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
    ) -> None:
        from app.modules.approvals.exceptions import ApprovalNotFoundError

        with pytest.raises(ApprovalNotFoundError, match='[Ww]orkflow not found'):
            await delete_workflow(
                real_async_db_session, async_approval_org.id, uuid.uuid4()
            )

    def test_not_found_error_is_subclass_of_approval_error(self) -> None:
        # Sanity check: callers catching ``ApprovalError`` must still
        # catch ``ApprovalNotFoundError`` to remain backward-compatible.
        from app.modules.approvals.exceptions import (
            ApprovalError,
            ApprovalNotFoundError,
        )

        assert issubclass(ApprovalNotFoundError, ApprovalError)


@pytest.mark.integration
class TestSwitchingAWorkflowOffAsAnAdmin:
    async def _wf_with_a_waiting_request(
        self,
        db: AsyncSession,
        org: Organization,
        requester: User,
        payload: dict[str, Any],
    ) -> tuple[Any, Any]:
        wf = await create_workflow(
            db,
            org.id,
            payload['target_type'],
            payload['name'],
            payload['stages'],
            is_active=True,
        )
        request = await request_approval(
            db, org.id, 'document', uuid.uuid4(), requester.id
        )
        return wf, request

    async def test_deactivating_closes_the_waiting_request_as_the_admin(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        async_approver: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        wf, request = await self._wf_with_a_waiting_request(
            real_async_db_session,
            async_approval_org,
            async_requester,
            single_stage_workflow_payload,
        )
        updated = await update_workflow(
            real_async_db_session,
            async_approval_org.id,
            wf.id,
            is_active=False,
            released_by=async_approver.id,
        )
        assert updated.is_active is False
        await real_async_db_session.refresh(request)
        assert request.status == 'CANCELLED'
        assert request.cancelled_by == async_approver.id
        assert request.meta_data['closed_reason'] == 'workflow deactivated'

    async def test_deleting_closes_the_waiting_request_and_archives(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        async_approver: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        wf, request = await self._wf_with_a_waiting_request(
            real_async_db_session,
            async_approval_org,
            async_requester,
            single_stage_workflow_payload,
        )
        outcome = await delete_workflow(
            real_async_db_session,
            async_approval_org.id,
            wf.id,
            released_by=async_approver.id,
        )
        assert outcome == {'archived': True, 'requests_kept': 1}
        await real_async_db_session.refresh(request)
        assert request.status == 'CANCELLED'
        assert request.meta_data['closed_reason'] == 'workflow deleted'

    async def test_a_change_of_stages_still_waits_for_the_requests(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_requester: User,
        async_approver: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        wf, _request = await self._wf_with_a_waiting_request(
            real_async_db_session,
            async_approval_org,
            async_requester,
            single_stage_workflow_payload,
        )
        with pytest.raises(
            ApprovalError,
            match=error_message_pattern(
                'approval_workflow_modify_blocked', count=1, documents='NAMES'
            ).replace('NAMES', '[^)]+'),
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
                released_by=async_approver.id,
            )
