from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType
from app.core.events import emit_transactional_safe
from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api

from ._document_workflow_crud import (
    _release_quants_for_doc,
    _unpin_the_lines,
    get_or_raise,
)
from ._document_workflow_helpers import build_document_event_payload
from .events import DocumentEvent
from .models import Document, DocumentStatus


async def rework_to_draft_after_reject(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    module: str,
    *,
    user_id: UUID | None = None,
    reason: str | None = None,
) -> Document:
    """Rework loop: PENDING_APPROVAL/CONFIRMED → DRAFT after a refusal.

    Called when the module a document waits for refuses it — for the
    approvals module, when its request is rejected. Refused documents must
    become editable again so the requester can fix the issue and re-submit,
    instead of being forced to cancel + recreate the document (which loses
    lines and audit trail). Stock reservations held in PENDING_APPROVAL are
    released so they do not block other documents during rework. Telling
    the requester is the refusing module's business.

    Idempotent: a doc already in DRAFT is returned unchanged (no release
    call). A document waiting for another module is not this one's to send
    back, and is refused like any other state.

    The document's own journal carries the step, as the release does: who
    sent it back (``user_id``) and why (``reason``), so its history does not
    end at "Waiting for approval" while the document is a draft again.
    """
    doc = await get_or_raise(db, org_id, doc_id)

    if doc.status == DocumentStatus.DRAFT.value:
        return doc

    if doc.status not in {
        DocumentStatus.CONFIRMED.value,
        DocumentStatus.PENDING_APPROVAL.value,
    } or doc.held_by not in (None, module):
        raise ServiceRejectionError('document_rework_wrong_status', status=doc.status)

    # Release stock reservations (OUT/INT hold stock capacity for the
    # receiving/storage step). Same helper as the cancel transition.
    await _release_quants_for_doc(db, doc)
    _unpin_the_lines(doc)

    old_status = doc.status
    doc.status = DocumentStatus.DRAFT.value
    doc.held_by = None
    doc.confirmed_by = None
    doc.confirmed_at = None
    await db.flush()
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.DOCUMENT,
        target_id=doc.id,
        snapshot={
            'number': doc.number,
            'type': doc.type,
            'old_status': old_status,
            'new_status': DocumentStatus.DRAFT.value,
        },
        reason=reason,
    )
    await db.refresh(doc, attribute_names=['lines'])

    # Emit DOCUMENT_CANCELLED so cross-module consumers (purchase_orders
    # PO-line capacity recompute, stats updates, downstream analytics)
    # see the capacity freed by the rework. Same payload as the cancel
    # transition — the doc is going from a reserved state (PENDING_APPROVAL
    # / CONFIRMED) back to a draft, the same observable effect on stock
    # capacity as a cancellation. The event is best-effort (failure
    # must not block or roll back the rework).
    await emit_transactional_safe(
        db,
        DocumentEvent.CANCELLED,
        await build_document_event_payload(db, doc, org_id),
    )

    return doc
