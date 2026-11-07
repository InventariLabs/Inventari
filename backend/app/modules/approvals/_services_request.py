from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction
from app.core.db_utils import acquire_advisory_lock, after_commit

from ._audit import log_request_async
from ._services_notify import _notify_pending_stage_approvers_async
from ._services_skip import _auto_advance_self_only_stages
from ._services_workflow import get_active_workflow
from .exceptions import ApprovalError
from .models import OPEN_STATUSES, ApprovalDecision, ApprovalRequest
from .target_summaries import get_target_summary_provider


async def require_target_exists(
    db: AsyncSession, org_id: UUID, target_type: str, target_id: UUID
) -> None:
    """Refuse a request about something its own module cannot describe.

    A request for an id that names no record is stored and then listed by no
    queue, because every queue reaches a request through its target: nobody
    sees it, nobody can decide it. The module that owns the target type
    already describes its targets for the queue (``target_summaries``), so the
    same provider answers whether the target is there. A type nobody claimed
    cannot be checked and is let through, as the queue lets it through.
    """
    provider = get_target_summary_provider(target_type)
    if provider is None:
        return
    if target_id not in await provider(db, org_id, [target_id]):
        raise ApprovalError.translated('approval_target_not_found')


async def request_approval(
    db: AsyncSession,
    org_id: UUID,
    target_type: str,
    target_id: UUID,
    created_by: UUID,
    meta_data: dict[str, Any] | None = None,
) -> ApprovalRequest:
    """Open an approval request for a target.

    The request is written, or rolled back, together with the rest of the
    caller's work (the one-step document post confirms and asks in one
    transaction). The approvers are told only once that transaction has
    committed: the mail and the push leave the database, and a refused post
    must not announce a request it never raised.
    """
    # Advisory lock to prevent TOCTOU race on concurrent approval requests
    await acquire_advisory_lock(db, f'approval:{org_id}:{target_type}:{target_id}')

    # Check for existing pending request for the same target
    existing = await db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.organization_id == org_id,
            ApprovalRequest.target_type == target_type,
            ApprovalRequest.target_id == target_id,
            ApprovalRequest.status.in_(OPEN_STATUSES),
        )
    )
    if existing is not None:
        raise ApprovalError.translated('approval_request_already_open')

    # Choose stages only after any edit or replacement has finished. The
    # same key protects both workflow save paths and archival.
    await acquire_advisory_lock(db, f'approval_workflow:{org_id}:{target_type}')
    workflow = await get_active_workflow(db, org_id, target_type)
    if workflow is None:
        raise ApprovalError.translated('approval_no_active_workflow')

    stages = workflow.stages or []
    if not stages:
        raise ApprovalError.translated('approval_workflow_no_stages')

    sorted_stages = sorted(stages, key=lambda s: s.get('order', 0))
    total_stages = len(sorted_stages)

    request = ApprovalRequest(
        organization_id=org_id,
        workflow_id=workflow.id,
        target_type=target_type,
        target_id=target_id,
        status='PENDING',
        current_stage=1,
        total_stages=total_stages,
        created_by=created_by,
        meta_data=meta_data,
    )
    db.add(request)
    await db.flush()

    first_stage = sorted_stages[0]
    decision = ApprovalDecision(
        approval_request_id=request.id,
        stage_order=first_stage['order'],
        status='PENDING',
    )
    db.add(decision)
    await db.flush()
    # Before the auto-skip, so the journal reads in the order things
    # happened: somebody asked, then the machine walked past the stages
    # only they could have decided. Without this row the log showed an
    # answer with no question, and a request nobody has answered yet --
    # the reason a document will not move -- showed nothing at all.
    await log_request_async(
        db,
        request,
        user_id=created_by,
        action=AuditAction.CREATE,
        snapshot={
            'stage_order': request.current_stage,
            'total_stages': total_stages,
            'new_status': request.status,
        },
    )
    # Auto-skip any leading stages where the requester is the sole approver.
    await _auto_advance_self_only_stages(db, request, sorted_stages, org_id)
    await db.flush()

    await db.refresh(request, ['decisions'])

    # The caller's commit is still ahead; the notice to the approvers of the
    # (possibly auto-advanced) pending stage waits for it, and like every
    # after-commit notice it never breaks the request.
    after_commit(
        db,
        lambda: _notify_pending_stage_approvers_async(
            db, request, sorted_stages, org_id
        ),
    )
    return request
