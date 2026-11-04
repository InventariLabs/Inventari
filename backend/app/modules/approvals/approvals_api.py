from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from . import services
from ._services_requirement import first_stage_verdict_async
from .approvals_dtos import (
    ApprovalRequestDTO,
    ApprovalWorkflowDTO,
    FirstStageVerdictDTO,
)
from .exceptions import ApprovalError, ApprovalRequiredError
from .schemas import WorkflowScope, WorkflowScopeCondition
from .target_decisions import (
    TargetDecision,
    TargetDecisionListener,
    TargetDecisionRefusedError,
    register_target_decision_listener,
)
from .target_scopes import (
    TargetScopeProvider,
    fixed_target_scope,
    register_target_scope_provider,
)
from .target_summaries import (
    TargetSearchProvider,
    TargetSummaryProvider,
    register_target_search_provider,
    register_target_summary_provider,
)


class ApprovalsAPI:
    @staticmethod
    def register_target_summary_provider(
        target_type: str, provider: TargetSummaryProvider
    ) -> None:
        """Describe your own target type in the approvals queue.

               Called at the consuming module's import time — the module package is
               imported by the registry at startup, so ``on_startup`` (which runs per
               organisation) would miss service-side calls. The provider takes
               ``(db, org_id, target_ids)`` and returns a mapping of id to a Pydantic
               summary; ids it does not recognise are simply omitted. Without one the
        queue falls back to the bare identifier.
        """
        register_target_summary_provider(target_type, provider)

    @staticmethod
    def register_target_search_provider(
        target_type: str, provider: TargetSearchProvider
    ) -> None:
        """Let the approvals queue's search find your target by its name.

        Registered at import time, beside the summary provider. The provider
        takes ``(db, org_id, text)`` and returns the ids of your targets whose
        card would show that text (a name, a serial). Without one the search
        matches your requests by their identifier only.
        """
        register_target_search_provider(target_type, provider)

    @staticmethod
    def register_target_decision_listener(
        target_type: str, listener: TargetDecisionListener
    ) -> None:
        """Hear how the requests about your own target type ended.

        Registered at the consuming module's import time, like the summary
        provider above. The listener takes ``(db, org_id, target_id,
        outcome, requester_id)`` -- outcome being APPROVED, REJECTED or
        CANCELLED -- runs inside the deciding transaction and must not
        commit. Without one, a decision changes the request and nothing
        else, which is what left approved documents sitting in
        PENDING_APPROVAL.
        """
        register_target_decision_listener(target_type, listener)

    @staticmethod
    def register_target_scope_provider(
        target_type: str, provider: TargetScopeProvider
    ) -> None:
        """Say what a workflow for your own target type would hold.

        Registered at the consuming module's import time, like the summary
        provider above. The provider takes ``(db, org_id)`` and returns a
        :class:`WorkflowScope` worked out from your module's own settings — the
        same answer your approval gate gives — so the workflow screen can tell an
        administrator, before they switch a workflow on, what it will hold.
        Without one the screen says nothing about scope.
        """
        register_target_scope_provider(target_type, provider)

    @staticmethod
    def fixed_target_scope(scope: WorkflowScope) -> TargetScopeProvider:
        """A scope provider for a target type whose rule no setting changes."""
        return fixed_target_scope(scope)

    @staticmethod
    async def get_active_workflow(
        db: AsyncSession, org_id: UUID, target_type: str
    ) -> ApprovalWorkflowDTO | None:
        result = await services.get_active_workflow(db, org_id, target_type)
        if result is None:
            return None
        return ApprovalWorkflowDTO.model_validate(result)

    @staticmethod
    async def first_stage_verdict(
        db: AsyncSession, org_id: UUID, target_type: str, requester_id: UUID
    ) -> FirstStageVerdictDTO | None:
        """Whether a request raised now could be decided at every stage.

        For the screen that raises the request (a document about to be
        confirmed): the answer is known before the click, so the dialog can
        say it. The first stage nobody can decide is the one named. ``None`` when
        no active workflow exists for the target type.
        """
        verdict = await first_stage_verdict_async(db, org_id, target_type, requester_id)
        if verdict is None:
            return None
        return FirstStageVerdictDTO(
            solvable=verdict.solvable,
            undecidable_reason=verdict.undecidable_reason,
            stage_label=verdict.stage_label,
        )

    @staticmethod
    async def requester_exempt(
        db: AsyncSession, org_id: UUID, target_type: str, requester_id: UUID | None
    ) -> bool:
        """Whether the active workflow for this target type leaves the person out.

        Asked first by every module's own approval rule: a submission from
        somebody the workflow does not name needs no approval, whatever the
        module's settings ask of the rest. ``False`` with no active workflow,
        and for an unknown requester.
        """
        return await services.requester_exempt_async(
            db, org_id, target_type, requester_id
        )

    @staticmethod
    async def documents_needing_approval_async(
        db: AsyncSession,
        org_id: UUID,
        documents: Sequence[tuple[UUID, UUID | None]],
    ) -> set[UUID]:
        """Which documents a screen must not offer its own start for.

        ``documents`` pairs each document id with the person who submitted
        it (for a confirmed document, its confirmer). The answer is the rule
        the confirmation and the posting ask, asked about a page of documents
        at once so a list can label the row before the reader taps it.
        """
        from .document_gate import (
            documents_needing_approval_async as _documents_needing_approval,
        )

        return await _documents_needing_approval(db, org_id, documents)

    @staticmethod
    async def create_workflow(
        db: AsyncSession,
        org_id: UUID,
        target_type: str,
        name: str,
        stages: list[dict[str, Any]],
        is_active: bool = False,
        requester_scope: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> ApprovalWorkflowDTO:
        """Save a workflow — switched off unless ``is_active`` says otherwise.

        A workflow holds nothing until somebody switches it on knowing what it
        will hold; a module seeding one on enable gets one that waits for that.
        ``requester_scope`` says whose submissions it holds (``None``: everyone).
        """
        result = await services.create_workflow(
            db,
            org_id,
            target_type,
            name,
            stages,
            is_active,
            requester_scope,
            created_by=created_by,
        )
        return ApprovalWorkflowDTO.model_validate(result)

    @staticmethod
    async def update_workflow(
        db: AsyncSession,
        org_id: UUID,
        workflow_id: UUID,
        name: str | None = None,
        stages: list[dict[str, Any]] | None = None,
        is_active: bool | None = None,
        released_by: UUID | None = None,
        requester_scope: dict[str, Any] | None = None,
    ) -> ApprovalWorkflowDTO:
        result = await services.update_workflow(
            db,
            org_id,
            workflow_id,
            name,
            stages,
            is_active,
            released_by,
            requester_scope=requester_scope,
        )
        return ApprovalWorkflowDTO.model_validate(result)

    @staticmethod
    async def delete_workflow(
        db: AsyncSession,
        org_id: UUID,
        workflow_id: UUID,
        released_by: UUID | None = None,
    ) -> dict[str, Any]:
        """Delete a workflow, or archive it when decisions were taken under it.

               Returns ``{'archived': bool, 'requests_kept': int}`` — see
        ``services.delete_workflow``.
        """
        return await services.delete_workflow(db, org_id, workflow_id, released_by)

    @staticmethod
    async def request_approval(
        db: AsyncSession,
        org_id: UUID,
        target_type: str,
        target_id: UUID,
        created_by: UUID,
        meta_data: dict[str, Any] | None = None,
    ) -> ApprovalRequestDTO:
        result = await services.request_approval(
            db, org_id, target_type, target_id, created_by, meta_data
        )
        return ApprovalRequestDTO.model_validate(result)

    @staticmethod
    async def approve_stage(
        db: AsyncSession,
        org_id: UUID,
        request_id: UUID,
        approver_id: UUID,
        notes: str | None = None,
    ) -> ApprovalRequestDTO:
        result = await services.approve_stage(
            db, org_id, request_id, approver_id, notes
        )
        return ApprovalRequestDTO.model_validate(result)

    @staticmethod
    async def reject_request(
        db: AsyncSession,
        org_id: UUID,
        request_id: UUID,
        approver_id: UUID,
        notes: str | None = None,
    ) -> ApprovalRequestDTO:
        result = await services.reject_request(
            db, org_id, request_id, approver_id, notes
        )
        return ApprovalRequestDTO.model_validate(result)

    @staticmethod
    async def cancel_request(
        db: AsyncSession,
        org_id: UUID,
        request_id: UUID,
        cancelled_by: UUID,
        *,
        cascade: bool = False,
    ) -> ApprovalRequestDTO:
        """Withdraw an open request.

               Pass ``cascade=True`` when the target (document, purchase order) is
               itself being cancelled or deleted: the ownership rule belongs to the
        direct withdrawal, not to a follow-on cleanup.
        """
        result = await services.cancel_request(
            db, org_id, request_id, cancelled_by, cascade=cascade
        )
        return ApprovalRequestDTO.model_validate(result)

    @staticmethod
    async def check_and_block(
        db: AsyncSession,
        org_id: UUID,
        target_type: str,
        target_id: UUID,
        *,
        require_workflow: bool = False,
    ) -> None:
        """Refuse unless this target has the approval it needs.

        ``require_workflow`` is for a caller that has already decided the
        target is under a control: a missing workflow then means the control
        cannot be run, which is not the same as there being none to run.
        """
        await services.check_and_block(
            db, org_id, target_type, target_id, require_workflow=require_workflow
        )

    @staticmethod
    async def consume_approval(
        db: AsyncSession,
        org_id: UUID,
        target_type: str,
        target_id: UUID,
        consumed_by: UUID,
    ) -> bool:
        """Spend the target's newest unconsumed approval, so it authorises one act.

        For a target whose approval is one-shot -- an equipment checkout,
        where one grant must not open every later checkout of the asset.
        Call it after ``check_and_block`` has let the act past, inside the
        caller's transaction: it does not commit. A target whose approval is
        a state of the record need not call it, and its gate keeps treating
        an APPROVED request as live. Returns whether an approval was spent.
        """
        return await services.consume_approval(
            db, org_id, target_type, target_id, consumed_by
        )

    @staticmethod
    async def find_active_request(
        db: AsyncSession, org_id: UUID, target_type: str, target_id: UUID
    ) -> ApprovalRequestDTO | None:
        """Return the active request (PENDING/IN_PROGRESS) for a target, if any.

        Use this when you need to *query* whether a request exists, not to
        enforce approval. For enforcement, ``check_and_block`` is the
        canonical guard (it also raises if a workflow exists but no approval
        has been granted).
        """
        result = await services.find_active_request(db, org_id, target_type, target_id)
        if result is None:
            return None
        return ApprovalRequestDTO.model_validate(result)

    @staticmethod
    async def get_request(
        db: AsyncSession, org_id: UUID, request_id: UUID
    ) -> ApprovalRequestDTO | None:
        result = await services.get_request(db, org_id, request_id)
        if result is None:
            return None
        return ApprovalRequestDTO.model_validate(result)

    @staticmethod
    async def get_request_enriched(
        db: AsyncSession,
        org_id: UUID,
        request_id: UUID,
        viewer_id: UUID | None = None,
    ) -> dict[str, Any] | None:
        """Return a request with workflow stages, user names and target
        summary already resolved (JSON-compatible dict).

               Pass ``viewer_id`` to have the response carry ``viewer_can_decide``
        for that person."""
        return await services.get_request_enriched(
            db, org_id, request_id, viewer_id=viewer_id
        )

    @staticmethod
    async def list_requests(
        db: AsyncSession,
        org_id: UUID,
        target_type: str | None = None,
        status: str | None = None,
        target_id: UUID | None = None,
        pending_for_user_id: UUID | None = None,
    ) -> list[ApprovalRequestDTO]:
        results = await services.list_requests(
            db,
            org_id,
            target_type,
            status,
            target_id,
            pending_for_user_id=pending_for_user_id,
        )
        return [ApprovalRequestDTO.model_validate(r) for r in results]

    @staticmethod
    async def notify_rejection_async(
        db: AsyncSession,
        *,
        org_id: UUID,
        doc_id: UUID,
        request_id: UUID,
        requester_id: UUID,
        reason: str | None,
    ) -> None:
        """Notify the requester their request was rejected.

        Best-effort, never raises. See ``_services_notify.notify_rejection_async``.
        """
        from ._services_notify import notify_rejection_async as _impl

        await _impl(
            db,
            org_id=org_id,
            doc_id=doc_id,
            request_id=request_id,
            requester_id=requester_id,
            reason=reason,
        )


approvals_api = ApprovalsAPI()

__all__ = [
    'approvals_api',
    'ApprovalError',
    'ApprovalRequiredError',
    'TargetDecision',
    'TargetDecisionRefusedError',
    'WorkflowScope',
    'WorkflowScopeCondition',
]
