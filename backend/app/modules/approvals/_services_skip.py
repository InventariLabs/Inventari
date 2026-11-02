"""Auto-skip for approval stages where the requester is the sole approver.

Prevents deadlocks in solo organizations: when the user who requested approval
is the only configured approver on a stage, no one else can approve it and the
requester is normally blocked from approving their own request. Such stages are
auto-approved on the requester's behalf (with an audit entry) and the request
advances, looping over consecutive self-only stages.

Extracted from ``_services_decisions.py`` to keep that file under the
architecture-lint line limit.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType
from app.core.public_api import core_api

from .models import ApprovalDecision, ApprovalRequest


async def _auto_advance_self_only_stages(
    db: AsyncSession,
    request: ApprovalRequest,
    stages: list[dict[str, Any]],
    org_id: UUID,
) -> None:
    """Auto-skip stages where the requester is the sole configured approver.

    A stage qualifies only when ``approver_user_ids`` is exactly
    ``[request.created_by]`` — an empty list means "anyone" and is NOT
    auto-skipped. Does NOT commit; the caller owns the transaction boundary.
    """
    ordered = sorted(stages, key=lambda s: s.get('order', 0))
    stage_by_order = {s.get('order'): s for s in ordered}
    created_by = str(request.created_by)

    while True:
        stage_def = stage_by_order.get(request.current_stage)
        if stage_def is None:
            return
        approver_ids = [str(u) for u in (stage_def.get('approver_user_ids') or [])]
        if approver_ids != [created_by]:
            return

        pending = await db.scalar(
            select(ApprovalDecision)
            .where(
                ApprovalDecision.approval_request_id == request.id,
                ApprovalDecision.stage_order == request.current_stage,
                ApprovalDecision.status == 'PENDING',
            )
            .with_for_update()
        )
        if pending is None:
            return

        pending.approver_id = request.created_by
        pending.status = 'APPROVED'
        pending.decided_at = datetime.now(UTC)
        pending.notes = 'Auto-approved: requester is the sole approver for this stage'

        await core_api.audit_log.log_action_async(
            db,
            organization_id=org_id,
            user_id=request.created_by,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.APPROVAL_REQUEST,
            target_id=request.id,
            snapshot={
                'stage_order': request.current_stage,
                'auto_skipped': True,
                'reason': 'sole_approver',
            },
        )

        next_order = None
        for stage in ordered:
            if stage.get('order', 0) > request.current_stage:
                next_order = stage['order']
                break

        if next_order is None:
            request.status = 'APPROVED'
            request.current_stage = pending.stage_order
            await db.flush()
            return

        request.status = 'IN_PROGRESS'
        request.current_stage = next_order
        db.add(
            ApprovalDecision(
                approval_request_id=request.id,
                stage_order=next_order,
                status='PENDING',
            )
        )
        await db.flush()
