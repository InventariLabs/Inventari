"""Bulk item update — multi-item field updates with per-row savepoints.

Extracted from bulk_service.py to keep the aggregator under the 400-LOC
module guideline.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_invalidate_org_queries
from app.core.contracts import AuditAction, AuditTargetType, UserContextDTO
from app.core.db_utils import in_ids
from app.core.exceptions import ServiceRejectionError
from app.models.item import Item
from app.models.item_history import ItemAction
from app.models.storage_location import StorageLocation
from app.schemas._common import keyed_by_column
from app.schemas.item import ItemBulkUpdate, _take_unit_confirmation
from app.services._stock_quant_ops import lock_stock_async
from app.services.audit_service import log_action_async

from ._date_meta import LEGACY_DATE_FIELDS, legacy_date_in_meta
from ._stock_quant import apply_quantity_change_async, lock_record_stock_async
from ._stock_relocation import carry_record_stock_async, shelf_change_keys
from ._unit_choice import log_unit_chosen_over_template_async
from ._update import (
    _apply_field_updates,
    _apply_meta_data,
    _capture_old_values,
    _changed_fields,
    _reference_names,
    _sync_template_fields,
    _validate_quantity_and_currency,
    keep_record_in_card_unit_async,
)
from .history import log_history_async


async def _get_storage_ids(
    db: AsyncSession, organization_id: UUID | None
) -> list[UUID]:
    if organization_id is None:
        return []
    result = await db.scalars(
        select(StorageLocation.id).where(
            StorageLocation.organization_id == organization_id
        )
    )
    return list(result.all())


async def _ensure_referenced_ids_are_own(
    db: AsyncSession, update_dict: dict, org_id: UUID | None
) -> None:
    """Refuse ids in the payload that belong to another organization.

    The batch reaches the same ``setattr`` as the single update, so it needs
    the same guards: a re-categorisation must not point at another
    organization's category, a relocation must not park fifty records on
    another organization's shelf — where the list and the detail fetch,
    both scoped by the locations the caller owns, would hand them over —
    and a unit change must not read another organization's unit definition.

    Checked once before the per-item savepoint loop: each id is one value for
    the whole batch, so either it suits every record or the request is
    incoherent, and callers expect all-or-nothing semantics.
    """
    if org_id is None:
        return

    from ._create import (
        _ensure_category_async,
        _ensure_storage_location_async,
        _ensure_uom_async,
    )

    if 'category_id' in update_dict:
        await _ensure_category_async(db, update_dict['category_id'], org_id)

    if 'storage_location_id' in update_dict:
        await _ensure_storage_location_async(
            db, update_dict['storage_location_id'], org_id
        )

    if update_dict.get('uom_id'):
        await _ensure_uom_async(db, update_dict['uom_id'], org_id)


async def _ensure_barcode_names_one_record_async(
    db: AsyncSession,
    update_dict: dict[str, Any],
    items: list[Item],
    org_id: UUID | None,
) -> None:
    """The single edit's barcode rule, stated for a whole batch.

    ``ItemUpdate`` carries ``barcode``, so the batch reached the same
    ``setattr`` as the single edit — and the unique index behind it — with
    no check of its own: a taken code answered a raw 500 where the very
    same collision on the edit path was a clean refusal. One code names one
    record, and a batch of more than one record asking for one code is
    self-contradictory whatever the database holds, so it is refused
    before anything is written. A batch of one is the single edit's own
    shape and runs the single edit's own check, so the two doors speak one
    sentence.
    """
    barcode = update_dict.get('barcode')
    if not barcode or not items:
        return
    if len(items) > 1:
        raise ServiceRejectionError(
            'barcode_names_one_record', count=len(items), barcode=barcode
        )
    if org_id is None:
        return

    from ._create import _ensure_barcode_unique_async

    await _ensure_barcode_unique_async(db, org_id, barcode, exclude_item_id=items[0].id)


async def _lock_the_batch_stock_async(
    db: AsyncSession, items: list[Item], update_dict: dict[str, Any]
) -> None:
    """Lock every group this batch writes, in one call, before the loop.

    The batch reaches the same writes as fifty single edits: a number per
    record and its movement, and the shelf a relocated record leaves and
    joins. Each record took its group when the loop got to it, so two
    batches crossing the same shelves each held what the other wanted and
    the database aborted one of them. The groups are collected first — the
    shelf every record stands on when its number moves, and the shelves
    each relocated record leaves and the one the batch joins — and locked
    in a single call: ``lock_stock_async`` orders them, so the batch queues
    with every other multi-group writer instead of closing a circle with it.

    Each record's number, grain and shelf are then read again under the
    lock. The records were read into the session before it, and another
    transaction's committed write is invisible to that snapshot: a delta
    measured from it is the number the batch saw before it waited, and a
    holding carried off it is the shelf the record has already left.
    Without the read again, two batches of one selection both posted the
    difference from the same old number — or carried the same holding off
    one shelf twice — and the record and the ledger parted. The read is per
    record, in ``id`` order, so batches meet on the records that have no
    card — no group, no anchor to queue on — in the same order too.
    """
    quantity_changed = 'quantity' in update_dict
    location_changed = 'storage_location_id' in update_dict
    keys: list[tuple[UUID, UUID]] = []
    if quantity_changed:
        keys += [
            (item.template_id, item.storage_location_id)
            for item in items
            if item.template_id is not None and item.storage_location_id is not None
        ]
    if location_changed:
        keys += shelf_change_keys(items, update_dict['storage_location_id'])
    if keys:
        await lock_stock_async(db, items[0].organization_id, keys=keys)
    if quantity_changed or location_changed:
        for item in sorted(items, key=lambda record: record.id):
            await lock_record_stock_async(db, item)


async def bulk_update_items(
    db: AsyncSession, bulk_data: ItemBulkUpdate, user: UserContextDTO
) -> int:
    user_storage_ids = await _get_storage_ids(db, user.organization_id)
    result = await db.execute(
        select(Item).where(
            Item.id.in_(bulk_data.item_ids),
            in_ids(Item.storage_location_id, user_storage_ids),
            Item.is_deleted.is_(False),
        )
    )
    items = list(result.scalars().all())

    update_dict = keyed_by_column(bulk_data.update_data.model_dump(exclude_unset=True))
    if 'metadata' in update_dict:
        update_dict['meta_data'] = update_dict.pop('metadata')
    # The confirmation has no column to land in. It is spent on the unit
    # guard below, as the single edit spends it; the batch used to set it on
    # the record, where ``hasattr`` dropped it, so a unit the single edit
    # takes on confirmation the batch refused whatever the caller said.
    confirmed_unit = _take_unit_confirmation(update_dict)

    if not update_dict:
        return 0

    await _ensure_referenced_ids_are_own(db, update_dict, user.organization_id)

    # The same barcode rule the single edit runs, once for the whole batch:
    # one code names one record, so a batch of many asking for one code is
    # refused as incoherent before the loop — the same fail-fast place the
    # category, location and unit gates take.
    await _ensure_barcode_names_one_record_async(
        db, update_dict, items, user.organization_id
    )

    # The rules the single update enforces before it touches anything: a
    # record holding stock does not get its unit swapped (the number on the
    # shelf did not change, so the label under it must not either), a
    # quantity has to fit the precision its unit allows, and a currency has
    # to be the organization's. The batch reached the same ``setattr`` past
    # all three, so the same edit was refused one at a time and accepted
    # fifty at a time.
    #
    # Before the loop, like the category check and the period gate above:
    # the payload is one value for the whole batch, so either it suits every
    # record or the request is incoherent — and nothing in the loop catches,
    # so a refusal halfway would answer 400 for one row after committing the
    # rows before it.
    template_units: dict[UUID, UUID | None] = {}
    for item in items:
        template_units[item.id] = await _validate_quantity_and_currency(
            db, item, update_dict, user, confirmed=confirmed_unit
        )

    quantity_changed = 'quantity' in update_dict
    location_changed = 'storage_location_id' in update_dict

    # When the bulk update touches quantity or location, block the
    # whole batch if the current period is closed — closed is decided on
    # the organization's day, not the server's. The check runs once
    # before the per-item savepoint loop — fail-fast beats partial
    # rejection because callers expect all-or-nothing semantics.
    if (quantity_changed or location_changed) and items:
        from app.core.public_api import core_api
        from app.services.analytics._common import org_today_async

        org_id: UUID | None = items[0].organization_id
        if org_id is not None:
            await core_api.periods.check_not_closed_async(
                db, org_id, await org_today_async(db, org_id)
            )

    if items and (location_changed or quantity_changed):
        await _lock_the_batch_stock_async(db, items, update_dict)

    updated_count = 0
    for item in items:
        # Wrap each item in a savepoint so a single bad row rolls back
        # only itself instead of poisoning the whole batch.
        async with db.begin_nested():
            await _update_one_async(
                db,
                item,
                dict(update_dict),
                user,
                confirmed_unit=confirmed_unit,
                template_uom_id=template_units[item.id],
            )
            updated_count += 1

    await db.flush()
    # log_action_async invalidates the analytics read-models per entry, but a
    # batch that matched nothing writes none of them — and the quantity path
    # below it can still have moved stock. Cheap and unconditional.
    if user.organization_id is not None:
        await cache_invalidate_org_queries(user.organization_id)
    return updated_count


async def _update_one_async(
    db: AsyncSession,
    item: Item,
    data: dict[str, Any],
    user: UserContextDTO,
    *,
    confirmed_unit: bool,
    template_uom_id: UUID | None,
) -> None:
    """One record of the batch, taken through the single edit's own steps.

    The batch used to ``setattr`` every field ``hasattr`` let through, and
    four fields of the schema are not the record's columns: the low-stock
    threshold (a read-only property, so the request ended in a 500), the
    unit weight, and a freeze date, which was dropped at 200. The single
    edit routes each of them by name, and the batch now calls the same
    helpers. They take the fields they route off *data*, which is this
    record's own copy of the payload.
    """
    dates_before = {
        field: legacy_date_in_meta(item.meta_data, field)
        for field in LEGACY_DATE_FIELDS
        if field in data
    }
    _apply_meta_data(item, data)
    chosen_uom_id = data.get('uom_id')
    entered_quantity = data.get('quantity')
    await keep_record_in_card_unit_async(db, item, data, template_uom_id)
    old_values = _capture_old_values(item, data)
    old_location, old_quantity = item.storage_location_id, item.quantity
    _apply_field_updates(item, data)
    # The stock follows the record to its new shelf — the same call the
    # single move and the single edit make, so fifty records moved at once
    # are the same operation as fifty moved one by one. It used to sit in the
    # ``elif`` of the quantity change below, so a batch that changed both put
    # the difference on the new shelf and never took anything off the old one.
    if 'storage_location_id' in data:
        await carry_record_stock_async(
            db,
            item,
            from_location_id=old_location,
            quantity=old_quantity,
            user_id=user.id,
        )
    if 'quantity' in data:
        await apply_quantity_change_async(
            db,
            item,
            item.quantity,
            old_quantity=old_values.get('quantity'),
            user_id=user.id,
        )
    if confirmed_unit:
        await log_unit_chosen_over_template_async(
            db,
            item,
            ItemAction.UPDATED,
            template_uom_id=template_uom_id,
            chosen_uom_id=chosen_uom_id,
            entered_quantity=entered_quantity,
            user_id=user.id,
        )
    template_changes = await _sync_template_fields(db, item, data, user)
    date_changes = {
        field: (before, legacy_date_in_meta(item.meta_data, field))
        for field, before in dates_before.items()
        if before != legacy_date_in_meta(item.meta_data, field)
    }
    changed = _changed_fields(old_values, data) | date_changes | template_changes
    if changed:
        await _trace_async(db, item, changed, old_values, data, user)


async def _trace_async(
    db: AsyncSession,
    item: Item,
    changed: dict[str, tuple[Any, Any]],
    old_values: dict[str, Any],
    data: dict[str, Any],
    user: UserContextDTO,
) -> None:
    """The record's history and the organization journal, naming what moved.

    Both used to be built from the payload, so a batch that posted a name
    the record already had wrote two rows whose sides agreed, and a field
    the record could not take was named as taken. They are built from what
    the record, its card and its dates took, and not written at all when
    that is nothing — the single edit skips its journal row the same way.
    """
    # The history keeps a record column in its own value, as the single
    # edit's does; what the record keeps elsewhere — the card's threshold, a
    # date in ``meta_data`` — has left *data* and reads as the change says.
    # Named as the single edit names them, on both sides of every pair: a
    # batch wrote the ids alone, so `Location: 405d91ba → 134990cc` was the
    # same symptom this naming was introduced to cure, on the same fields,
    # reached by the other button — and the card the batch writes for read
    # it too, not only the journal.
    old = {f: old_values[f] if f in data else was for f, (was, _) in changed.items()}
    new = {f: data[f] if f in data else now for f, (_, now) in changed.items()}
    before_names = await _reference_names(
        db, {f: old_values.get(f, changed[f][0]) for f in changed}
    )
    after_names = await _reference_names(
        db, {f: data.get(f, changed[f][1]) for f in changed}
    )
    await log_history_async(
        db,
        item,
        ItemAction.UPDATED,
        {
            'old': old | before_names,
            'new': new | after_names,
            'bulk': True,
        },
        user_id=user.id,
    )
    # And the organization journal, which used to be skipped here with a
    # comment saying so. Fifty items recategorised at once left the same
    # trace as nothing having happened, while the same edit made one at a
    # time was fully recorded — the journal is not supposed to depend on
    # which button was pressed. The `bulk` flag is what tells the reader it
    # was one batch.
    if user.organization_id is None:
        return
    await log_action_async(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.ITEM,
        target_id=item.id,
        snapshot={
            'name': item.name,
            # The audited values are the change pairs, not the record's raw
            # columns: a Decimal is not JSON, and the pair has already been
            # read for the log. The names ride the same sides the history got.
            'before': {f: was for f, (was, _) in changed.items()} | before_names,
            'after': {f: now for f, (_, now) in changed.items()} | after_names,
        },
        meta_data={'bulk': True},
    )


# The pair this module's journal keys come from: this writer builds both
# sides of its snapshot from the update payload, so every key it can write is
# a field the schema and the model share. The snapshot-key exporter reads
# this declaration (backend/scripts/export_audit_snapshot_keys.py); a writer
# of the same shape declares its own pair beside its own loop.
AUDIT_PAYLOAD_SCHEMA = ('ItemUpdate', 'Item')

# The payload fields the record keeps in ``meta_data``, which the journal
# names by the word the API reads them by. The card's fields a batch names
# (``min_quantity``, ``weight_value``) are declared by the card's own writer.
_AUDITED_LEGACY_DATES = ('freeze_date',)
