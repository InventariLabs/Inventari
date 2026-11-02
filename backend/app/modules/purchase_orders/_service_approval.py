"""Purchase order approval transitions: park, approve, reject.

The approvals module decides HOW a request is routed (stages, approvers);
these functions decide how the PO state machine reacts, so the router only
resolves the order and hands it over. ``approve_purchase_order`` queues its
event the way ``confirm_purchase_order`` does — the router drains it after
the commit.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.events import PurchaseOrderConfirmedPayload
from app.core.exceptions import ConflictException, refusal_code, rejection_code
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message
from app.modules.approvals.approvals_api import approvals_api
from app.modules.approvals.exceptions import ApprovalError

from . import _notification_labels as _labels
from ._journal import journal_order_act
from ._service_workflow import _confirm_po_after_approval
from .events import PurchaseOrderEvent
from .models import PurchaseOrder


async def _active_request_or_conflict(
    db: AsyncSession, org_id: UUID, po: PurchaseOrder
) -> Any:
    active = await approvals_api.find_active_request(
        db, org_id, 'purchase_order', po.id
    )
    if active is None:
        key = 'po_no_pending_approval_request'
        raise ConflictException(
            code=rejection_code(key),
            message=get_error_message(key, get_current_lang()),
        )
    return active


async def _journal_approval_act(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    po: PurchaseOrder,
    previous_status: str,
    decision: str,
    notes: str | None,
) -> None:
    """One entry per approval act on the order, whether or not it moved it.

    The approvals module journals its own request row, which names the
    request and not the order. A stage approved while later ones are still
    open leaves the order where it was, and that decision is still the fact.
    """
    await journal_order_act(
        db,
        org_id,
        user_id,
        po,
        before={'status': previous_status},
        after={'status': po.status},
        act={'approval': decision, **({'notes': notes} if notes else {})},
    )


async def request_purchase_order_approval(
    db: AsyncSession,
    org_id: UUID,
    po: PurchaseOrder,
    user_id: UUID,
    notes: str | None = None,
) -> Any:
    """Open an approval request and park the PO in PENDING_APPROVAL.

    PENDING_APPROVAL is allowed on purpose: withdrawing a request leaves
    the PO parked with nothing pending on it, and insisting on DRAFT
    here was the third of three actions that answered 409, so the order
    had no way forward at all. A PO that still has an active
    request is refused by the approvals engine itself.
    """
    if po.status not in ('DRAFT', 'PENDING_APPROVAL'):
        raise ConflictException(
            code='INVALID_STATUS',
            message=get_error_message(
                'po_request_approval_invalid_status', get_current_lang()
            ),
        )
    try:
        request_obj = await approvals_api.request_approval(
            db,
            org_id,
            'purchase_order',
            po.id,
            user_id,
            meta_data={'notes': notes} if notes else None,
        )
    except ApprovalError as exc:
        raise ConflictException(
            code=refusal_code(exc, 'APPROVAL_ERROR'), message=str(exc)
        ) from exc
    # Park the PO so it is visible in the PENDING_APPROVAL filter.
    previous_status = po.status
    po.status = 'PENDING_APPROVAL'
    await db.flush()
    await _journal_approval_act(
        db, org_id, user_id, po, previous_status, 'requested', notes
    )
    return request_obj


async def approve_purchase_order(
    db: AsyncSession,
    org_id: UUID,
    po: PurchaseOrder,
    user_id: UUID,
    notes: str | None = None,
) -> Any:
    """Approve the active stage; the last stage flips the PO to CONFIRMED."""
    if po.status != 'PENDING_APPROVAL':
        raise ConflictException(
            code='INVALID_STATUS',
            message=get_error_message('po_approve_invalid_status', get_current_lang()),
        )
    previous_status = po.status
    active = await _active_request_or_conflict(db, org_id, po)
    try:
        request_obj = await approvals_api.approve_stage(
            db, org_id, active.id, user_id, notes=notes
        )
    except ApprovalError as exc:
        raise ConflictException(
            code=refusal_code(exc, 'APPROVAL_ERROR'), message=str(exc)
        ) from exc

    if request_obj.status == 'APPROVED':
        await _confirm_po_after_approval(db, po, user_id)
        await core_api.events.emit_transactional_async(
            db,
            PurchaseOrderEvent.CONFIRMED,
            PurchaseOrderConfirmedPayload(
                po_id=str(po.id),
                po_number=po.number,
                organization_id=str(org_id),
            ),
        )
    await _journal_approval_act(
        db, org_id, user_id, po, previous_status, 'approved', notes
    )
    return request_obj


async def reject_purchase_order(
    db: AsyncSession,
    org_id: UUID,
    po: PurchaseOrder,
    user_id: UUID,
    notes: str | None = None,
) -> Any:
    """Reject the active request; the PO returns to DRAFT for rework.

    The requester is notified. The approvals helper
    ``notify_rejection_async`` is documents-specific (keyword-only
    ``doc_id``), so core notifications are used directly.
    """
    active = await _active_request_or_conflict(db, org_id, po)
    try:
        request_obj = await approvals_api.reject_request(
            db, org_id, active.id, user_id, notes=notes
        )
    except ApprovalError as exc:
        raise ConflictException(
            code=refusal_code(exc, 'APPROVAL_ERROR'), message=str(exc)
        ) from exc

    # Rework loop: rejected PO returns to DRAFT so the requester can
    # edit and re-submit (mirrors the documents reject flow).
    previous_status = po.status
    po.status = 'DRAFT'
    await db.flush()
    await _journal_approval_act(
        db, org_id, user_id, po, previous_status, 'rejected', notes
    )

    # The reason is part of the sentence, so it has to be composed in the
    # same language as the sentence it lands in.
    content = {
        lang: text.format(
            po=po.number,
            reason=(
                _labels.PO_REJECTED_REASON[lang].format(notes=notes) if notes else ''
            ),
        )
        for lang, text in _labels.PO_REJECTED_CONTENT.items()
    }
    notification = await core_api.notifications.create_async(
        db,
        user_id=active.created_by,
        title=core_api.notifications.localize(_labels.PO_REJECTED_TITLE, po=po.number),
        content=content,
        notification_type='warning',
        link=f'/purchase-orders/{po.id}',
    )
    await core_api.notifications.publish_async(db, notification)
    return request_obj
