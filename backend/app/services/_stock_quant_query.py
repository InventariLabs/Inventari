"""Stock read operations: the lot and owner rules, the shelves, what picking plans from.

Read-only, kept apart from the write-side ``_stock_quant_ops`` so catalog
browse endpoints can depend on this lighter surface without pulling in the
draw and the movement pass. Everything here reads the records — directly or
through ``stock_quants_from_records`` — and the reservation rows; the quant
table is gone.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Row, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import PickGroupDTO, ShelfContentsDTO
from app.core.db_utils import in_ids
from app.core.exceptions import ServiceRejectionError
from app.models.stock_lot import (
    LotStatus,
    StockLot,
    effective_status_expression,
)
from app.services.stock_strategy import resolve_removal_strategy


def earliest_lot_date(*fallbacks: Any) -> Any:
    """The date FEFO orders a batch by.

    ``use_by_date`` (food safety) and ``expiry_date`` (quality) both count
    and the earlier one triggers first; a batch with only one of them is
    ordered by that one. *fallbacks* are the dates to read when the batch
    has none (a record's own date). Undated stock has none, and callers
    sort it last.
    """
    return func.coalesce(
        func.least(StockLot.use_by_date, StockLot.expiry_date),
        StockLot.use_by_date,
        StockLot.expiry_date,
        *fallbacks,
    )


def active_lot_predicate(lot_column: Any):
    """OR predicate: stock is consumable when it has no lot or an ACTIVE lot.

    Shared by the picking/strategy reads — quarantined/held/recalled
    lots must never be picked, and neither must one past its date. The date
    is read through ``effective_status_expression`` rather than the column,
    because nothing ever wrote EXPIRED into the column: FEFO hands out the
    earliest date first, which is precisely the wrong answer once that date
    has gone by.

    *lot_column* is the batch of whatever is being filtered — a record's
    (``Item.lot_id``) for a draw planned from the records.
    """
    active_lot_ids = (
        select(StockLot.id)
        .where(effective_status_expression() == LotStatus.ACTIVE.value)
        .scalar_subquery()
    )
    return or_(
        lot_column.is_(None),
        lot_column.in_(active_lot_ids),
    )


async def assert_lot_consumable_async(
    db: AsyncSession, lot_id: UUID, organization_id: UUID | None = None
) -> None:
    """Refuse a lot that is not ACTIVE, naming the status that blocks it.

    The twin of ``active_lot_predicate`` for the path that names one lot
    instead of searching for candidates. A predicate can only narrow a
    search, and an operator typing a batch number is not searching — so the
    same rule has to be asked as a question here, or it holds on one path
    and not on the other.

    ``organization_id`` scopes the lookup. Without it the fetch was by bare
    id, and the message names the batch: someone guessing an id learned that
    the row exists, what another organization calls it, and what state it is
    in. Outside this organization the answer is the same as for a lot that
    does not exist — nothing.

    A lot that no longer exists is not this function's business: the caller
    is about to find no records of it anyway, and says so better.
    """
    conditions = [StockLot.id == lot_id]
    if organization_id is not None:
        conditions.append(StockLot.organization_id == organization_id)
    lot = await db.scalar(select(StockLot).where(*conditions))
    if lot is not None and lot.effective_status != LotStatus.ACTIVE:
        raise ServiceRejectionError(
            'stock_lot_not_consumable', lot=lot.name, status=lot.effective_status
        )


def owner_predicate(owner_id: UUID | None, owner_column: Any):
    """Owner filter: default (None) = own stock only (``owner_id IS NULL``).

    Pass a partner UUID to consume consignment stock owned by that partner.
    *owner_column* is the owner of whatever is being filtered — a record's
    for a draw.
    """
    return owner_column.is_(None) if owner_id is None else owner_column == owner_id


async def list_quants_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID | None = None,
    storage_location_id: UUID | None = None,
    product_template_ids: list[UUID] | None = None,
    storage_location_ids: list[UUID] | None = None,
) -> list[Row[Any]]:
    """What stands on the shelves, as the records tell it.

    One row per product, shelf, batch and owner, read from
    ``stock_quants_from_records``: the live records summed per group, with
    the group's reservation rows beside them. The rows carry the columns the
    quant table had, so a reader that once read the table reads them the
    same way. ``id`` is the group's: nothing may write or lock by it.

    A record standing on no shelf would make a row no shelf holds. The
    schema forbids such a record today (``items.storage_location_id`` is
    NOT NULL); the filter keeps it away from every reader of availability if
    that ever changes.

    ``product_template_ids`` is the batch twin of ``product_template_id``
    (callers resolving many templates must not issue one query each), and
    ``storage_location_ids`` the same twin of ``storage_location_id``.
    """
    from app.models.stock_quants_from_records import stock_quants_from_records

    view = stock_quants_from_records
    stmt = select(view).where(
        view.c.organization_id == organization_id,
        view.c.storage_location_id.is_not(None),
    )
    if product_template_id:
        stmt = stmt.where(view.c.product_template_id == product_template_id)
    elif product_template_ids:
        stmt = stmt.where(in_ids(view.c.product_template_id, product_template_ids))
    if storage_location_id:
        stmt = stmt.where(view.c.storage_location_id == storage_location_id)
    elif storage_location_ids is not None:
        stmt = stmt.where(in_ids(view.c.storage_location_id, storage_location_ids))
    return list((await db.execute(stmt)).all())


async def quantities_by_shelf_async(
    db: AsyncSession,
    organization_id: UUID,
    storage_location_ids: list[UUID] | None = None,
) -> dict[UUID, dict[UUID, Decimal]]:
    """Shelf -> product -> quantity, summed in the database.

    What a fill is computed from: the groups of :func:`list_quants_async`
    added up per shelf and product, batches and owners together. Reading
    every group to add them up in Python cost a second for one zone at a
    hundred thousand products and held every group in memory for the
    organization's overview. ``storage_location_ids`` narrows to those
    shelves; ``None`` is the whole organization.
    """
    from app.models.stock_quants_from_records import stock_quants_from_records

    view = stock_quants_from_records
    stmt = select(
        view.c.storage_location_id,
        view.c.product_template_id,
        func.sum(view.c.quantity),
    ).where(
        view.c.organization_id == organization_id,
        view.c.storage_location_id.is_not(None),
        view.c.product_template_id.is_not(None),
    )
    if storage_location_ids is not None:
        stmt = stmt.where(in_ids(view.c.storage_location_id, storage_location_ids))
    stmt = stmt.group_by(view.c.storage_location_id, view.c.product_template_id)
    shelves: dict[UUID, dict[UUID, Decimal]] = {}
    for shelf, template_id, quantity in (await db.execute(stmt)).all():
        shelves.setdefault(shelf, {})[template_id] = quantity or Decimal('0')
    return shelves


async def _anchor_id_for_group_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    storage_location_id: UUID,
) -> UUID | None:
    """The row that locks this group — or None, for a shelf nothing stocked.

    An anchor is created when the first write locks its group, so a group
    seen read-only may have none. The pick line takes None and keeps the
    lot: nothing breaks, the line simply cannot be matched by group yet.
    """
    from app.models.stock_anchor import StockAnchor

    return await db.scalar(
        select(StockAnchor.id).where(
            StockAnchor.organization_id == organization_id,
            StockAnchor.product_template_id == product_template_id,
            StockAnchor.storage_location_id == storage_location_id,
        )
    )


async def find_best_pick_group_for_picking_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    storage_location_id: UUID | None = None,
    owner_id: UUID | None = None,
    *,
    except_document_id: UUID | None = None,
) -> PickGroupDTO | None:
    """The group and lot picking plans from: the shelf the product's strategy reaches first.

    The answer comes from ``stock_quants_from_records`` — the records'
    side of the world, where the availability a picker needs is counted.
    FIFO orders by the group's oldest record; FEFO by the earliest date of
    its batch, undated stock last, the group's oldest record breaking a
    tie — the same two orders the draw itself follows, so the batch a
    picker is sent to is the batch the draw would take. A lot that is not
    ACTIVE is no more pickable here than it was there, and a shelf the
    caller did not ask for is excluded the same way.

    *except_document_id* is the document this line will be picked for. Its
    own reservation rows are not counted against it: confirmation holds the
    strategy's first lot for the document, and reading that hold as
    somebody else's would send the picker to the next lot with the document
    holding the first one. Every other document's holds still count, as
    they do in the draw plan and in the lot-capacity check.
    """
    from app.models.product_template import ProductTemplate
    from app.models.stock_anchor import StockAnchor
    from app.models.stock_quants_from_records import stock_quants_from_records
    from app.models.stock_reservation import StockReservation

    view = stock_quants_from_records
    active_lots = (
        select(StockLot.id)
        .where(effective_status_expression() == LotStatus.ACTIVE.value)
        .scalar_subquery()
    )
    available = view.c.quantity > view.c.reserved_quantity
    if except_document_id is not None:
        own_hold = (
            select(func.coalesce(func.sum(StockReservation.quantity), 0))
            .join(StockAnchor, StockAnchor.id == StockReservation.anchor_id)
            .where(
                StockReservation.organization_id == view.c.organization_id,
                StockAnchor.product_template_id == view.c.product_template_id,
                StockAnchor.storage_location_id == view.c.storage_location_id,
                StockReservation.lot_id.is_not_distinct_from(view.c.lot_id),
                StockReservation.owner_id.is_not_distinct_from(view.c.owner_id),
                StockReservation.document_id == except_document_id,
            )
            .correlate(view)
            .scalar_subquery()
        )
        available = view.c.quantity + own_hold > view.c.reserved_quantity
    conditions = [
        view.c.organization_id == organization_id,
        view.c.product_template_id == product_template_id,
        view.c.storage_location_id.isnot(None),
        available,
        or_(view.c.lot_id.is_(None), view.c.lot_id.in_(active_lots)),
        (
            view.c.owner_id.is_(None)
            if owner_id is None
            else view.c.owner_id == owner_id
        ),
    ]
    if storage_location_id is not None:
        conditions.append(view.c.storage_location_id == storage_location_id)
    template = await db.scalar(
        select(ProductTemplate).where(ProductTemplate.id == product_template_id)
    )
    stmt = select(view.c.storage_location_id, view.c.lot_id, view.c.owner_id).where(
        *conditions
    )
    if resolve_removal_strategy(template) == 'FEFO':
        stmt = stmt.outerjoin(StockLot, view.c.lot_id == StockLot.id).order_by(
            earliest_lot_date().asc().nulls_last()
        )
    row = (await db.execute(stmt.order_by(view.c.created_at.asc()).limit(1))).first()
    if row is None:
        return None
    anchor_id = await _anchor_id_for_group_async(
        db, organization_id, product_template_id, row.storage_location_id
    )
    return PickGroupDTO(
        anchor_id=anchor_id,
        product_template_id=product_template_id,
        location_id=row.storage_location_id,
        lot_id=row.lot_id,
        owner_id=row.owner_id,
        expiry_date=await _next_draw_date_async(
            db,
            organization_id,
            product_template_id,
            (row.storage_location_id, row.lot_id, row.owner_id),
            resolve_removal_strategy(template),
        ),
    )


async def _next_draw_date_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    grain: tuple[UUID, UUID | None, UUID | None],
    strategy: str,
) -> date | None:
    """The date of the record a draw takes first from the group.

    Read the way the draw ranks its records, so the date shown to a picker
    is the date of the pack the draw reaches: the batch's when there is one,
    the record's own when there is not.
    """
    from app.models.item import Item
    from app.services._stock_draw import records_in_removal_order

    shelf, lot_id, owner_id = grain
    stmt = (
        select(earliest_lot_date(Item.effective_expiry_date))
        .select_from(Item)
        .where(
            Item.organization_id == organization_id,
            Item.template_id == product_template_id,
            Item.is_deleted.is_(False),
            Item.storage_location_id == shelf,
            Item.lot_id.is_not_distinct_from(lot_id),
            Item.owner_id.is_not_distinct_from(owner_id),
            Item.quantity > 0,
        )
    )
    return await db.scalar(records_in_removal_order(stmt, strategy).limit(1))


async def shelf_contents_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_ids: Collection[UUID] = (),
) -> list[ShelfContentsDTO]:
    """What stands on every shelf of the organization, one row per shelf.

    The records summed per shelf and product the way
    ``stock_quants_from_records`` sums them — a deleted record holds nothing,
    a NaN quantity is set aside — then told per shelf: how many products
    stand there, the one when it is one, and the quantities of
    *product_template_ids*. Read from the records directly: the view also
    builds each group's id and its reservations, which nobody here asks
    for, and at three hundred thousand records that was most of a second.

    Two statements whatever the size of the floor, and the rows that leave
    the database are one per shelf, not one per product on it. A shelf with
    no record at all has no row.
    """
    from app.models.item import Item

    per_product = (
        select(
            Item.storage_location_id.label('location_id'),
            Item.template_id.label('product_template_id'),
            func.sum(
                func.nullif(Item.quantity, literal_column("'NaN'::numeric"))
            ).label('quantity'),
        )
        .where(
            Item.organization_id == organization_id,
            Item.is_deleted.is_(False),
            Item.template_id.is_not(None),
            Item.storage_location_id.is_not(None),
        )
        .group_by(Item.storage_location_id, Item.template_id)
    )
    stocking = per_product.subquery('per_product')
    standing = stocking.c.quantity > 0
    shelves: dict[UUID, ShelfContentsDTO] = {}
    for row in (
        await db.execute(
            select(
                stocking.c.location_id,
                func.count().filter(standing).label('products'),
                # Read only where one product stands, so the first is the one.
                func.array_agg(stocking.c.product_template_id)
                .filter(standing)[1]
                .label('only_product'),
                func.sum(stocking.c.quantity).filter(standing).label('only_quantity'),
            ).group_by(stocking.c.location_id)
        )
    ).all():
        alone = row.products == 1
        shelves[row.location_id] = ShelfContentsDTO(
            location_id=row.location_id,
            products=row.products,
            only_product_template_id=row.only_product if alone else None,
            only_quantity=row.only_quantity if alone else None,
        )

    if product_template_ids:
        named = per_product.where(in_ids(Item.template_id, product_template_ids))
        for location_id, template_id, quantity in (await db.execute(named)).all():
            shelf = shelves.get(location_id)
            if shelf is not None:
                shelf.quantities[template_id] = quantity or Decimal('0')
    return list(shelves.values())
