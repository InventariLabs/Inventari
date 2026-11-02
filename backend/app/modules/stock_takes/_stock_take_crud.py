"""CRUD and query helpers for stock take operations.

Extracted from stock_take_service.py to keep each file under the 400 LOC
quality gate. These helpers are thin wrappers over the DB session used by
router handlers; they do not touch Core tables directly (only module-local
StockTake/StockTakeItem models and CoreAPI for item lookups).
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.contracts import (
    AuditAction,
    AuditTargetType,
    ItemCreateDTO,
    ItemDTO,
    UserContextDTO,
)
from app.core.db_utils import acquire_advisory_lock, escape_ilike, paginate_async
from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    ServiceRejectionError,
)
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message

from .models import (
    StockTake,
    StockTakeClosedLocation,
    StockTakeCount,
    StockTakeItem,
    StockTakeStatus,
)
from .schemas import (
    COUNTED_QUANTITY_MAX,
    ClosedLocation,
    ShelfClosed,
    StockTakeItemCountUpdate,
    StockTakeStatusUpdate,
    StockTakeUpdate,
)
from .storage_lookup_service import get_storage_tree


class _Unset:
    """The absence of a key, carried into the service as a value.

    A count payload sends only what the caller meant to change, so by the
    time the service holds the DTO the payload's key set is the only witness
    of that intent. ``None`` cannot stand for both "clear it" and "you did not
    send it" — a blanket ``if value is not None`` erases the first (AGENTS.md
    §2b). A key the payload did not send arrives as ``UNSET`` and never
    reaches the column.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return 'UNSET'


UNSET: Final = _Unset()


def sent_or_unset(dto: Any, field: str) -> Any:
    """*dto*'s ``field`` when the payload carried the key, ``UNSET`` when it
    did not — the one place presence is read, so no caller re-filters."""
    return getattr(dto, field) if field in dto.model_fields_set else UNSET


def record_counting_pass(
    stock_take_item: StockTakeItem,
    quantity: Decimal | None,
    user_id: UUID | None,
) -> None:
    """Keep this pass over the row, without losing the last one.

    A new pass is a deliberate second look: the row was sent back to be
    counted again, or nobody had counted it yet. Saving the same row twice in
    a row is somebody fixing a typed number, not a second opinion, so it
    corrects the pass it belongs to — otherwise "counted twice, and they
    agreed" would mean nothing, being true of every row anybody double-tapped.
    """
    if quantity is None:
        return
    passes = list(stock_take_item.counts)
    if stock_take_item.recount_requested or not passes:
        stock_take_item.counts.append(
            StockTakeCount(
                sequence=len(passes) + 1,
                quantity=quantity,
                counted_by=user_id,
            )
        )
        stock_take_item.recount_requested = False
        return
    latest = passes[-1]
    latest.quantity = quantity
    latest.counted_by = user_id
    latest.counted_at = datetime.now(UTC)


def apply_item_count(
    stock_take_item: StockTakeItem,
    counted_quantity: Decimal | None,
    location_in_storage: str | None | _Unset = UNSET,
    notes: str | None | _Unset = UNSET,
    discrepancy_reason: str | None | _Unset = UNSET,
    tolerance_percent: Decimal | None = None,
    discrepancy_reason_code: str | None | _Unset = UNSET,
    assignee_id: UUID | None | _Unset = UNSET,
    lot_id: UUID | None | _Unset = UNSET,
) -> None:
    """Update counted quantity and derive discrepancy flag. Does NOT commit.

    When tolerance_percent is set, differences within that percentage of
    system_quantity are not flagged as discrepancies.

    The ceiling does not stand here: this setter is not every door — the
    surplus row writes the column without it — so the refusal lives on the
    three writers that own the column (``count_item_and_commit``, its bulk
    twin, ``add_surplus_item``), every caller's step to the write.
    """
    # The counted quantity is required of every count payload; the rest are
    # written only when the payload carried them. An absent key is not a
    # decision — the location badge, the note and the discrepancy reason the
    # snapshot put there must survive a save that said nothing about them.
    stock_take_item.counted_quantity = counted_quantity
    if not isinstance(location_in_storage, _Unset):
        stock_take_item.location_in_storage = location_in_storage
    if not isinstance(notes, _Unset):
        stock_take_item.notes = notes
    if not isinstance(discrepancy_reason, _Unset):
        stock_take_item.discrepancy_reason = discrepancy_reason
    if not isinstance(discrepancy_reason_code, _Unset):
        stock_take_item.discrepancy_reason_code = discrepancy_reason_code
    if not isinstance(assignee_id, _Unset):
        stock_take_item.assignee_id = assignee_id
    if not isinstance(lot_id, _Unset):
        stock_take_item.lot_id = lot_id

    if stock_take_item.system_quantity is not None and counted_quantity is not None:
        diff = abs(counted_quantity - stock_take_item.system_quantity)
        if tolerance_percent is not None and stock_take_item.system_quantity != 0:
            threshold = abs(stock_take_item.system_quantity) * tolerance_percent / 100
            stock_take_item.is_discrepancy = 1 if diff > threshold else 0
        else:
            stock_take_item.is_discrepancy = 1 if diff > 0 else 0
        # Counted away from where its record stands: a difference of place,
        # whatever the quantity says.
        if stock_take_item.expected_location_id is not None:
            stock_take_item.is_discrepancy = 1


