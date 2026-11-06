"""Stock reservation operations, under the groups' anchors.

Extracted from ``stock_service.py`` — handles atomic stock reservation,
per-document reservation tracking, and release operations. A reservation is
its rows: each names the grain it holds (the group's anchor, the batch, the
owner) and how much, and what a grain has promised is the sum of its rows.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import DocumentReservationHoldDTO, ReservedSliceDTO
from app.core.contracts import ReservationResultDTO as ReservationResult
from app.core.logging import get_logger
from app.models.product_template import ProductTemplate
from app.models.stock_anchor import StockAnchor
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.services._stock_draw import records_by_grain_async
from app.services._stock_quant_ops import (
    _by_grain,
    _plan_under_the_anchors_async,
    anchor_ids_async,
    lock_stock_async,
)
from app.services.stock_strategy import resolve_removal_strategy

logger = get_logger(__name__)


async def reserve_for_document_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    location_id: UUID | None,
    needed_qty: Decimal,
    removal_strategy: str | None = None,
    *,
    document_id: UUID,
    document_line_id: UUID | None = None,
    lot_id: UUID | None = None,
    require_active_lot: bool = True,
) -> ReservationResult:
    """Atomically reserve stock for one document, under the groups' anchors.

    Returns a ReservationResult whose slices name a lot, an owner, a
    quantity and the reservation row that records them.

    The owner scope is the line's, the one rule every door answers by
    (``docs/subsystems/STOCK.md`` — the owner comes from the document
    line): a line that names no owner does not restrict, so the hold plans
    across every owner standing there, and the draw at completion takes
    the same scope — the two sides of one promise. Each row then names the
    owner of the grain it holds, whose goods the promise is about.

    What is held is planned from the records (``plan_draw_async``): in the
    removal strategy's order, only what each (shelf, batch, owner) has free
    of the rows already holding it, and only in a batch that may be
    dispatched — a reservation is a promise that the stock can later leave,
    and a held batch is exactly the stock that cannot. Nothing is held
    unless the whole quantity can be.

    *lot_id* narrows the hold to the batch a line names, and
    *require_active_lot* False is for the door that takes that batch out
    whatever its state — a write-off of a quarantined batch, a move of it
    into a quarantine area — the same terms the take at completion runs on
    (``plan_draw_async``).

    A ``StockReservation`` row is written for each grain drawn on, so the
    reservation can later be released per document without touching other
    documents' holds. The row names its grain — the group's anchor, the
    batch, the owner — and that is all a hold is: the records' view counts
    it by those.

    There is no reservation without a document: a hold is a row, and a row
    names the document it is for.

    *removal_strategy* None follows the product's own, as ``plan_draw_async``
    does when the stock leaves: the hold has to cover the batches the draw
    will take, and a first-expired-first-out product held in FIFO order
    promises the wrong stock.
    """
    if document_id is None:
        raise TypeError('A reservation belongs to a document; none was named.')
    if needed_qty <= 0:
        return ReservationResult(success=True, message='No quantity to reserve')

    if removal_strategy is None:
        template = await db.scalar(
            select(ProductTemplate).where(ProductTemplate.id == product_template_id)
        )
        removal_strategy = resolve_removal_strategy(template)

    plan = await _plan_under_the_anchors_async(
        db,
        organization_id,
        product_template_id,
        location_id,
        needed_qty,
        strategy=removal_strategy,
        any_owner=True,
        lot_id=lot_id,
        require_active_lot=require_active_lot,
    )
    if plan.free < needed_qty:
        short = needed_qty - plan.free
        message = (
            f'Could not reserve {short} of {needed_qty} for product '
            f'{product_template_id}'
        )
        logger.warning('Reservation refused, nothing held: %s', message)
        return ReservationResult(
            reserved=[], unreserved_quantity=short, success=False, message=message
        )

    from app.models.stock_reservation import StockReservation

    taken = _by_grain(plan.draws)
    anchors = await anchor_ids_async(
        db,
        organization_id,
        ((product_template_id, shelf) for shelf, _lot, _owner in taken),
    )
    # The rows first: each slice is named by the reservation row that records
    # it, so the ids have to exist before the answer is built.
    rows = [
        StockReservation(
            id=uuid4(),
            organization_id=organization_id,
            document_id=document_id,
            document_line_id=document_line_id,
            anchor_id=anchors[(product_template_id, shelf)],
            lot_id=lot,
            owner_id=owner,
            quantity=amount,
        )
        for (shelf, lot, owner), amount in taken.items()
    ]
    db.add_all(rows)
    return ReservationResult(
        reserved=[
            ReservedSliceDTO(
                reservation_id=row.id,
                lot_id=row.lot_id,
                owner_id=row.owner_id,
                quantity=row.quantity,
            )
            for row in rows
        ],
        unreserved_quantity=Decimal('0'),
        success=True,
        message='',
    )


async def release_for_document_async(
    db: AsyncSession,
    organization_id: UUID,
    document_id: UUID,
) -> None:
    """Release all reservations for a specific document.

    Deletes the document's ``StockReservation`` rows and nothing else, so it
    is safe for multi-document scenarios — only the target document's holds
    are released.
    """
    from app.models.stock_reservation import StockReservation

    # The anchors first, in the shared order, then the rows that hold them:
    # the order every other release and every reservation takes them in.
    await lock_stock_async(db, organization_id, reserved_for_document_id=document_id)
    stmt = (
        select(StockReservation)
        .where(
            StockReservation.organization_id == organization_id,
            StockReservation.document_id == document_id,
        )
        .with_for_update()
    )
    reservations = list((await db.execute(stmt)).scalars().all())
    for reservation in reservations:
        await db.delete(reservation)

    if reservations:
        logger.info(
            'Released %d reservation(s) for document %s',
            len(reservations),
            document_id,
        )


async def release_unbacked_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    location_id: UUID | None,
    leaving_quantity: Decimal,
    *,
    document_ids: Sequence[UUID] | None = None,
) -> Decimal:
    """Release only the hold the remaining stock can no longer cover.

    A group of stock is shared by every record of one product at one place,
    and the reservations on it belong to documents. So stock leaving is not
    a reason to release anything on its own: what stays behind usually
    still covers every hold. Only the part that ends up without stock behind
    it has to go — the newest holds first.

    What is held is the reservation rows of the product at the place; what
    covers them is the records of the (batch, owner) they hold, as the
    records' view counts both.

    *document_ids* narrows the rows that may be released to the holds those
    documents own. The goods on a shelf are fungible, the promises on them
    are not: a door that releases one kind of hold (a receipt's quarantine
    hold) must leave every other document's reservation standing, even when
    the stock behind both is the same record. What is free of every hold
    still decides how much of the named documents' share the leaving
    quantity uncovers — the other promises come off the top first.

    Returns how much was released.
    """
    from app.models.stock_reservation import StockReservation

    await lock_stock_async(
        db, organization_id, keys=[(product_template_id, location_id)]
    )
    rows_stmt = (
        select(StockReservation, StockAnchor.storage_location_id)
        .join(StockAnchor, StockAnchor.id == StockReservation.anchor_id)
        .where(
            StockReservation.organization_id == organization_id,
            StockAnchor.product_template_id == product_template_id,
        )
        .order_by(StockReservation.created_at.desc(), StockReservation.id.desc())
        .with_for_update(of=StockReservation)
    )
    if location_id is not None:
        rows_stmt = rows_stmt.where(StockAnchor.storage_location_id == location_id)
    rows = (await db.execute(rows_stmt)).all()
    if not rows:
        return Decimal('0')

    named = None if document_ids is None else set(document_ids)
    releasable = [
        (row, shelf) for row, shelf in rows if named is None or row.document_id in named
    ]
    if not releasable:
        return Decimal('0')

    held_grains = {(shelf, row.lot_id, row.owner_id) for row, shelf in rows}
    on_hand = sum(
        (
            quantity
            for grain, quantity in (
                await records_by_grain_async(
                    db, organization_id, product_template_id, location_id
                )
            ).items()
            if grain in held_grains
        ),
        start=Decimal('0'),
    )
    held = sum((row.quantity for row, _ in rows), start=Decimal('0'))
    # What is free of every promise, not only of the releasable ones.
    free = on_hand - held
    releasable_held = sum((row.quantity for row, _ in releasable), start=Decimal('0'))
    unbacked = min(releasable_held, max(Decimal('0'), leaving_quantity - free))
    if unbacked <= 0:
        return Decimal('0')

    remaining = unbacked
    for row, _ in releasable:
        if remaining <= 0:
            break
        taken = min(row.quantity, remaining)
        remaining -= taken
        if taken >= row.quantity:
            await db.delete(row)
        else:
            row.quantity -= taken
    return unbacked


async def held_quantity_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    location_id: UUID | None,
    *,
    document_ids: Sequence[UUID] | None = None,
) -> Decimal:
    """How much of this product on this shelf the named documents hold.

    The holds of a group are its reservation rows; this sums them, narrowed
    to one shelf and — when *document_ids* is given — to the holds those
    documents own. It reads and changes nothing: a door asking how much of a
    shelf's stock is one kind of hold (a receipt's quarantine hold) can tell
    it apart from the promises other documents made on the same goods.
    """
    from app.models.stock_reservation import StockReservation

    stmt = (
        select(func.coalesce(func.sum(StockReservation.quantity), 0))
        .join(StockAnchor, StockAnchor.id == StockReservation.anchor_id)
        .where(
            StockReservation.organization_id == organization_id,
            StockAnchor.product_template_id == product_template_id,
        )
    )
    if location_id is not None:
        stmt = stmt.where(StockAnchor.storage_location_id == location_id)
    if document_ids is not None:
        stmt = stmt.where(StockReservation.document_id.in_(document_ids))
    return Decimal(str(await db.scalar(stmt) or 0))


async def list_reservations_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    product_template_id: UUID | None = None,
    location_id: UUID | None = None,
    document_id: UUID | None = None,
    limit: int = 500,
):
    """List per-document stock reservations, newest first.

    Returns ORM ``StockReservation`` rows; the caller maps to DTOs. The
    product and the shelf a row holds are its anchor's, which the filters
    read.
    """
    from app.models.stock_reservation import StockReservation

    stmt = (
        select(StockReservation)
        .join(StockAnchor, StockAnchor.id == StockReservation.anchor_id)
        .where(StockReservation.organization_id == organization_id)
    )
    if document_id is not None:
        stmt = stmt.where(StockReservation.document_id == document_id)
    if product_template_id is not None:
        stmt = stmt.where(StockAnchor.product_template_id == product_template_id)
    if location_id is not None:
        stmt = stmt.where(StockAnchor.storage_location_id == location_id)
    stmt = stmt.order_by(StockReservation.created_at.desc()).limit(limit)

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def reservation_holds_by_documents_async(
    db: AsyncSession,
    organization_id: UUID,
    document_ids: Iterable[UUID],
) -> list[DocumentReservationHoldDTO]:
    """What each of these documents holds, per product and shelf.

    One row per (document, product, shelf) — the grain a screen shows a
    hold at — carrying the sum of that document's reservation rows on the
    group. The product's name, its unit and the shelf's name come with
    the row, read in the same statement: resolving them per row would be
    three lookups per hold across a screen of held documents. A document
    named twice is answered once.

    The document's own number and date are not read here; the document
    table belongs to the module that owns the documents, which already
    has them when it asks.
    """
    from app.models.stock_reservation import StockReservation

    ids = list(dict.fromkeys(document_ids))
    if not ids:
        return []
    rows = (
        await db.execute(
            select(
                StockReservation.document_id,
                StockAnchor.product_template_id,
                StockAnchor.storage_location_id,
                func.sum(StockReservation.quantity).label('quantity'),
                ProductTemplate.name.label('product_name'),
                Uom.symbol.label('uom_symbol'),
                StorageLocation.name.label('location_name'),
            )
            .join(StockAnchor, StockAnchor.id == StockReservation.anchor_id)
            .join(
                ProductTemplate,
                ProductTemplate.id == StockAnchor.product_template_id,
            )
            .outerjoin(Uom, Uom.id == ProductTemplate.uom_id)
            .join(
                StorageLocation,
                StorageLocation.id == StockAnchor.storage_location_id,
            )
            .where(
                StockReservation.organization_id == organization_id,
                StockAnchor.organization_id == organization_id,
                StockReservation.document_id.in_(ids),
            )
            .group_by(
                StockReservation.document_id,
                StockAnchor.product_template_id,
                StockAnchor.storage_location_id,
                ProductTemplate.name,
                Uom.symbol,
                StorageLocation.name,
            )
            .order_by(
                StockReservation.document_id,
                ProductTemplate.name,
                StorageLocation.name,
            )
        )
    ).all()
    return [
        DocumentReservationHoldDTO(
            document_id=row.document_id,
            product_template_id=row.product_template_id,
            location_id=row.storage_location_id,
            quantity=Decimal(str(row.quantity)),
            product_name=row.product_name,
            uom_symbol=row.uom_symbol,
            location_name=row.location_name,
        )
        for row in rows
    ]
