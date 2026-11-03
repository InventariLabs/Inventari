from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import build_module_context
from app.core.contracts import UserContextDTO
from app.core.exceptions import ServiceRejectionError
from app.core.logging import get_logger
from app.core.money import quantise
from app.i18n.service import get_current_lang, get_error_message
from app.models.audit_log import AuditAction, AuditTargetType
from app.models.item import Item
from app.models.item_history import ItemAction
from app.services.audit_service import log_action_async

from ._stock_quant import apply_quantity_change_async as apply_quantity_change
from .history import log_history_async

logger = get_logger(__name__)


async def delete_item(
    db: AsyncSession,
    item: Item,
    user: UserContextDTO,
    reason: str | None = None,
    notes: str | None = None,
) -> None:
    """Soft-delete item: sets is_deleted=True, zeros quantity, posts its movement.

    The item row persists for audit. Use purge_item() for permanent removal.
    """
    from app.core.events import SystemEvent, TenantEventPayload, event_bus
    from app.core.interceptors import interceptor_pipeline

    if item.is_deleted:
        raise ServiceRejectionError('item_already_deleted')

    context = build_module_context(db, user.organization_id, user)

    await interceptor_pipeline.run_before_item_delete(item.id, context)

    old_quantity = item.quantity

    # The quant this record stands on is shared with every other record of
    # the same product in the same place, and the reservations on it belong
    # to documents. Releasing this record's whole quantity therefore handed
    # away holds that other records still backed -- scrapping one bottle of
    # six freed the picking document's claim on the other five.
    #
    # Zeroing the record still has to be possible, and it is refused while
    # more is held than the remaining stock covers, so what goes is exactly
    # the part left without stock behind it, rows and all.
    if item.template_id and item.storage_location_id and old_quantity:
        from sqlalchemy import func, select

        from app.models.stock_quants_from_records import stock_quants_from_records
        from app.services._stock_reservation import release_unbacked_async

        # One indexed SELECT to skip the locking read in the common case,
        # where nothing on this shelf is reserved at all. The promises come
        # from the reservation rows through the records' view: they are what
        # a release acts on, and nothing else keeps a total of them.
        reserved_total = await db.scalar(
            select(
                func.coalesce(
                    func.sum(stock_quants_from_records.c.reserved_quantity), 0
                )
            ).where(
                stock_quants_from_records.c.organization_id == item.organization_id,
                stock_quants_from_records.c.product_template_id == item.template_id,
                stock_quants_from_records.c.storage_location_id
                == item.storage_location_id,
                stock_quants_from_records.c.reserved_quantity > 0,
            )
        )
        if reserved_total and reserved_total > 0:
            await release_unbacked_async(
                db,
                organization_id=item.organization_id,
                product_template_id=item.template_id,
                location_id=item.storage_location_id,
                leaving_quantity=old_quantity,
            )

    # The label stays bound. A sticker outlives the thing it was stuck to, and
    # the question a warehouse actually asks is "what was under this one" —
    # scanning it opens the archived-item sheet, which reports the history and
    # frees the slot on request (unassign_label_async clears both sides). The
    # label pool lists these under "Consumed (Archived)", so a label released
    # this way is never lost, only waiting for someone to say it is free.
    #
    # The hand that emptied the record travels onto the movement: without it
    # the Movements journal reads "Kto: —" for an archive, while the
    # consumption and disposal beside it name their author.
    await apply_quantity_change(db, item, Decimal('0'), user_id=user.id)

    item.is_deleted = True
    item.deleted_at = datetime.now(UTC)
    item.deleted_by = user.id
    item.deletion_reason = reason

    await db.flush()

    await log_history_async(
        db,
        item,
        ItemAction.DELETED,
        {
            'reason': reason,
            'notes': notes,
            'old_quantity': float(old_quantity) if old_quantity else 0.0,
        },
        user_id=user.id,
    )
    await log_action_async(
        db,
        organization_id=item.organization_id,
        user_id=user.id,
        action=AuditAction.SOFT_DELETE,
        target_type=AuditTargetType.ITEM,
        target_id=item.id,
        snapshot={
            'name': item.name,
            'barcode': item.barcode,
            'old_quantity': quantise(old_quantity or Decimal('0'), 3),
        },
        reason=reason,
        meta_data={'notes': notes} if notes else None,
    )

    await event_bus.emit_transactional(
        db,
        SystemEvent.ITEM_DELETED,
        TenantEventPayload.model_validate(
            {
                'organization_id': str(item.organization_id),
                'item_id': str(item.id),
                'user_id': str(user.id),
            }
        ),
    )
    await interceptor_pipeline.run_after_item_delete(item.id, context)