async def get_stock_take_item_or_404(
    db: AsyncSession,
    stock_take_id: UUID,
    item_id: UUID,
    org_id: UUID | None = None,
) -> StockTakeItem:
    """Fetch a specific StockTakeItem or raise 404.

    When *org_id* is provided, the result is additionally scoped to the
    given organisation via a join on StockTake.
    """
    lang = get_current_lang()
    stmt = (
        select(StockTakeItem)
        .join(StockTake, StockTakeItem.stock_take_id == StockTake.id)
        .where(
            StockTakeItem.id == item_id,
            StockTakeItem.stock_take_id == stock_take_id,
        )
    )
    if org_id is not None:
        stmt = stmt.where(StockTake.organization_id == org_id)
    result = await db.execute(stmt)
    item = result.scalars().first()
    if not item:
        raise NotFoundException('stock_take_item', lang)
    return item


async def list_stock_takes_filtered(
    db: AsyncSession,
    org_id: UUID,
    storage_location_id: UUID | None,
    status_filter: StockTakeStatus | None,
    offset: int,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    """Return paginated stock takes with optional filters. Returns (items, total).

    Each dict contains all StockTake columns plus items_count,
    counted_items_count and discrepancies_count computed via a single
    grouped aggregate over StockTakeItem (page-wide, keyed by stock take id)
    so that no lazy-loaded relationship is accessed in async context.
    """
    conditions = [StockTake.organization_id == org_id]
    if storage_location_id:
        conditions.append(StockTake.storage_location_id == storage_location_id)
    if status_filter:
        conditions.append(StockTake.status == status_filter)

    stmt = (
        select(StockTake)
        .options(
            selectinload(StockTake.storage_location),
            # Loaded with the page, not per row: the list is how somebody
            # returns to their own count, and a card that names only the date
            # cannot say whose count it is.
            selectinload(StockTake.user),
        )
        .where(*conditions)
        .order_by(StockTake.created_at.desc())
    )
    stock_takes, total = await paginate_async(db, stmt, limit=limit, offset=offset)

    counts: dict[UUID, tuple[int, int, int]] = {}
    if stock_takes:
        agg_rows = await db.execute(
            select(
                StockTakeItem.stock_take_id,
                func.count(StockTakeItem.id),
                func.count(StockTakeItem.counted_quantity),
                func.sum(case((StockTakeItem.is_discrepancy == 1, 1), else_=0)),
            )
            .where(StockTakeItem.stock_take_id.in_([st.id for st in stock_takes]))
            .group_by(StockTakeItem.stock_take_id)
        )
        counts = {
            row[0]: (row[1] or 0, row[2] or 0, row[3] or 0) for row in agg_rows.all()
        }

    rows: list[dict[str, Any]] = []
    for st in stock_takes:
        d: dict[str, Any] = {c.key: getattr(st, c.key) for c in st.__table__.columns}
        d['items_count'], d['counted_items_count'], d['discrepancies_count'] = (
            counts.get(st.id, (0, 0, 0))
        )
        # the list row must answer "where" and "how far along" —
        # the storage relation is already loaded via selectinload above. The
        # columns are read by their own names; the row speaks the API's.
        d['location_id'] = d.pop('storage_location_id')
        d['location_name'] = st.storage_location.name if st.storage_location else None
        d['started_by_name'] = st.user.full_name or st.user.email if st.user else None
        d['progress_percent'] = (
            d['counted_items_count'] / d['items_count'] * 100
            if d['items_count']
            else 0.0
        )
        rows.append(d)
    return rows, total


async def get_stock_take_items_simple(
    db: AsyncSession, stock_take_id: UUID
) -> list[StockTakeItem]:
    """Return all items for a stock take ordered by item name (no filters)."""
    result = await db.execute(
        select(StockTakeItem)
        .where(StockTakeItem.stock_take_id == stock_take_id)
        .order_by(StockTakeItem.item_name.asc())
    )
    return list(result.scalars().all())


async def get_stock_take_items_filtered(
    db: AsyncSession,
    stock_take_id: UUID,
    include_counted: bool | None,
    include_discrepancies: bool | None,
    search: str | None,
    *,
    limit: int,
    offset: int = 0,
) -> tuple[list[StockTakeItem], int]:
    """Return one page of a stock take's items, with the filtered total."""
    conditions = [StockTakeItem.stock_take_id == stock_take_id]
    if include_counted is True:
        conditions.append(StockTakeItem.counted_quantity.isnot(None))
    elif include_counted is False:
        conditions.append(StockTakeItem.counted_quantity.is_(None))
    if include_discrepancies is True:
        conditions.append(StockTakeItem.is_discrepancy == 1)
    if search:
        conditions.append(StockTakeItem.item_name.ilike(f'%{escape_ilike(search)}%'))

    return await paginate_async(
        db,
        select(StockTakeItem)
        .where(*conditions)
        .order_by(StockTakeItem.item_name.asc(), StockTakeItem.id),
        limit=limit,
        offset=offset,
    )


# The pair this writer's journal keys come from: `update_stock_take_fields`
# logs the `fields` list cut from the update payload, so every key it can
# write is a field the schema and the model share. The snapshot-key exporter
# reads this declaration (backend/scripts/export_audit_snapshot_keys.py).
AUDIT_PAYLOAD_SCHEMA = ('StockTakeUpdate', 'StockTake')


async def update_stock_take_fields(
    db: AsyncSession,
    stock_take: StockTake,
    data: StockTakeUpdate,
    user_id: UUID | None = None,
) -> StockTake:
    """Apply update fields, commit and refresh."""
    changed = sorted(data.model_dump(exclude_unset=True))
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(stock_take, field, value)
    await core_api.audit_log.log_action_async(
        db,
        organization_id=stock_take.organization_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.STOCK_TAKE,
        target_id=stock_take.id,
        snapshot={
            'name': stock_take.name,
            'fields': changed,
        },
    )
    await db.flush()
    await db.refresh(stock_take)
    return stock_take


async def update_stock_take_status_service(
    db: AsyncSession,
    stock_take: StockTake,
    status_update: StockTakeStatusUpdate,
    user_id: UUID | None = None,
) -> StockTake:
    """Validate status transition, apply and persist.

    Closing is deliberately absent from the table. Finalisation is what
    actually ends a count -- it locks the row, refuses while items are
    still uncounted, checks the inventory period and posts every counted
    difference back into stock. Reaching COMPLETED from here would set the
    field and do none of that, leaving a count closed over uncounted rows
    with no adjustment written. So this endpoint starts and abandons a
    count; ending one goes through finalisation.
    """
    valid_transitions: dict[StockTakeStatus, list[StockTakeStatus]] = {
        StockTakeStatus.DRAFT: [StockTakeStatus.IN_PROGRESS, StockTakeStatus.CANCELLED],
        StockTakeStatus.IN_PROGRESS: [StockTakeStatus.CANCELLED],
        StockTakeStatus.COMPLETED: [],
        StockTakeStatus.CANCELLED: [],
    }
    if status_update.status == StockTakeStatus.COMPLETED:
        raise ServiceRejectionError('stock_take_close_requires_finalize')
    if status_update.status not in valid_transitions.get(stock_take.status, []):
        raise ServiceRejectionError(
            'stock_take_status_unchangeable',
            current=stock_take.status.value,
            new=status_update.status.value,
        )
    old_status = stock_take.status
    stock_take.status = status_update.status
    if status_update.status == StockTakeStatus.CANCELLED:
        stock_take.completed_at = datetime.now(UTC)
    await core_api.audit_log.log_action_async(
        db,
        organization_id=stock_take.organization_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.STOCK_TAKE,
        target_id=stock_take.id,
        snapshot={
            'name': stock_take.name,
            'old_status': old_status.value,
            'new_status': stock_take.status.value,
        },
    )
    await db.flush()
    await db.refresh(stock_take)
    return stock_take


async def delete_stock_take_entity(
    db: AsyncSession, stock_take: StockTake, user_id: UUID | None = None
) -> None:
    """Soft-delete stock take — preserves audit trail."""
    stock_take.status = StockTakeStatus.CANCELLED
    stock_take.deleted_at = datetime.now(UTC)
    # The row stays, but "who removed this count" still has an answer: the
    # soft delete is the removal the list stops showing.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=stock_take.organization_id,
        user_id=user_id,
        action=AuditAction.SOFT_DELETE,
        target_type=AuditTargetType.STOCK_TAKE,
        target_id=stock_take.id,
        snapshot={
            'name': stock_take.name,
            'status': stock_take.status.value,
        },
    )
    await db.flush()


