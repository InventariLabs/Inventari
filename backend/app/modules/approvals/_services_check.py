from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.public_api import core_api

from ._services_requesters import requester_in_scope_async
from ._services_workflow import get_active_workflow
from .exceptions import ApprovalRequiredError
from .models import OPEN_STATUSES, ApprovalRequest

logger = get_logger(__name__)


async def requester_exempt_async(
    db: AsyncSession, org_id: UUID, target_type: str, user_id: UUID | None
) -> bool:
    """Whether the active workflow for ``target_type`` leaves this person out.

    ``False`` when there is no active workflow — whether an approval is due
    then is the module's own question, and its answer (usually a refusal
    naming the missing workflow) stays what it was — and when nobody is
    named: a submission nobody can be found behind is held rather than
    waved through.
    """
    if user_id is None:
        return False
    workflow = await get_active_workflow(db, org_id, target_type)
    if workflow is None:
        return False
    return not await requester_in_scope_async(db, org_id, workflow, user_id)


async def check_and_block(
    db: AsyncSession,
    org_id: UUID,
    target_type: str,
    target_id: UUID,
    *,
    require_workflow: bool = False,
) -> None:
    """Refuse unless this target has the approval it needs.

    No active workflow normally means nobody asked for a control here, so
    there is nothing to enforce. ``require_workflow`` says the caller has
    already decided this particular target is under one — and a control that
    cannot be run is not a control that has been satisfied. A target already
    approved still passes: the approval was given while the workflow existed,
    and taking the workflow away does not take it back. One that has been
    *spent* does not, though — a target that acts once spends its approval
    with :func:`consume_approval`, and a spent row is not a live one.

    Switched off means stood down (``docs/purpose/approvals.md``): when the
    module is not enabled for the organization, this is a no-op and the
    operation that would have waited simply proceeds. A document parked in
    PENDING_APPROVAL used to stay un-postable, unreadable and un-withdrawable
    with the module off — the refusal even told the reader to request an
    approval, which a disabled module makes impossible.
    """
    if not await core_api.organizations.is_module_enabled_async(
        db, org_id, 'approvals'
    ):
        return

    workflow = await get_active_workflow(db, org_id, target_type)
    if workflow is None and not require_workflow:
        return

    # The newest request that says something decides. Asking "is there an
    # approved request" first meant the answer never changed again: approval
    # rows are an audit trail, so the old one stays in the table and every
    # later submission was decorative -- resubmit, be rejected, and the
    # target went through anyway.
    #
    # A withdrawn request says nothing, so it is not the newest anything;
    # without that, cancelling a resubmission would block a target its
    # owner had already approved.
    #
    # An approval already spent is spent: a target that acts once (an
    # equipment checkout) consumes its approval, and the same row must not
    # keep passing the gate afterwards. Its targets that never consume
    # (a document) are unaffected -- their APPROVED rows stay unconsumed.
    latest = (
        await db.scalars(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.organization_id == org_id,
                ApprovalRequest.target_type == target_type,
                ApprovalRequest.target_id == target_id,
                ApprovalRequest.status.in_(['APPROVED', 'REJECTED', *OPEN_STATUSES]),
            )
            .order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id.desc())
            .limit(1)
        )
    ).first()

    if (
        latest is not None
        and latest.status == 'APPROVED'
        and latest.consumed_at is None
    ):
        return

    if latest is not None and latest.status == 'REJECTED':
        raise ApprovalRequiredError.translated('approval_required_after_rejection')

    if workflow is None:
        # Under a control with nothing to run it through. "Request one first"
        # would be advice nobody can follow.
        raise ApprovalRequiredError.translated('approval_workflow_required_but_missing')

    raise ApprovalRequiredError.translated('approval_required_first')


async def consume_approval(
    db: AsyncSession,
    org_id: UUID,
    target_type: str,
    target_id: UUID,
    consumed_by: UUID,
) -> bool:
    """Spend the target's newest unconsumed approval, so it authorises one act.

    A consuming module calls this after :func:`check_and_block` has let it
    past and inside its own transaction -- this flushes and returns, it does
    not commit. ``False`` when there was nothing to spend, which means the
    gate was satisfied some other way (no workflow, or an already-spent
    approval under no control).

    Only the newest APPROVED request is spent. The gate reads that same row
    and refuses on anything newer, so spending an older one would consume an
    approval the gate had already stopped counting.
    """
    request = (
        await db.scalars(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.organization_id == org_id,
                ApprovalRequest.target_type == target_type,
                ApprovalRequest.target_id == target_id,
                ApprovalRequest.status == 'APPROVED',
                ApprovalRequest.consumed_at.is_(None),
            )
            .order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id.desc())
            .limit(1)
        )
    ).first()
    if request is None:
        return False
    request.consumed_at = datetime.now(UTC)
    request.consumed_by = consumed_by
    await db.flush()
    return True
