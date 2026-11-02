from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction
from app.core.logging import get_logger
from app.core.public_api import core_api

from ._audit import as_reason, log_request_async, people_names_async
from ._services_notify import clear_settled_notices
from ._services_skip import _auto_advance_self_only_stages
from ._services_workflow import get_workflow_by_id
from ._settings import SELF_APPROVE_SETTING
from .exceptions import ApprovalError, ApprovalNotFoundError
from .models import OPEN_STATUSES, ApprovalDecision, ApprovalRequest
from .target_decisions import TargetDecision, notify_target_decided

logger = get_logger(__name__)


async def _log_decision(
    db: AsyncSession,
    request: ApprovalRequest,
    *,
    approver_id: UUID,
    stage_order: int,
    outcome: str,
    notes: str | None,
) -> None:
    """Record who decided, on which stage, and why.

    A human decision was the one act here that lived nowhere but
    ``approval_decisions`` — a table the organization log does not read and no
    screen shows whole. So the log knew a document had gone to approval and
    never that anybody answered, while the stage that a machine skipped on the
    requester's behalf was written down. The one act with a person behind it
    was the one act missing.

    The approver's own note goes in the log's reason column, where a deletion
    reason already goes: "rejected" without "the supplier changed the price
    list" is the kind of record that gets a right decision re-opened.
    """
    # The row shows the first fields of the snapshot and keeps the rest
    # behind "show the whole change", so the decision and who took it lead:
    # "Stage order: 1 / Stages: 1" in front of them answered nothing.
    names = await people_names_async(db, request.organization_id, [approver_id])
    await log_request_async(
        db,
        request,
        user_id=approver_id,
        action=AuditAction.UPDATE,
        snapshot={
            'decision': outcome,
            'decided_by': names.get(str(approver_id), str(approver_id)),
            'stage_order': stage_order,
            'total_stages': request.total_stages,
            'new_status': request.status,
        },
        reason=as_reason(notes),
    )


def stage_accepts_approver(
    stages: list[dict[str, Any]], stage_order: int, approver_id: UUID
) -> bool:
    """Whether *approver_id* may decide on the stage at *stage_order*.

    An empty ``approver_user_ids`` is an open stage: anyone holding the grant
    decides. A named list is exclusive. This is the rule both decisions and
    the queue read, so a card never offers a button the decision refuses.
    """
    stage = next((s for s in stages if s.get('order') == stage_order), None)
    if stage is None:
        return False
    allowed = stage.get('approver_user_ids') or []
    return not allowed or str(approver_id) in [str(u) for u in allowed]


async def _may_decide_on_own_request(
    db: AsyncSession, org_id: UUID, approver_id: UUID
) -> bool:
    """True when this organization lets admins act on their own requests."""
    settings = await core_api.settings.get_async(db, org_id, 'approvals') or {}
    if not settings.get(SELF_APPROVE_SETTING, False):
        return False
    approver = await core_api.users.get_async(db, org_id, approver_id)
    return bool(approver and approver.role == 'admin')