async def refuse_a_count_the_unit_cannot_hold(
    db: AsyncSession,
    stock_take_item: StockTakeItem,
    quantity: Decimal | None,
    organization_id: UUID,
) -> None:
    """A shelf counted in whole pieces is not counted in halves.

    Every unit says the smallest step it is counted in, and a piece says one.
    Nothing asked that question of a count, so "2.5 pieces" was recorded, and
    then written to the shelf by the finalization as whatever the column
    rounded it to.

    Rows with no unit are left alone: a product that predates units is a real
    and blameless case, and the rule cannot be stricter than the data.
    """
    if quantity is None or stock_take_item.uom_id is None:
        return
    from app.core.public_api import core_api

    await core_api.uoms.validate_quantity_precision_async(
        db, stock_take_item.uom_id, quantity, organization_id
    )


def refuse_a_count_the_column_cannot_hold(quantity: Decimal | None) -> None:
    """A count past what the column stores is refused with the bound named.

    The stock-take columns are numeric(10, 3) — narrower than the items
    column whose QUANTITY_MAX does not fit here — and this is the writer
    every door to them passes: the counting PATCH and its bulk twin, the
    surplus row, and any caller that builds a count in code. A value past
    the largest storable one is refused before anything is written, where
    the driver would have answered with the overflow.
    """
    if quantity is None or quantity <= COUNTED_QUANTITY_MAX:
        return
    raise ServiceRejectionError(
        'counted_quantity_above_ceiling',
        quantity=quantity,
        ceiling=COUNTED_QUANTITY_MAX,
    )


