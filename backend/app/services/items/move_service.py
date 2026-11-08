from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import build_module_context
from app.core.contracts import UserContextDTO
from app.core.events import SystemEvent, TenantEventPayload, event_bus
from app.core.exceptions import NotFoundException, ServiceRejectionError
from app.core.logging import get_logger
from app.core.money import quantise
from app.i18n.service import get_current_lang
from app.models.audit_log import AuditAction, AuditTargetType
from app.models.item import Item
from app.models.item_history import ItemAction
from app.models.storage_location import LocationUsage, StorageLocation
from app.schemas.item import ItemConsumeRequest, ItemDiscardRequest, ItemMove
from app.services.audit_service import log_action_async

from ._stock_relocation import carry_record_stock_async, lock_shelf_change_async
from .history import log_history_async

logger = get_logger(__name__)


async def _location_name_async(db: AsyncSession, storage_id: UUID | None) -> str:
    """A human-readable name for the journal's before/after of a move.

    A row reading `storage_location_id: 4c3d… → 8f2a…` answers nothing at a
    glance; the reader is owed the names the map uses. The raw id is the
    fallback for a location that no longer exists — the journal stays
    precise even when the tree has moved on.
    """
    if storage_id is None:
        return '—'
    storage = await db.get(StorageLocation, storage_id)
    return storage.name if storage else str(storage_id)


async def _reduce_quantity(
    db: AsyncSession,
    item: Item,
    quantity: Decimal,
    user: UserContextDTO,
    virtual_usage: LocationUsage,
    action: ItemAction,
    event: SystemEvent,
    source_document_id: UUID | None = None,
    reason: str | None = None,
    notes: str | None = None,
) -> Item:
    """Shared logic for consume and discard operations."""
    from app.core.interceptors import interceptor_pipeline
    from app.core.period_guard import check_period_not_closed
    from app.services.analytics._common import org_today_async

    # Real-time item mutations are guarded by the inventory period, and
    # which day it is decides membership — so it is the organization's day,
    # not the server's (no scheduled_date context: these are ad-hoc actions,
    # not document-driven).
    if user.organization_id is not None:
        await check_period_not_closed(
            db, user.organization_id, await org_today_async(db, user.organization_id)
        )

    from app.services.items._stock_quant import lock_record_stock_async

    # The new number is worked out from the old one, so the old one is read
    # under the lock: two hands taking three off the same five each read
    # five before anybody locked, and both went through.
    await lock_record_stock_async(db, item)
    if item.quantity < quantity:
        raise ServiceRejectionError('insufficient_quantity')

    context = build_module_context(db, user.organization_id, user)

    if action == ItemAction.USED:
        await interceptor_pipeline.run_before_item_consume(item.id, quantity, context)
    elif action == ItemAction.DISPOSED:
        await interceptor_pipeline.run_before_item_discard(item.id, quantity, context)

    from app.services.items._stock_quant import (
        apply_quantity_change_async as _apply_async,
    )

    # The action is the reason, and this is the only place that knows it:
    # further down, the ledger sees a quantity going away and nothing else.
    # The hand travels with it — a movement without its author reads as "—"
    # in the journal while every other door signs its rows.
    old_q = await _apply_async(
        db, item, item.quantity - quantity, outflow_reason=action.value, user_id=user.id
    )

    if item.quantity <= 0:
        from app.services.storage._defaults import (
            ensure_virtual_locations_async,
            get_virtual_location_async,
        )

        await ensure_virtual_locations_async(
            db, str(user.organization_id), str(user.id)
        )
        virtual_loc = await get_virtual_location_async(
            db, str(user.organization_id), virtual_usage
        )
        if virtual_loc:
            await lock_shelf_change_async(db, [item], virtual_loc.id)
            item.storage_location_id = virtual_loc.id

    await db.flush()
    await db.refresh(item)
    item_id = item.id
    # The caller asked why, so record why. Both request schemas carry a
    # reason and a note; without this they travelled as far as the endpoint
    # and stopped there, and the history entry could not answer the one
    # question it is kept for.
    # The exact digits, as every quantity in the history (AUDIT.md): a float
    # here is less precise than the data it describes.
    details: dict[str, object] = {'qty': str(quantity), 'old': str(old_q)}
    if reason:
        details['reason'] = reason
    if notes:
        details['notes'] = notes
    await log_history_async(
        db,
        item,
        action,
        details,
        user_id=user.id,
        source_document_id=source_document_id,
    )
    # The journal's verb says why the shelf shrank: a use is not a dispose
    # is not a correction, and "quantity: 10 → 8" alone answers none of it.
    audit_action = AuditAction.USE if action == ItemAction.USED else AuditAction.DISPOSE
    await log_action_async(
        db,
        organization_id=item.organization_id,
        user_id=user.id,
        action=audit_action,
        target_type=AuditTargetType.ITEM,
        target_id=item.id,
        snapshot={
            'name': item.name,
            'before': {'quantity': quantise(old_q, 3)},
            'after': {'quantity': quantise(item.quantity, 3)},
        },
        reason=reason,
        meta_data={'notes': notes} if notes else None,
    )

    from fastapi.encoders import jsonable_encoder

    event_payload_dict = {
        'organization_id': str(user.organization_id),
        'item': jsonable_encoder(item),
        'quantity': float(quantity),
        'user_id': str(user.id),
    }
    await event_bus.emit_transactional(
        db, event, TenantEventPayload.model_validate(event_payload_dict)
    )

    if action == ItemAction.USED:
        await interceptor_pipeline.run_after_item_consume(item_id, quantity, context)
    elif action == ItemAction.DISPOSED:
        await interceptor_pipeline.run_after_item_discard(item_id, quantity, context)

    await db.refresh(item, ['category'])
    return item