async def approve_stage(
    db: AsyncSession,
    org_id: UUID,
    request_id: UUID,
    approver_id: UUID,
    notes: str | None = None,
) -> ApprovalRequest:
    # Lock the request row first to prevent concurrent cancel/approve races
    request = (
        (
            await db.execute(
                select(ApprovalRequest)
                .where(
                    ApprovalRequest.id == request_id,
                    ApprovalRequest.organization_id == org_id,
                )
                .with_for_update()
            )
        )
        .scalars()
        .first()
    )
    if request is None:
        raise ApprovalNotFoundError.translated('approval_request_not_found')

    if request.status not in OPEN_STATUSES:
        raise ApprovalError.translated('approval_approve_invalid_status')

    result = await db.execute(
        select(ApprovalDecision)
        .where(
            ApprovalDecision.approval_request_id == request_id,
            ApprovalDecision.status == 'PENDING',
        )
        .with_for_update()
    )
    decision = result.scalars().first()

    if decision is None:
        raise ApprovalError.translated('approval_decision_already_taken')

    if request.created_by == approver_id and not await _may_decide_on_own_request(
        db, org_id, approver_id
    ):
        raise ApprovalError.translated('approval_cannot_approve_own_request')

    workflow = await get_workflow_by_id(db, org_id, request.workflow_id)
    if workflow is None:
        raise ApprovalError.translated('approval_workflow_inactive')

    stages = sorted(workflow.stages or [], key=lambda s: s.get('order', 0))
    current_stage_def = next(
        (s for s in stages if s.get('order') == decision.stage_order), None
    )

    if current_stage_def and not stage_accepts_approver(
        stages, decision.stage_order, approver_id
    ):
        raise ApprovalError.translated('approval_not_stage_approver')

    decision.approver_id = approver_id
    decision.status = 'APPROVED'
    decision.notes = notes
    decision.decided_at = datetime.now(UTC)

    next_order = None
    for stage in stages:
        if stage.get('order', 0) > decision.stage_order:
            next_order = stage['order']
            break

    if next_order is None:
        request.status = 'APPROVED'
        request.current_stage = decision.stage_order
    else:
        request.status = 'IN_PROGRESS'
        request.current_stage = next_order
        next_decision = ApprovalDecision(
            approval_request_id=request.id,
            stage_order=next_order,
            status='PENDING',
        )
        db.add(next_decision)

    await db.flush()
    await _log_decision(
        db,
        request,
        approver_id=approver_id,
        stage_order=decision.stage_order,
        outcome='APPROVED',
        notes=notes,
    )
    # Auto-skip any subsequent stages where the requester is the sole approver.
    await _auto_advance_self_only_stages(db, request, stages, org_id)
    await db.refresh(request, ['decisions'])

    # The last stage settles the question, so whoever owns the target hears
    # about it -- once, after the auto-advance, since that is what decides
    # whether this decision was the final one.
    if request.status == 'APPROVED':
        await clear_settled_notices(db, org_id, request.id)
        await notify_target_decided(
            db,
            TargetDecision(
                organization_id=org_id,
                target_type=request.target_type,
                target_id=request.target_id,
                request_id=request.id,
                outcome='APPROVED',
                requester_id=request.created_by,
                decided_by=approver_id,
            ),
        )

    if next_order is not None:
        # the approvers of the stage that just opened learn about it.
        # Only stage 1 was ever notified, which left two- and three-stage
        # workflows waiting on people who had no way to know it was their turn
        # unless they happened to open the queue.
        #
        # Unlike the notification on creation, this one runs inside the
        # caller's transaction: the stored notification rolls back with the
        # decision it announces, and only the e-mail can outlive a rollback.
        try:
            from ._services_notify import _notify_pending_stage_approvers_async

            await _notify_pending_stage_approvers_async(db, request, stages, org_id)
        except Exception as exc:  # noqa: BLE001 — never fail a decision over a notice
            logger.warning('[Approvals] stage advance notify failed: %s', exc)

    return request


async def reject_request(
    db: AsyncSession,
    org_id: UUID,
    request_id: UUID,
    approver_id: UUID,
    notes: str | None = None,
) -> ApprovalRequest:
    # Lock the request row first to prevent concurrent cancel/reject races
    request = (
        (
            await db.execute(
                select(ApprovalRequest)
                .where(
                    ApprovalRequest.id == request_id,
                    ApprovalRequest.organization_id == org_id,
                )
                .with_for_update()
            )
        )
        .scalars()
        .first()
    )
    if request is None:
        raise ApprovalNotFoundError.translated('approval_request_not_found')

    if request.status not in OPEN_STATUSES:
        raise ApprovalError.translated('approval_reject_invalid_status')

    result = await db.execute(
        select(ApprovalDecision)
        .where(
            ApprovalDecision.approval_request_id == request_id,
            ApprovalDecision.status == 'PENDING',
        )
        .with_for_update()
    )
    decision = result.scalars().first()

    if decision is None:
        raise ApprovalError.translated('approval_decision_already_taken')

    if request.created_by == approver_id and not await _may_decide_on_own_request(
        db, org_id, approver_id
    ):
        raise ApprovalError.translated('approval_cannot_reject_own_request')

    workflow = await get_workflow_by_id(db, org_id, request.workflow_id)
    if workflow is None:
        raise ApprovalError.translated('approval_workflow_inactive')

    stages = sorted(workflow.stages or [], key=lambda s: s.get('order', 0))
    current_stage_def = next(
        (s for s in stages if s.get('order') == decision.stage_order), None
    )

    if current_stage_def and not stage_accepts_approver(
        stages, decision.stage_order, approver_id
    ):
        raise ApprovalError.translated('approval_not_stage_approver')

    decision.approver_id = approver_id
    decision.status = 'REJECTED'
    decision.notes = notes
    decision.decided_at = datetime.now(UTC)

    request.status = 'REJECTED'
    request.current_stage = decision.stage_order
    # no inner commit — ``get_async_db`` commits the whole
    # approve+reject+downstream-cascade as a single transaction at request
    # end. On any exception inside the router the whole thing rolls back.
    await db.flush()
    await _log_decision(
        db,
        request,
        approver_id=approver_id,
        stage_order=decision.stage_order,
        outcome='REJECTED',
        notes=notes,
    )
    await clear_settled_notices(db, org_id, request.id)
    await notify_target_decided(
        db,
        TargetDecision(
            organization_id=org_id,
            target_type=request.target_type,
            target_id=request.target_id,
            request_id=request.id,
            outcome='REJECTED',
            requester_id=request.created_by,
            notes=notes,
        ),
    )
    await db.refresh(request, ['decisions'])
    return request