async def count_item_and_commit(
    db: AsyncSession,
    stock_take_item: StockTakeItem,
    count_data: StockTakeItemCountUpdate,
    tolerance_percent: Decimal | None = None,
    user_id: UUID | None = None,
    *,
    organization_id: UUID,
    stock_take_name: str | None = None,
) -> StockTakeItem:
    """Apply counted quantity to item, persist and refresh."""
    refuse_a_count_the_column_cannot_hold(count_data.counted_quantity)
    await refuse_a_count_the_unit_cannot_hold(
        db, stock_take_item, count_data.counted_quantity, organization_id
    )
    record_counting_pass(stock_take_item, count_data.counted_quantity, user_id)
    # The number the row already carried is read before the count overwrites
    # it — the entry exists to show what the count replaced.
    old_counted = stock_take_item.counted_quantity
    apply_item_count(
        stock_take_item,
        count_data.counted_quantity,
        location_in_storage=sent_or_unset(count_data, 'shelf_location'),
        notes=sent_or_unset(count_data, 'notes'),
        discrepancy_reason=sent_or_unset(count_data, 'discrepancy_reason'),
        tolerance_percent=tolerance_percent,
        discrepancy_reason_code=sent_or_unset(count_data, 'discrepancy_reason_code'),
        assignee_id=sent_or_unset(count_data, 'assignee_id'),
        lot_id=sent_or_unset(count_data, 'lot_id'),
    )
    # The recorded number is the count's own business before anything posts:
    # one entry per saved row, with the number it replaced.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.STOCK_TAKE,
        target_id=stock_take_item.stock_take_id,
        snapshot={
            'name': stock_take_name,
            'item_name': stock_take_item.item_name,
            'item_id': str(stock_take_item.item_id)
            if stock_take_item.item_id
            else None,
            'old_counted_quantity': str(old_counted)
            if old_counted is not None
            else None,
            'counted_quantity': (
                str(count_data.counted_quantity)
                if count_data.counted_quantity is not None
                else None
            ),
        },
    )
    await db.flush()
    await db.refresh(stock_take_item)
    return stock_take_item