async def move_item(
    db: AsyncSession,
    item: Item,
    move_data: ItemMove,
    user: UserContextDTO,
    source_document_id: UUID | None = None,
    history_changes: dict | None = None,
    history_action: ItemAction = ItemAction.MOVED,
    post_the_change: bool = True,
) -> Item:
    from app.core.period_guard import check_period_not_closed

    # Block moves during closed inventory periods. The guard runs
    # after target_storage lookup so 404 vs 409 are unambiguous, and the
    # day that decides membership is the organization's, not the server's.
    if user.organization_id is not None:
        from app.services.analytics._common import org_today_async

        await check_period_not_closed(
            db,
            user.organization_id,
            await org_today_async(db, user.organization_id),
        )

    result = await db.scalars(
        select(StorageLocation).where(
            StorageLocation.id == move_data.to_location_id,
            StorageLocation.organization_id == user.organization_id,
        ),
    )
    target_storage = result.first()

    if not target_storage:
        raise NotFoundException('storage', get_current_lang())

    old_storage_id = item.storage_location_id

    # A move to the same location is a no-op. Previously the code below
    # still decremented the source and re-incremented the destination, which
    # for a reserved source quant silently eroded reserved_quantity.
    if old_storage_id == move_data.to_location_id:
        await db.flush()
        await log_history_async(
            db,
            item,
            history_action,
            {
                'from': str(old_storage_id),
                'to': str(move_data.to_location_id),
                'notes': move_data.notes,
                'same_location_noop': True,
                **(history_changes or {}),
            },
            user_id=user.id,
            source_document_id=source_document_id,
        )
        return item

    await lock_shelf_change_async(db, [item], move_data.to_location_id)
    item.storage_location_id = move_data.to_location_id

    if post_the_change:
        # Refuses when the source quant still holds reservations, and
        # carries the lots across — the same call every door that writes a
        # record's shelf makes.
        await carry_record_stock_async(
            db,
            item,
            from_location_id=old_storage_id,
            quantity=item.quantity,
            user_id=user.id,
        )

    await db.flush()
    await log_history_async(
        db,
        item,
        history_action,
        {
            'from': str(old_storage_id),
            'to': str(move_data.to_location_id),
            'notes': move_data.notes,
            **(history_changes or {}),
        },
        user_id=user.id,
        source_document_id=source_document_id,
    )
    # The caller's ``history_changes`` already says why the move happened and
    # what it came from — the document's number among it. The journal row
    # took only the note, so a move a document executed read as a hand move
    # and answered nothing about which document the goods followed.
    audit_extras = dict(history_changes or {})
    audit_reason = audit_extras.pop('reason', None)
    if source_document_id is not None:
        audit_extras['source_document_id'] = str(source_document_id)
    if move_data.notes:
        audit_extras['notes'] = move_data.notes
    await log_action_async(
        db,
        organization_id=item.organization_id,
        user_id=user.id,
        action=AuditAction.MOVE,
        target_type=AuditTargetType.ITEM,
        target_id=item.id,
        snapshot={
            'name': item.name,
            'before': {'location': await _location_name_async(db, old_storage_id)},
            'after': {'location': target_storage.name},
        },
        reason=audit_reason,
        meta_data=audit_extras or None,
    )
    await event_bus.emit_transactional(
        db,
        SystemEvent.ITEM_UPDATED,
        TenantEventPayload.model_validate(
            {
                'organization_id': str(user.organization_id),
                'item': item,
                'changes': {'storage_location_id': str(item.storage_location_id)},
                'user_id': str(user.id),
            }
        ),
    )
    await event_bus.emit_transactional(
        db,
        SystemEvent.ITEM_MOVED,
        TenantEventPayload.model_validate(
            {
                'organization_id': str(user.organization_id),
                'item': item,
                'changes': {
                    'from_storage_id': str(old_storage_id),
                    'to_storage_id': str(move_data.to_location_id),
                },
                'user_id': str(user.id),
            }
        ),
    )
    await db.refresh(item, ['category'])
    return item


async def consume_item(
    db: AsyncSession,
    item: Item,
    consume_data: ItemConsumeRequest,
    user: UserContextDTO,
    source_document_id: UUID | None = None,
) -> Item:
    return await _reduce_quantity(
        db,
        item,
        consume_data.quantity,
        user,
        virtual_usage=LocationUsage.CUSTOMER,
        action=ItemAction.USED,
        event=SystemEvent.ITEM_USED,
        source_document_id=source_document_id,
        reason=consume_data.reason,
        notes=consume_data.notes,
    )


async def discard_item(
    db: AsyncSession,
    item: Item,
    discard_data: ItemDiscardRequest,
    user: UserContextDTO,
    source_document_id: UUID | None = None,
) -> Item:
    return await _reduce_quantity(
        db,
        item,
        discard_data.quantity,
        user,
        virtual_usage=LocationUsage.INVENTORY,
        action=ItemAction.DISPOSED,
        event=SystemEvent.ITEM_DISPOSED,
        source_document_id=source_document_id,
        reason=discard_data.reason,
        notes=discard_data.notes,
    )