async def cancel_request(
    db: AsyncSession,
    org_id: UUID,
    request_id: UUID,
    cancelled_by: UUID,
    *,
    cascade: bool = False,
    reason: str | None = None,
) -> ApprovalRequest:
    """Withdraw an open request.

       ``reason`` says why it was closed when the cancelling was not the
       requester's own act (the workflow was switched off); it is kept on the
       request and in the journal entry.

       ``cascade`` marks the call as following the target's own cancellation —
       a document or purchase order being cancelled or deleted takes its approval
       request with it. Authority was already decided on the target there, and
       insisting on the requester's identity left a manager cancelling someone
       else's document with a live request pointing at a cancelled target: an
    approver would open it, decide on it, and change nothing.
    """
    # Lock the request row to prevent concurrent cancel races
    request = (
        (
            await db.execute(
                select(ApprovalRequest)
                .where(
                    ApprovalRequest.id == request_id,
                    ApprovalRequest.organization_id == org_id,
                )
                .with_for_update()
            )
        )
        .scalars()
        .first()
    )
    if request is None:
        raise ApprovalNotFoundError.translated('approval_request_not_found')

    # allow IN_PROGRESS too. A workflow may have multiple stages
    # and the requester needs to retract a request that has already passed
    # the first stage. The previous strict-PENDING guard meant a request
    # could only be cancelled before anyone had a chance to look at it,
    # which in practice is too narrow — once any approver has approved,
    # the requester loses control.
    if request.status not in OPEN_STATUSES:
        raise ApprovalError.translated('approval_cancel_invalid_status')

    # ownership check. Only the requester withdraws their own
    # request — unless the target it belongs to is itself being cancelled.
    if not cascade and request.created_by != cancelled_by:
        raise ApprovalError.translated('approval_only_requester_can_cancel')

    old_status = request.status
    request.status = 'CANCELLED'
    request.cancelled_by = cancelled_by
    request.cancelled_at = datetime.now(UTC)
    if reason:
        request.meta_data = {**(request.meta_data or {}), 'closed_reason': reason}
    # A withdrawal closes an open question and unblocks the target, so it is
    # an act like the decisions are. A cascade writes one too: the module
    # that owns the target records its own cancellation, and neither entry
    # says what happened to the request that was standing in front of it.
    await log_request_async(
        db,
        request,
        user_id=cancelled_by,
        action=AuditAction.UPDATE,
        snapshot={
            'stage_order': request.current_stage,
            'total_stages': request.total_stages,
            'decision': 'CANCELLED',
            'old_status': old_status,
            'new_status': 'CANCELLED',
        },
        meta_data={
            **({'cascade': True} if cascade else {}),
            **({'reason': reason} if reason else {}),
        }
        or None,
    )
    # no inner commit — the router's ``get_async_db`` commits the
    # whole transaction at request end. On any exception (e.g. the     # cascade that calls this service from within cancel_document) the
    # request stays in its pre-cancel state.
    await db.flush()
    await clear_settled_notices(db, org_id, request.id)
    # Nothing is waiting on this target any more, so the module that parked
    # it says so on its own side.
    await notify_target_decided(
        db,
        TargetDecision(
            organization_id=org_id,
            target_type=request.target_type,
            target_id=request.target_id,
            request_id=request.id,
            outcome='CANCELLED',
            requester_id=request.created_by,
            decided_by=cancelled_by,
            released=reason is not None,
        ),
    )
    await db.refresh(request, ['decisions'])
    return request