async def restore_item(
    db: AsyncSession,
    item: Item,
    user: UserContextDTO,
) -> Item:
    """Restore a soft-deleted item back to active state."""
    from sqlalchemy import select

    from app.core.events import SystemEvent, TenantEventPayload, event_bus
    from app.models.item_history import ItemHistory

    if not item.is_deleted:
        raise ServiceRejectionError('item_not_deleted')

    if item.deleted_at:
        await log_history_async(
            db,
            item,
            ItemAction.RESTORED,
            {
                'restored': True,
                'previous_deletion_reason': item.deletion_reason,
                'deleted_at': item.deleted_at.isoformat(),
            },
            user_id=user.id,
        )

    # Read the pre-deletion quantity from the DELETED history entry
    # instead of hardcoding 1. delete_item stores old_quantity there.
    restore_qty = Decimal('1')
    deleted_entry = await db.execute(
        select(ItemHistory.changes)
        .where(
            ItemHistory.item_id == item.id,
            ItemHistory.action == ItemAction.DELETED.value,
        )
        .order_by(ItemHistory.created_at.desc())
        .limit(1)
    )
    changes_row = deleted_entry.first()
    if changes_row and changes_row[0]:
        old_qty = changes_row[0].get('old_quantity')
        if old_qty is not None and old_qty > 0:
            restore_qty = Decimal(str(old_qty))
        else:
            raise ServiceRejectionError('item_restore_quantity_unknown')
    else:
        raise ServiceRejectionError('item_restore_quantity_unknown')

    deleted_reason = item.deletion_reason
    item.is_deleted = False
    item.deleted_at = None
    item.deleted_by = None
    item.deletion_reason = None

    await apply_quantity_change(db, item, restore_qty, user_id=user.id)
    await db.flush()

    # The SOFT_DELETE entry above it used to be the last word, and reading
    # the journal alone said the product was gone. A restore is the pair
    # that entry lacked.
    await log_action_async(
        db,
        organization_id=item.organization_id,
        user_id=user.id,
        action=AuditAction.RESTORE,
        target_type=AuditTargetType.ITEM,
        target_id=item.id,
        snapshot={
            'name': item.name,
            'before': {'is_deleted': True, 'deletion_reason': deleted_reason},
            'after': {
                'is_deleted': False,
                # The restored number was read back from the history as a float;
                # the journal records the digits the column keeps.
                'quantity': quantise(item.quantity, 3),
            },
        },
    )

    await event_bus.emit_transactional(
        db,
        SystemEvent.ITEM_UPDATED,
        TenantEventPayload.model_validate(
            {
                'organization_id': str(user.organization_id),
                'item': item,
                'changes': {'restored': True},
                'user_id': str(user.id),
            }
        ),
    )

    await db.refresh(item, ['category', 'template'])
    return item