async def bulk_count_items_and_commit(
    db: AsyncSession,
    stock_take_id: UUID,
    items_update: list[StockTakeItemCountUpdate],
    tolerance_percent: Decimal | None = None,
    user_id: UUID | None = None,
    *,
    organization_id: UUID,
    stock_take_name: str | None = None,
) -> list[StockTakeItem]:
    """Apply bulk counted quantities for a stock take.

    Maps updates by StockTakeItem.id (via item_id field) rather than array index
    to prevent data corruption when DB order differs from payload order.
    """
    result = await db.execute(
        select(StockTakeItem)
        .where(StockTakeItem.stock_take_id == stock_take_id)
        .order_by(StockTakeItem.id)
    )
    by_id = {sti.id: sti for sti in result.scalars().all()}
    updated: list[StockTakeItem] = []
    for update_data in items_update:
        if update_data.item_id is None:
            raise ServiceRejectionError('stock_take_bulk_item_id_required')
        target = by_id.get(update_data.item_id)
        if target is None:
            raise ServiceRejectionError('stock_take_item_not_found')
        refuse_a_count_the_column_cannot_hold(update_data.counted_quantity)
        await refuse_a_count_the_unit_cannot_hold(
            db, target, update_data.counted_quantity, organization_id
        )
        record_counting_pass(target, update_data.counted_quantity, user_id)
        apply_item_count(
            target,
            update_data.counted_quantity,
            location_in_storage=sent_or_unset(update_data, 'shelf_location'),
            notes=sent_or_unset(update_data, 'notes'),
            discrepancy_reason=sent_or_unset(update_data, 'discrepancy_reason'),
            tolerance_percent=tolerance_percent,
            discrepancy_reason_code=sent_or_unset(
                update_data, 'discrepancy_reason_code'
            ),
            assignee_id=sent_or_unset(update_data, 'assignee_id'),
            lot_id=sent_or_unset(update_data, 'lot_id'),
        )
        updated.append(target)
    await core_api.audit_log.log_action_async(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.STOCK_TAKE,
        target_id=stock_take_id,
        snapshot={
            'name': stock_take_name,
            'counted_rows': len(updated),
            'bulk': True,
        },
    )
    await db.flush()
    return updated


