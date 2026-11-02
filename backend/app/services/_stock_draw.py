"""A draw planned from the records: which record gives how much, in what order.

The records are the stock (the one-number stock model, ADR-022), so what
a draw takes is chosen here, from the records of the group and the
reservation rows of each (shelf, batch, owner): the batch order off the
records' lot and ``created_at``, the free part as what a grain's records
hold less what its rows hold. The quant primitives that used to make this
choice by reading the quants went with the quant table.

Read under the group's anchor. Every writer of a group locks its anchor
first (``lock_stock_async``), so while the caller holds it nobody else
changes the records or the holds read here, and the records need no row
lock of their own.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Numeric, exists, func, literal, select, tuple_, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.stock_anchor import StockAnchor
from app.models.stock_lot import StockLot
from app.models.stock_reservation import StockReservation
from app.services._stock_quant_query import (
    active_lot_predicate,
    earliest_lot_date,
    owner_predicate,
)
from app.services.stock_strategy import resolve_removal_strategy

#: Places (a product on a shelf) one statement asks about; the bind parameters
#: of a statement are 32 767, and a place takes two.
_PLACES_PER_STATEMENT = 5000

#: ``(shelf, batch, owner)`` — what a reservation row holds stock of.
Grain = tuple[UUID, UUID | None, UUID | None]


@dataclass(frozen=True)
class RecordDraw:
    """How much one record gives to a draw, and what it has left afterwards.

    ``quantity`` is the take — ``min`` of what the record holds, what its
    grain still has free and what is still wanted. ``remaining`` is the record
    with that take off it, which is what the caller writes the record down to:
    the write is absolute, and the plan already decided the split.
    """

    record_id: UUID
    storage_location_id: UUID
    lot_id: UUID | None
    owner_id: UUID | None
    quantity: Decimal
    remaining: Decimal
    #: The date FEFO ranked the record by: its batch's, else its own.
    expiry_date: date | None = None


@dataclass(frozen=True)
class DrawPlan:
    """What a draw takes, record by record, and what there was to take.

    ``free`` is all the candidates could give, not only what was asked for,
    so a short draw can say how short. ``on_shelf`` tells nothing there from
    nothing free: some record of the product holds stock at the place,
    whatever its batch, its owner or the holds on it.
    """

    draws: list[RecordDraw]
    free: Decimal
    on_shelf: bool


def records_in_removal_order(stmt: Any, strategy: str) -> Any:
    """Order a record query the way *strategy* hands stock out.

    FEFO sorts by the earliest relevant date of the record's batch —
    ``use_by_date`` (food safety) before ``expiry_date`` (quality) when both
    are set, because the earlier one triggers first — with undated stock
    after dated stock. A record with no batch at all still has the date it
    was received with: a pack that showed a date but no lot number lands on
    the shelf with an expiry date and no ``lot_id``, and reading only the
    batch would file it with the undated stock. FIFO is the oldest record
    first. The batch is joined either way, so a query can select
    ``earliest_lot_date(...)`` — the date a draw is ranked by — from it.

    Both end on the record's id. Two records written in one instant — one
    statement, one transaction's ``now()`` — tie on every other key, and
    without the last one the database's row order would decide which of
    them a draw takes, differently from one plan to the next.
    """
    stmt = stmt.outerjoin(StockLot, Item.lot_id == StockLot.id)
    if strategy == 'FEFO':
        return stmt.order_by(
            earliest_lot_date(Item.effective_expiry_date).asc().nulls_last(),
            Item.created_at.asc(),
            Item.id.asc(),
        )
    return stmt.order_by(Item.created_at.asc(), Item.id.asc())


def _counted(quantity: Any) -> Any:
    """A record's quantity as the records' view counts it: NaN is not a number."""
    return func.nullif(quantity, literal(Decimal('NaN'), Numeric))


async def _held_by_grain_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    storage_location_id: UUID | None,
    except_document_id: UUID | None = None,
) -> dict[Grain, Decimal]:
    """What the reservation rows hold of the product, per (shelf, batch, owner).

    *except_document_id* leaves that document's own rows out: stock a document
    holds is not held against the document that is about to take it.
    """
    stmt = (
        select(
            StockAnchor.storage_location_id,
            StockReservation.lot_id,
            StockReservation.owner_id,
            func.sum(StockReservation.quantity),
        )
        .join(StockAnchor, StockAnchor.id == StockReservation.anchor_id)
        .where(
            StockReservation.organization_id == organization_id,
            StockAnchor.product_template_id == product_template_id,
        )
        .group_by(
            StockAnchor.storage_location_id,
            StockReservation.lot_id,
            StockReservation.owner_id,
        )
    )
    if storage_location_id is not None:
        stmt = stmt.where(StockAnchor.storage_location_id == storage_location_id)
    if except_document_id is not None:
        stmt = stmt.where(StockReservation.document_id != except_document_id)
    return {
        (shelf, lot, owner): held
        for shelf, lot, owner, held in (await db.execute(stmt)).all()
    }


async def records_by_grain_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    storage_location_id: UUID | None,
) -> dict[Grain, Decimal]:
    """What the product's records hold at the place, per (shelf, batch, owner).

    Every record counts, whatever the state of its batch: this is what
    stands behind a hold, not what may be drawn.
    """
    stmt = (
        select(
            Item.storage_location_id,
            Item.lot_id,
            Item.owner_id,
            func.coalesce(func.sum(_counted(Item.quantity)), 0),
        )
        .where(
            Item.organization_id == organization_id,
            Item.template_id == product_template_id,
            Item.is_deleted.is_(False),
        )
        .group_by(Item.storage_location_id, Item.lot_id, Item.owner_id)
    )
    if storage_location_id is not None:
        stmt = stmt.where(Item.storage_location_id == storage_location_id)
    return {
        (shelf, lot, owner): quantity
        for shelf, lot, owner, quantity in (await db.execute(stmt)).all()
    }


async def plan_draw_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    storage_location_id: UUID | None,
    quantity: Decimal | None,
    *,
    strategy: str | None = None,
    owner_id: UUID | None = None,
    any_owner: bool = False,
    lot_id: UUID | None = None,
    require_active_lot: bool = True,
    except_document_id: UUID | None = None,
    among_shelves: Sequence[UUID] | None = None,
) -> DrawPlan:
    """Plan a draw of *quantity* of a product from its records, in *strategy*'s order.

    A caller that names no *strategy* follows the template's own — the same
    voice the taking call answers in, so a plan cannot promise a FIFO draw
    a FEFO template's take would refuse to make.

    The candidates are the records of the product at *storage_location_id*
    (every shelf when it is None) that hold stock in a batch that may be
    used — none, or one whose effective status is ACTIVE. Whose goods: the
    organization's own by default, *owner_id*'s when one is named, anyone's
    with *any_owner*.

    *lot_id* narrows the candidates to that one batch — the door an operator
    pointed at a batch takes. *require_active_lot* False lifts the ACTIVE
    demand for the named batch: scrapping is what a recalled batch is for,
    and the door that takes it by name must still find its records.

    What a grain has free is its records less its reservation rows --
    *except_document_id*'s own not counted, for the document that asks what
    its own hold can still be served from. A row
    names its grain, not a record, so the records of a grain give their free
    part in order: each gives what it holds, what is still free in its
    grain and what is still wanted, whichever is least.

    *among_shelves* restricts the candidates to records standing on one of
    those shelves — a zone's draw passes the shelves below it. The order is
    the same across them: one list, FEFO or FIFO over all the records, so a
    batch that is earliest on one shelf comes before the later batch of
    another.

    *quantity* None plans everything free. A plan that falls short is not
    refused here; the caller decides what a short draw means.
    """
    if strategy is None:
        template = await db.scalar(
            select(ProductTemplate).where(ProductTemplate.id == product_template_id)
        )
        strategy = resolve_removal_strategy(template)
    place = [
        Item.organization_id == organization_id,
        Item.template_id == product_template_id,
        Item.is_deleted.is_(False),
        _counted(Item.quantity) > 0,
    ]
    if storage_location_id is not None:
        place.append(Item.storage_location_id == storage_location_id)
    if among_shelves is not None:
        place.append(Item.storage_location_id.in_(list(among_shelves)))

    candidates = select(
        Item.id,
        Item.storage_location_id,
        Item.lot_id,
        Item.owner_id,
        Item.quantity,
        earliest_lot_date(Item.effective_expiry_date).label('expiry_date'),
    ).where(*place)
    if require_active_lot:
        candidates = candidates.where(active_lot_predicate(Item.lot_id))
    else:
        # Only a door that names its batch may lift the demand, and then
        # only that batch's records are candidates.
        assert lot_id is not None, (
            'require_active_lot=False is for a draw that names its batch'
        )
    if lot_id is not None:
        candidates = candidates.where(Item.lot_id.is_not_distinct_from(lot_id))
    if not any_owner:
        candidates = candidates.where(owner_predicate(owner_id, Item.owner_id))
    records = (await db.execute(records_in_removal_order(candidates, strategy))).all()
    if not records:
        on_shelf = await db.scalar(select(exists().where(*place)))
        return DrawPlan(draws=[], free=Decimal('0'), on_shelf=bool(on_shelf))

    held = await _held_by_grain_async(
        db,
        organization_id,
        product_template_id,
        storage_location_id,
        except_document_id,
    )
    left: dict[Grain, Decimal] = {}
    for record in records:
        grain = (record.storage_location_id, record.lot_id, record.owner_id)
        left[grain] = left.get(grain, Decimal('0')) + record.quantity
    for grain, on_hand in left.items():
        left[grain] = max(on_hand - held.get(grain, Decimal('0')), Decimal('0'))
    free = sum(left.values(), Decimal('0'))

    wanted = free if quantity is None else quantity
    draws: list[RecordDraw] = []
    for record in records:
        if wanted <= 0:
            break
        grain = (record.storage_location_id, record.lot_id, record.owner_id)
        take = min(record.quantity, left[grain], wanted)
        if take <= 0:
            continue
        left[grain] -= take
        wanted -= take
        draws.append(
            RecordDraw(
                record_id=record.id,
                storage_location_id=record.storage_location_id,
                lot_id=record.lot_id,
                owner_id=record.owner_id,
                quantity=take,
                remaining=record.quantity - take,
                expiry_date=record.expiry_date,
            )
        )
    return DrawPlan(draws=draws, free=free, on_shelf=True)


async def free_in_grains_async(
    db: AsyncSession,
    organization_id: UUID,
    grains: Iterable[tuple[UUID, Grain]],
) -> dict[tuple[UUID, Grain], Decimal]:
    """What each (product, grain) has free, for many at once: records less rows.

    The answer :func:`free_in_grain_async` gives for one, asked of every
    product and shelf named in a single statement (a chunk of them, past a
    few thousand) -- a document's lines used to ask it once each.
    """
    free = {key: Decimal('0') for key in grains}
    places = list({(template, grain[0]) for template, grain in free})
    for start in range(0, len(places), _PLACES_PER_STATEMENT):
        chunk = places[start : start + _PLACES_PER_STATEMENT]
        on_hand = (
            select(
                Item.template_id,
                Item.storage_location_id,
                Item.lot_id,
                Item.owner_id,
                func.coalesce(func.sum(_counted(Item.quantity)), 0),
                literal('on_hand').label('kind'),
            )
            .where(
                Item.organization_id == organization_id,
                Item.is_deleted.is_(False),
                tuple_(Item.template_id, Item.storage_location_id).in_(chunk),
            )
            .group_by(
                Item.template_id,
                Item.storage_location_id,
                Item.lot_id,
                Item.owner_id,
            )
        )
        held = (
            select(
                StockAnchor.product_template_id,
                StockAnchor.storage_location_id,
                StockReservation.lot_id,
                StockReservation.owner_id,
                func.sum(StockReservation.quantity),
                literal('held').label('kind'),
            )
            .join(StockAnchor, StockAnchor.id == StockReservation.anchor_id)
            .where(
                StockReservation.organization_id == organization_id,
                tuple_(
                    StockAnchor.product_template_id, StockAnchor.storage_location_id
                ).in_(chunk),
            )
            .group_by(
                StockAnchor.product_template_id,
                StockAnchor.storage_location_id,
                StockReservation.lot_id,
                StockReservation.owner_id,
            )
        )
        for template, shelf, lot, owner, quantity, kind in (
            await db.execute(union_all(on_hand, held))
        ).all():
            key = (template, (shelf, lot, owner))
            if key in free:
                free[key] += quantity if kind == 'on_hand' else -quantity
    return free


async def free_in_grain_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    grain: Grain,
) -> Decimal:
    """What one grain has free: what its records hold less what its rows hold.

    Every record of the grain counts, whatever the state of its batch — a
    change to a record takes off the record's own grain, not a draw that
    chooses among batches. Read under the group's anchor, like the rest.
    """
    free = await free_in_grains_async(
        db, organization_id, [(product_template_id, grain)]
    )
    return free[(product_template_id, grain)]