async def purge_item(
    db: AsyncSession,
    item: Item,
    user: UserContextDTO | None,
    reason: str | None = None,
) -> None:
    """Permanently remove a soft-deleted item from the database.

       Only items with is_deleted=True can be purged.
       Logs the full item snapshot to the immutable audit_log before deletion.
       In production (DEBUG=False), requires a non-trivial reason string.

       ``user`` may be ``None`` for system-initiated purges (archive retention):
       the audit entry then carries a null ``user_id`` with the reason marking
       the actor (e.g. ``RETENTION``).

    before deleting, the ``before_purge`` interceptor hook runs so
       modules can veto the irreversible path (e.g. posted document lines,
       stock-take evidence); the item's full ``ItemHistory`` is captured into
       the PURGE audit entry because the FK CASCADE wipes those rows.
    """
    from app.config import settings
    from app.core.events import SystemEvent, TenantEventPayload, event_bus
    from app.core.interceptors import interceptor_pipeline
    from app.services.audit_service import item_to_snapshot, log_purge_async

    from ._update import _reference_names

    if not item.is_deleted:
        raise ServiceRejectionError('item_purge_requires_archived')

    if not await _org_allows_permanent_delete(db, item.organization_id):
        raise PermissionError(
            get_error_message('permanent_delete_disabled', get_current_lang())
        )

    if (
        not settings.DEBUG
        and not settings.TESTING
        and (not reason or len(reason.strip()) < 3)
    ):
        raise ServiceRejectionError('item_purge_reason_required')

    item_id = item.id
    organization_id = str(item.organization_id)

    context = build_module_context(db, organization_id, user)

    # Modules may veto the purge before anything is written or deleted.
    await interceptor_pipeline.run_before_item_purge(item_id, context)

    # The row is about to stop existing and this entry is the only place its
    # references survive, so the organization, the shelf, the category and
    # the template it stood for are named here — a purge row that says
    # `Location: 67d57628` outlives even the id's usefulness.
    snapshot = item_to_snapshot(item) | await _reference_names(
        db,
        {
            'organization_id': item.organization_id,
            'storage_location_id': item.storage_location_id,
            'category_id': item.category_id,
            'template_id': item.template_id,
        },
    )
    history = await _capture_item_history(db, item_id)

    await log_purge_async(
        db,
        organization_id=item.organization_id,
        user_id=user.id if user else None,
        target_type='item',
        target_id=item_id,
        snapshot=snapshot,
        reason=reason,
        meta_data={
            'environment': 'development' if settings.DEBUG else 'production',
            'item_history': history,
        },
    )

    await db.delete(item)
    await db.flush()

    await event_bus.emit_transactional(
        db,
        SystemEvent.ITEM_DELETED,
        TenantEventPayload.model_validate(
            {
                'organization_id': organization_id,
                'item_id': str(item_id),
                'user_id': str(user.id) if user is not None else None,
            }
        ),
    )
    await interceptor_pipeline.run_after_item_delete(item_id, context)


async def _capture_item_history(
    db: AsyncSession, item_id: UUID
) -> list[dict[str, Any]]:
    """Serialise the item's full history before purge destroys it.

       ``item_history.item_id`` has ``ondelete='CASCADE'``, so purging an item
       silently wipes every movement/quantity/location change. Capturing the
       rows here and attaching them to the PURGE audit entry keeps that evidence
    readable in the immutable ``audit_log`` (variant 2 — no FK change).
    """
    from sqlalchemy import select

    from app.models.item_history import ItemHistory

    result = await db.execute(
        select(ItemHistory)
        .where(ItemHistory.item_id == item_id)
        .order_by(ItemHistory.created_at)
    )
    rows = result.scalars().all()
    return [
        {
            'id': str(h.id),
            'action': h.action,
            'changes': h.changes,
            'source_document_id': str(h.source_document_id)
            if h.source_document_id
            else None,
            'user_id': str(h.user_id) if h.user_id else None,
            'created_at': h.created_at.isoformat() if h.created_at else None,
        }
        for h in rows
    ]


# Business profiles that start with permanent deletion locked — the org can
# still switch the explicit setting on knowingly.
_PURGE_LOCKED_PROFILES = frozenset({'equipment_wms', 'clean_core'})


def resolve_allow_permanent_delete(
    settings: dict[str, Any] | None, active_profile_id: str | None
) -> bool:
    """Effective ``allow_permanent_delete`` value for an organization.

    The explicit ``settings['allow_permanent_delete']`` wins. When unset,
    the product profile decides: home profiles keep the convenience, audited
    business profiles start locked; legacy orgs without a profile keep the
    historical behaviour (allowed).
    """
    if settings and 'allow_permanent_delete' in settings:
        return bool(settings['allow_permanent_delete'])
    return active_profile_id not in _PURGE_LOCKED_PROFILES


async def _org_allows_permanent_delete(db: AsyncSession, organization_id: UUID) -> bool:
    """Load the org and resolve the purge flag.

    ``active_profile_id`` is deferred on the model — select the two columns
    explicitly. A plain ``db.get(... options=[undefer(...)])`` is not enough:
    when the org is already in the identity map (as in the retention run)
    the options are ignored and touching the attribute would lazy-load on an
    async session.
    """
    from sqlalchemy import select

    from app.models.organization import Organization

    row = (
        await db.execute(
            select(Organization.settings, Organization.active_profile_id).where(
                Organization.id == organization_id
            )
        )
    ).one_or_none()
    if row is None:
        return False
    return resolve_allow_permanent_delete(row.settings, row.active_profile_id)