async def close_location(
    db: AsyncSession,
    stock_take: StockTake,
    location_id: UUID,
    user_id: UUID,
) -> ShelfClosed:
    """The counter is done with *location_id*: what nobody counted there is none.

    Every row of the shelf still waiting for a number is counted as zero, by
    whoever closed it, the way a typed 0 would be — so the report shows it
    as a shortage and closing the count posts it. A shelf with nothing on it
    afterwards (no row, or every row at none) is confirmed as empty. Either
    way the closure is kept, so the report can say which shelves were looked
    at and by whom. Closing again restates it: a shelf counted further after
    being closed is closed by the later look.

    Only the shelf's own rows: one below it is a shelf of its own, closed on
    its own.
    """
    lang = get_current_lang()
    _tree_ids, _family_ids, paths = await get_storage_tree(
        db, stock_take.organization_id, stock_take.storage_location_id
    )
    if location_id not in paths:
        raise ConflictException(
            code='STOCK_TAKE_SHELF_OUTSIDE_LOCATION',
            message=get_error_message(
                'stock_take_shelf_outside_location',
                lang,
                location=paths.get(stock_take.storage_location_id, ''),
            ),
        )
    await acquire_advisory_lock(db, f'stock_take:close:{stock_take.id}:{location_id}')
    rows = (
        (
            await db.execute(
                select(StockTakeItem).where(
                    StockTakeItem.stock_take_id == stock_take.id,
                    StockTakeItem.storage_location_id == location_id,
                )
            )
        )
        .scalars()
        .all()
    )
    counted_as_zero = 0
    for row in rows:
        if row.counted_quantity is not None:
            continue
        record_counting_pass(row, Decimal('0'), user_id)
        apply_item_count(
            row, Decimal('0'), tolerance_percent=stock_take.tolerance_percent
        )
        counted_as_zero += 1

    closure = (
        (
            await db.execute(
                select(StockTakeClosedLocation).where(
                    StockTakeClosedLocation.stock_take_id == stock_take.id,
                    StockTakeClosedLocation.storage_location_id == location_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if closure is None:
        closure = StockTakeClosedLocation(
            stock_take_id=stock_take.id, storage_location_id=location_id
        )
        db.add(closure)
    closure.path = paths[location_id]
    closure.empty = all(row.counted_quantity == 0 for row in rows)
    closure.closed_by = user_id
    closure.closed_at = datetime.now(UTC)
    # A shelf found empty leaves no number behind; this entry is the trace
    # that somebody looked, and how many rows they counted as none.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=stock_take.organization_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.STOCK_TAKE,
        target_id=stock_take.id,
        snapshot={
            'name': stock_take.name,
            'location': closure.path,
            'counted_rows': counted_as_zero,
            'closed': True,
        },
    )
    await db.flush()
    await db.refresh(closure)
    return ShelfClosed(
        **ClosedLocation.model_validate(closure).model_dump(),
        counted_as_zero=counted_as_zero,
    )


async def list_closed_locations(
    db: AsyncSession, stock_take_id: UUID
) -> list[ClosedLocation]:
    """The shelves closed in a count, by path, with who closed them."""
    result = await db.execute(
        select(StockTakeClosedLocation)
        .where(StockTakeClosedLocation.stock_take_id == stock_take_id)
        .order_by(StockTakeClosedLocation.path)
    )
    return [ClosedLocation.model_validate(row) for row in result.scalars().all()]


async def add_surplus_item(
    db: AsyncSession,
    stock_take_id: UUID,
    org_id: UUID,
    item_id: UUID,
    counted_quantity: Decimal,
    notes: str | None = None,
    user_id: UUID | None = None,
    storage_location_id: UUID | None = None,
) -> StockTakeItem:
    """Create a surplus StockTakeItem for an item not in the original stock take list.

    "Surplus" means the snapshot did not expect it here, not that the system
    holds none of it. The row used to be written with ``system_quantity=0``,
    and finalising writes the count as an absolute quantity — so an item the
    system holds seven of, counted as three, ended the count at three with the
    missing four recorded nowhere. The growth cap missed it too: it skips rows
    whose system quantity is falsy.

    The item must be stored inside the tree this count covers. It was looked
    up across the whole organization, so the thing being "found" could be on a
    different shelf entirely — and counting it here overwrote the quantity it
    has there.

    *storage_location_id* is the shelf the counter found the goods on. When
    the record stands on another shelf of the tree, the find is recorded where
    it was made — see ``_the_record_on_the_shelf``.
    """
    # A count typed against a surplus row is a count like any other: asked
    # against the column's own ceiling, so a number the row cannot store is
    # refused here and not met as the driver's overflow on the INSERT.
    refuse_a_count_the_column_cannot_hold(counted_quantity)
    await acquire_advisory_lock(db, f'stock_take:surplus:{stock_take_id}:{item_id}')
    lang = get_current_lang()

    # Verify the item exists in the org
    item = await core_api.items.get_async(db, org_id, item_id)
    if item is None:
        raise NotFoundException('item', lang)
    # A count typed against a surplus row is a count like any other: asked
    # against the unit's smallest step, so that "2.5 pieces" is refused here
    # and not written to the shelf by the finalization.
    if item.uom_id is not None:
        await core_api.uoms.validate_quantity_precision_async(
            db, item.uom_id, counted_quantity, org_id
        )

    stock_take = await db.get(StockTake, stock_take_id)
    if stock_take is None or stock_take.organization_id != org_id:
        raise NotFoundException('stock_take', lang)

    tree_ids, _family_ids, paths = await get_storage_tree(
        db, org_id, stock_take.storage_location_id
    )
    if item.location_id not in set(tree_ids):
        raise ConflictException(
            code='STOCK_TAKE_ITEM_OUTSIDE_LOCATION',
            message=get_error_message('stock_take_item_outside_location', lang),
        )
    if storage_location_id is not None and storage_location_id not in paths:
        raise ConflictException(
            code='STOCK_TAKE_SHELF_OUTSIDE_LOCATION',
            message=get_error_message(
                'stock_take_shelf_outside_location',
                lang,
                location=paths[stock_take.storage_location_id],
            ),
        )
    # Where the find is counted: the record's own shelf, unless the counter
    # stands at another. Goods with a card are counted onto a record of them
    # on that shelf; a unit that owns its identity has no second record to be
    # counted onto, so its row is counted where the counter stands.
    counted_on = item.location_id
    owns_its_identity = item.template_id is None or bool(item.serial_number)
    if storage_location_id is not None and user_id is not None:
        if owns_its_identity:
            counted_on = storage_location_id
        else:
            item = await _the_record_on_the_shelf(
                db, stock_take, item, storage_location_id, user_id, paths
            )
            counted_on = item.location_id

    # Check for duplicate
    existing = (
        (
            await db.execute(
                select(StockTakeItem).where(
                    StockTakeItem.stock_take_id == stock_take_id,
                    StockTakeItem.item_id == item.id,
                )
            )
        )
        .scalars()
        .first()
    )
    if (
        existing is not None
        and owns_its_identity
        and counted_on is not None
        and existing.storage_location_id != counted_on
    ):
        return await _the_row_counted_where_found(
            db, stock_take, existing, item, counted_on, counted_quantity, paths, user_id
        )
    if existing is not None:
        # Named, so the counting screen can count the row it already has: a
        # second find of the same goods on a shelf is one more of them there.
        raise ConflictException(
            code='STOCK_TAKE_ITEM_ALREADY_EXISTS',
            message=get_error_message('stock_take_item_already_exists', lang),
            details={'stock_take_item_id': str(existing.id), 'item_id': str(item.id)},
        )

    surplus = StockTakeItem(
        stock_take_id=stock_take_id,
        item_id=item.id,
        item_name=item.name,
        item_brand=getattr(item, 'brand', None),
        uom_id=getattr(item, 'uom_id', None),
        system_quantity=item.quantity or Decimal('0'),
        notes=notes,
    )
    _count_on(surplus, item, counted_on, counted_quantity, paths)
    db.add(surplus)
    # An item the snapshot did not expect is exactly the finding a count
    # exists to produce: the log keeps who recorded it and how much.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.STOCK_TAKE,
        target_id=stock_take_id,
        snapshot={
            'name': stock_take.name,
            'item_name': surplus.item_name,
            'item_id': str(item.id),
            'counted_quantity': str(counted_quantity),
            'system_quantity': str(surplus.system_quantity),
            'surplus': True,
        },
    )
    await db.flush()
    await db.refresh(surplus)
    return surplus


def _count_on(
    row: StockTakeItem,
    record: ItemDTO,
    shelf_id: UUID | None,
    counted_quantity: Decimal,
    paths: dict[UUID, str],
) -> None:
    """Count *row* on *shelf_id*, remembering where its record stands if elsewhere.

    A unit counted away from its record's shelf is a difference of place
    even when the quantity agrees: it was not where the records said, and
    the counter says why, the way they do for any difference. Counted back
    on its own shelf, it is an ordinary row again.
    """
    at_home = shelf_id == record.location_id
    row.storage_location_id = shelf_id
    row.expected_location_id = None if at_home else record.location_id
    row.location_in_storage = (
        record.shelf_location
        if at_home and record.shelf_location
        else paths.get(shelf_id)
        if shelf_id is not None
        else None
    )
    row.counted_quantity = counted_quantity
    row.is_discrepancy = (
        1 if not at_home or counted_quantity != row.system_quantity else 0
    )


async def _the_row_counted_where_found(
    db: AsyncSession,
    stock_take: StockTake,
    row: StockTakeItem,
    record: ItemDTO,
    shelf_id: UUID,
    counted_quantity: Decimal,
    paths: dict[UUID, str],
    user_id: UUID | None,
) -> StockTakeItem:
    """The row of a unit that owns its identity, counted on the shelf it was found on.

    A serial number is unique and goods with no card have no card to open a
    second record from, so such a unit cannot be a surplus record on one
    shelf beside a shortage on another. Its one row moves instead: it counts
    the shelf the unit was found on and keeps the shelf its record stands on.
    Closing the count moves the record, and the report shows the shortage on
    the old shelf beside the surplus on the new one.
    """
    _count_on(row, record, shelf_id, counted_quantity, paths)
    await core_api.audit_log.log_action_async(
        db,
        organization_id=stock_take.organization_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.STOCK_TAKE,
        target_id=stock_take.id,
        snapshot={
            'name': stock_take.name,
            'item_name': row.item_name,
            'item_id': str(record.id),
            'counted_quantity': str(counted_quantity),
            # Where the unit was counted: the journal reads the path.
            'location': paths.get(shelf_id),
        },
    )
    await db.flush()
    await db.refresh(row)
    return row


async def _the_record_on_the_shelf(
    db: AsyncSession,
    stock_take: StockTake,
    record: ItemDTO,
    shelf_id: UUID,
    user_id: UUID,
    paths: dict[UUID, str],
) -> ItemDTO:
    """The record of *record*'s goods standing on the shelf they were found on.

    Counting is by location: what a counter finds on a shelf is a statement
    about that shelf. Goods the snapshot expected on another shelf of the
    tree are therefore not counted onto the record over there — that would
    move them on paper while the shelf they were expected on still shows them
    — but onto a record of the same goods on the shelf where they stand, the
    way a receipt asks whether the product is already on a shelf before it
    opens a record there. None standing there yet, one is opened holding
    nothing: the count's posting raises it to what was counted, as a surplus
    on this shelf, and the row on the other shelf answers for the shortage
    when that shelf is counted.

    A record with no card, or with a serial number, owns its identity and
    never comes here: see ``_the_row_counted_where_found``.
    """
    if record.location_id == shelf_id:
        return record
    await acquire_advisory_lock(
        db, f'stock_take:shelf:{stock_take.id}:{shelf_id}:{record.template_id}'
    )
    standing = await core_api.items.find_stock_row_async(
        db,
        stock_take.organization_id,
        template_id=record.template_id,
        expiry_date=record.expiry_date,
        storage_location_id=shelf_id,
        lot_id=record.lot_id,
        owner_id=record.owner_id,
    )
    if standing is not None:
        return standing
    history = {'reason': 'stock_take_adjustment', 'stock_take_id': str(stock_take.id)}
    return await core_api.items.create_async(
        db,
        stock_take.organization_id,
        ItemCreateDTO(
            # The same goods as the record they were expected as, without
            # what names that record alone (its barcode, its shelf code).
            name=record.template_name or record.name,
            template_id=record.template_id,
            category_id=record.category_id,
            location_id=shelf_id,
            quantity=Decimal('0'),
            uom_id=record.uom_id,
            brand=record.brand,
            expiry_date=record.expiry_date,
            purchase_price=record.purchase_price,
            currency=record.currency,
            image_url=record.image_url,
            lot_id=record.lot_id,
            owner_id=record.owner_id,
        ),
        UserContextDTO(id=user_id, organization_id=stock_take.organization_id),
        history_changes=history,
        # Nothing to post: the record holds nothing until the count closes.
        post_the_change=False,
    )
