"""PO status recompute + COMPLETED event/notifications.

Extracted from ``_service_workflow.py`` to keep that file under the 400 LOC
limit. ``recalculate_po_quantities`` recomputes ``quantity_received`` on PO
lines from completed receipts and drives the CONFIRMED↔COMPLETED status
transitions; ``_emit_po_completed`` is its private helper that records the
PURCHASE_ORDER_COMPLETED event and notifies stakeholders. The helper is only
ever called from ``recalculate_po_quantities``, so both live together here.

Like the workflow operations in ``_service_workflow``, the COMPLETED event
is written to the outbox in the caller's transaction.
"""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.events import PurchaseOrderCompletedPayload
from app.core.public_api import core_api
from app.core.scoped_session import AsyncModuleScopedSession
from app.modules.warehouse.warehouse_api import warehouse_api

from . import _notification_labels as _labels
from ._service_crud import get_purchase_order
from .events import PurchaseOrderEvent
from .models import PurchaseOrder, PurchaseOrderLine


async def recalculate_po_quantities(
    db: AsyncSession | AsyncModuleScopedSession,
    org_id: UUID,
    po_line_ids: list[UUID],
) -> None:
    """Recalculate ``quantity_received`` on PO lines from completed receipts.

    Called when a linked receipt document is completed or cancelled.
    Only COMPLETED receipt documents contribute to quantity_received.
    Also transitions PO status: CONFIRMED→COMPLETED when fully received,
    COMPLETED→CONFIRMED when quantities drop below ordered.
    """
    if not po_line_ids:
        return

    active_totals = await warehouse_api.get_active_received_quantities_async(
        db,  # type: ignore[arg-type]
        org_id,
        po_line_ids,
    )

    result = await db.execute(
        select(PurchaseOrderLine)
        .where(
            PurchaseOrderLine.id.in_(po_line_ids),
        )
        .with_for_update(of=PurchaseOrderLine)
    )
    lines = list(result.scalars().all())
    affected_po_ids: set[UUID] = set()
    for line in lines:
        line.quantity_received = active_totals.get(line.id, Decimal('0'))
        affected_po_ids.add(line.purchase_order_id)
    await db.flush()

    for po_id in affected_po_ids:
        po = await get_purchase_order(db, org_id, po_id, for_update=True)  # type: ignore[arg-type]
        if not po:
            continue
        all_received = all(
            ln.quantity_received >= ln.quantity_ordered for ln in po.lines
        )
        if all_received and po.status == 'CONFIRMED':
            po.status = 'COMPLETED'
            await _emit_po_completed(db, org_id, po)
        elif not all_received and po.status == 'COMPLETED':
            po.status = 'CONFIRMED'
    await db.flush()


async def _emit_po_completed(
    db: AsyncSession | AsyncModuleScopedSession,
    org_id: UUID,
    po: PurchaseOrder,
) -> None:
    """Record PURCHASE_ORDER_COMPLETED in the outbox and notify stakeholders."""
    payload_obj = PurchaseOrderCompletedPayload(
        po_id=str(po.id),
        po_number=po.number,
        organization_id=str(org_id),
    )
    session = db.raw_session if hasattr(db, 'raw_session') else db
    await core_api.events.emit_transactional_async(
        session, PurchaseOrderEvent.COMPLETED, payload_obj
    )

    try:
        admin_notifications = await core_api.notifications.notify_org_admins_async(
            session,
            organization_id=org_id,
            title=core_api.notifications.localize(
                _labels.PO_COMPLETED_TITLE, po=po.number
            ),
            content=core_api.notifications.localize(
                _labels.PO_COMPLETED_CONTENT, po=po.number
            ),
            notification_type='success',
            link=f'/purchase-orders/{po.id}',
        )
        # An administrator who raised the order has just been told; a second
        # notice about the same event would only say it again.
        creator_told = any(n.user_id == po.created_by for n in admin_notifications)
        creator_notification = None
        if po.created_by and not creator_told:
            creator_notification = await core_api.notifications.create_async(
                session,
                user_id=po.created_by,
                title=core_api.notifications.localize(
                    _labels.PO_COMPLETED_OWN_TITLE, po=po.number
                ),
                content=core_api.notifications.localize(
                    _labels.PO_COMPLETED_OWN_CONTENT, po=po.number
                ),
                notification_type='success',
                link=f'/purchase-orders/{po.id}',
            )
        await core_api.notifications.publish_async(
            session,
            [n for n in [*admin_notifications, creator_notification] if n is not None],
        )
    except Exception:  # noqa: BLE001 — notices are best-effort; the completion stands
        from app.core.logging import get_logger

        get_logger(__name__).warning('Failed to send PO completion notifications')
