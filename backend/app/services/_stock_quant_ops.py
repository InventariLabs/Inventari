"""The stock service's writes: the anchor lock, the draw off the records, the movement pass.

- ``lock_stock_async`` — the one order every operation that writes more
  than one group of stock locks in: each group's anchor (``stock_anchors``);
- ``take_from_the_records_async`` — a draw planned from the records under
  the anchors, on one shelf or on every shelf of the product: the records it
  names written down, one movement off the shelf per shelf and batch they
  gave up;
- ``post_movement_async`` — goods arriving, leaving or changing shelves:
  the records handed over stated and the movement written, one pass.

The quant table these used to keep beside the records is gone (the
one-number stock model, ADR-022). The records are the stock, and a group's
reservation rows are what is promised out of it: what a grain can give is
what its records hold less what its rows hold.

Read-only operations live in ``_stock_quant_query``. Reservation
operations live in ``_stock_reservation``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Uuid,
    and_,
    any_,
    bindparam,
    column,
    func,
    or_,
    select,
    tuple_,
    union,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import RecordPostDTO
from app.core.exceptions import ServiceRejectionError, StockUnavailableError
from app.core.txn_memo import transaction_memo
from app.i18n.service import get_current_lang, get_error_message
from app.models.product_template import ProductTemplate
from app.models.stock_anchor import StockAnchor
from app.models.storage_location import StorageLocation
from app.services._stock_draw import (
    DrawPlan,
    Grain,
    RecordDraw,
    free_in_grains_async,
    plan_draw_async,
)
from app.services._stock_quant_query import assert_lot_consumable_async
from app.services.stock_strategy import resolve_removal_strategy


async def _refuse(
    db: AsyncSession,
    code: str,
    key: str,
    product_template_id: UUID,
    storage_location_id: UUID,
    **numbers: object,
) -> StockUnavailableError:
    """The refusal, named the way the person looking at it knows the two things.

    These sentences reach the screen unchanged — a toast on a bulk edit, a
    toast on a single move — and they used to carry two UUIDs and no
    translation. The names cost two selects on a path that is already
    refusing, and they are what makes the message actionable: on a bulk edit
    the product name is which of the selected rows blocked the batch.
    """
    product = await db.scalar(
        select(ProductTemplate.name).where(ProductTemplate.id == product_template_id)
    )
    location = await db.scalar(
        select(StorageLocation.name).where(StorageLocation.id == storage_location_id)
    )
    return StockUnavailableError(
        code,
        get_error_message(
            key,
            get_current_lang(),
            product=product or product_template_id,
            location=location or storage_location_id,
            **numbers,
        ),
        product_template_id=product_template_id,
        storage_location_id=storage_location_id,
    )


async def _create_anchors_async(
    db: AsyncSession,
    organization_id: UUID,
    shelves: list[tuple[UUID, UUID]],
) -> None:
    """Give each ``(product, shelf)`` group an anchor, in one statement, in key order."""
    await db.execute(
        pg_insert(StockAnchor)
        .values(
            [
                {
                    'organization_id': organization_id,
                    'product_template_id': tpl,
                    'storage_location_id': loc,
                }
                for tpl, loc in shelves
            ]
        )
        .on_conflict_do_nothing(
            index_elements=[
                'organization_id',
                'product_template_id',
                'storage_location_id',
            ]
        )
    )


async def anchor_ids_async(
    db: AsyncSession,
    organization_id: UUID,
    shelves: Iterable[tuple[UUID, UUID]],
) -> dict[tuple[UUID, UUID], UUID]:
    """The anchor of each ``(product, shelf)`` group, created where it is missing.

    For a row that names its group by its anchor, a reservation, rather than
    for a lock: the groups a reservation draws on were locked before it read
    them, so every one of them has its anchor already.
    """
    shelves = sorted(set(shelves))
    if not shelves:
        return {}
    await _create_anchors_async(db, organization_id, shelves)
    rows = await db.execute(
        select(
            StockAnchor.product_template_id,
            StockAnchor.storage_location_id,
            StockAnchor.id,
        ).where(
            StockAnchor.organization_id == organization_id,
            tuple_(
                StockAnchor.product_template_id, StockAnchor.storage_location_id
            ).in_(shelves),
        )
    )
    return {(tpl, loc): anchor_id for tpl, loc, anchor_id in rows.all()}


async def _lock_anchors_async(
    db: AsyncSession,
    organization_id: UUID,
    templates: list[UUID],
    shelves: list[tuple[UUID, UUID]],
    reserved_for_document_id: UUID | None,
) -> set[tuple[UUID, UUID]]:
    """Create the named shelves' missing anchors, then lock the anchors in ``id`` order.

    ``FOR NO KEY UPDATE``, not ``FOR UPDATE``: nothing ever updates an anchor,
    and the weaker lock still keeps two writers of a group apart while letting
    through the ``FOR KEY SHARE`` a foreign key check takes on it.

    Returns the groups locked, as ``(product_template_id, storage_location_id)``.
    """
    if shelves:
        await _create_anchors_async(db, organization_id, shelves)
    if len(templates) + len(shelves) >= _MANY_GROUPS:
        return await _lock_many_anchors_async(
            db, organization_id, templates, shelves, reserved_for_document_id
        )
    conditions: list[Any] = []
    if templates:
        conditions.append(StockAnchor.product_template_id.in_(templates))
    if shelves:
        conditions.append(
            tuple_(
                StockAnchor.product_template_id, StockAnchor.storage_location_id
            ).in_(shelves)
        )
    if reserved_for_document_id is not None:
        from app.models.stock_reservation import StockReservation

        conditions.append(
            StockAnchor.id.in_(
                select(StockReservation.anchor_id).where(
                    StockReservation.document_id == reserved_for_document_id
                )
            )
        )
    if not conditions:
        return set()
    locked = await db.execute(
        select(StockAnchor.product_template_id, StockAnchor.storage_location_id)
        .where(StockAnchor.organization_id == organization_id, or_(*conditions))
        .order_by(StockAnchor.id)
        .with_for_update(key_share=True)
    )
    return {(tpl, shelf) for tpl, shelf in locked.all()}


#: How many groups make a lock worth finding in two steps. Asked for with a
#: long list, the single statement below is planned as a walk of the whole
#: table in ``id`` order — the order it locks in — filtering as it goes; at a
#: few hundred thousand anchors that is a quarter of a second to a second.
_MANY_GROUPS = 24


async def _lock_many_anchors_async(
    db: AsyncSession,
    organization_id: UUID,
    templates: list[UUID],
    shelves: list[tuple[UUID, UUID]],
    reserved_for_document_id: UUID | None,
) -> set[tuple[UUID, UUID]]:
    """Lock the anchors of a long list of groups: find their ids by index, then lock those.

    The same anchors as the single statement locks, in the same ``id`` order.
    Finding them is a separate statement without the ordering, which the
    planner answers from the indexes (the product, and the unique group key
    probed once per shelf named); locking is then one ordered read of exactly
    those rows by key.
    """
    found: list[Any] = []
    if templates:
        found.append(
            select(StockAnchor.id).where(
                StockAnchor.organization_id == organization_id,
                StockAnchor.product_template_id.in_(templates),
            )
        )
    if shelves:
        named = (
            func.unnest(
                bindparam('named_products', [t for t, _ in shelves], ARRAY(Uuid)),
                bindparam('named_shelves', [loc for _, loc in shelves], ARRAY(Uuid)),
            )
            .table_valued(column('product_id', Uuid), column('shelf_id', Uuid))
            .render_derived(name='named')
        )
        found.append(
            select(StockAnchor.id)
            .join(
                named,
                and_(
                    StockAnchor.product_template_id == named.c.product_id,
                    StockAnchor.storage_location_id == named.c.shelf_id,
                ),
            )
            .where(StockAnchor.organization_id == organization_id)
        )
    if reserved_for_document_id is not None:
        from app.models.stock_reservation import StockReservation

        found.append(
            select(StockAnchor.id).where(
                StockAnchor.organization_id == organization_id,
                StockAnchor.id.in_(
                    select(StockReservation.anchor_id).where(
                        StockReservation.document_id == reserved_for_document_id
                    )
                ),
            )
        )
    ids = sorted(set((await db.scalars(union(*found))).all()))
    if not ids:
        return set()
    locked = await db.execute(
        select(StockAnchor.product_template_id, StockAnchor.storage_location_id)
        .where(StockAnchor.id == any_(bindparam('locked_ids', ids, ARRAY(Uuid))))
        .order_by(StockAnchor.id)
        .with_for_update(key_share=True)
    )
    return {(tpl, shelf) for tpl, shelf in locked.all()}


async def lock_stock_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    keys: Iterable[tuple[UUID, UUID | None]] = (),
    reserved_for_document_id: UUID | None = None,
) -> set[tuple[UUID, UUID]]:
    """Lock every group of stock an operation is about to write, at once, in one order.

    A group used to be locked by whoever wrote it, when they got to it. An
    operation that writes more than one — a document's lines, the two ends
    of a move, a reservation that may draw on any shelf — took them one at a
    time, so two of them taking the same groups in opposite orders each held
    one the other was waiting for, and the database aborted one of them: a
    person got an error for a document or a move nothing was wrong with.
    Taken here, before the first write and in ``id`` order, the second
    operation waits for the first instead of meeting it halfway.

    *keys* are ``(product_template_id, storage_location_id)`` pairs; a
    location of ``None`` means every shelf of the product — the grain the
    cost layers are kept at, which a document drains per product whatever
    the shelf. *reserved_for_document_id* adds the groups that document's
    reservations hold, which need not be on any shelf the caller names.

    What is locked is the group's anchor (``stock_anchors``), a row with no
    quantity. The anchors of the shelves named are created first, in one
    statement and in key order, so a group nobody has stocked yet has a row
    to wait on: two first receipts to one shelf queue on it rather than
    racing to insert. Every shelf of a product locks only the anchors that
    exist — a shelf with no anchor holds none of the product to protect.

    Locking again what the transaction already holds costs nothing, so a
    caller that locks up front can go on through code that locks as it
    goes. A key the transaction did not name up front, locked later, is
    taken after the others and can close a circle with a neighbour: the
    database then aborts one of the two, and no stock is written wrong.

    Returns the groups whose anchors are now locked.
    """
    keys = list(keys)
    templates = sorted({tpl for tpl, loc in keys if loc is None})
    shelves = sorted({(tpl, loc) for tpl, loc in keys if loc is not None})
    held_templates, held_pairs = _held_locks(db)
    # What this transaction already holds is not asked for again: a document
    # posting line by line names the same groups from every layer it passes
    # through, and each ask was two statements.
    wanted_templates = [
        t for t in templates if (organization_id, t) not in held_templates
    ]
    wanted_shelves = [
        (t, loc) for t, loc in shelves if (organization_id, t, loc) not in held_pairs
    ]
    if wanted_templates or wanted_shelves or reserved_for_document_id is not None:
        locked = await _lock_anchors_async(
            db,
            organization_id,
            wanted_templates,
            wanted_shelves,
            reserved_for_document_id,
        )
        held_templates.update((organization_id, t) for t in wanted_templates)
        held_pairs.update((organization_id, t, loc) for t, loc in locked)
    # What is held among the groups asked about: the named shelves, and every
    # shelf held of a product named as a whole.
    held_of_the_products = _held_by_product(held_pairs, organization_id, templates)
    return held_of_the_products | {
        (t, loc) for t, loc in shelves if (organization_id, t, loc) in held_pairs
    }


def _held_by_product(
    held_pairs: set[tuple[UUID, UUID, UUID]],
    organization_id: UUID,
    templates: list[UUID],
) -> set[tuple[UUID, UUID]]:
    """The held groups of the named products, each on every shelf it is held on."""
    if not templates:
        return set()
    named = set(templates)
    return {
        (t, loc)
        for (org, t, loc) in held_pairs
        if org == organization_id and t in named
    }


def _held_locks(
    db: AsyncSession,
) -> tuple[set[tuple[UUID, UUID]], set[tuple[UUID, UUID, UUID]]]:
    """The anchors this transaction has locked: ``(org, product)`` taken as every
    shelf of the product, and ``(org, product, shelf)`` taken one by one.
    """
    return transaction_memo(db, 'stock_anchors_held', lambda: (set(), set()))


@dataclass(frozen=True)
class QuantConsumption:
    """How much a draw took off one grain: a batch, on a shelf, of an owner."""

    lot_id: UUID | None
    consumed: Decimal
    storage_location_id: UUID | None = None
    owner_id: UUID | None = None
    #: Set only on stock that carries no batch, one entry per date drawn:
    #: the date the records were received with. A batch's date is the batch's.
    expiry_date: date | None = None
    #: The first record the draw took from for this entry, batch or not: the
    #: record a line of that batch or date stands for.
    record_id: UUID | None = None


def _by_grain(draws: Iterable[RecordDraw]) -> dict[Grain, Decimal]:
    """How much the plan takes per (shelf, batch, owner), in the order first drawn on."""
    grains: dict[Grain, Decimal] = {}
    for draw in draws:
        grain = (draw.storage_location_id, draw.lot_id, draw.owner_id)
        grains[grain] = grains.get(grain, Decimal('0')) + draw.quantity
    return grains


async def _plan_under_the_anchors_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    storage_location_id: UUID | None,
    quantity: Decimal | None,
    *,
    strategy: str,
    owner_id: UUID | None = None,
    any_owner: bool = False,
    lot_id: UUID | None = None,
    require_active_lot: bool = True,
) -> DrawPlan:
    """Lock the groups a draw may take from, then plan it from their records.

    One shelf is one anchor, locked before the plan reads it. Every shelf of
    the product locks the anchors there are when the lock is taken; a shelf
    stocked for the first time meanwhile has an anchor that lock never saw,
    and once that stock is committed the plan reads it all the same. So the
    shelves the plan drew on that the transaction does not hold are locked
    by name and the plan read again, until it names none it does not hold.
    Anchors already held cost nothing; a new one is a key taken late, which
    ``lock_stock_async`` allows at the price it names.
    """
    held = await lock_stock_async(
        db, organization_id, keys=[(product_template_id, storage_location_id)]
    )
    while True:
        plan = await plan_draw_async(
            db,
            organization_id,
            product_template_id,
            storage_location_id,
            quantity,
            strategy=strategy,
            owner_id=owner_id,
            any_owner=any_owner,
            lot_id=lot_id,
            require_active_lot=require_active_lot,
        )
        unheld = {
            (product_template_id, draw.storage_location_id) for draw in plan.draws
        } - held
        if not unheld:
            return plan
        held |= await lock_stock_async(db, organization_id, keys=sorted(unheld))


async def _write_the_planned_records_async(
    db: AsyncSession,
    organization_id: UUID,
    plan: DrawPlan,
    *,
    user_id: UUID | None,
    source_document_id: UUID | None,
    history_changes: dict[str, Any] | None,
) -> None:
    """Write each record of the plan down to its new number, one update each.

    Through the items service's own quantity path, because the period guard,
    the interceptor pipeline and the history log are the record's rules, not
    a copy of them. The record's own posting stays off
    (``post_the_change=False``) — the movements are written once, per shelf
    and batch, by the draw, not once per record on the way — and so does the
    valuation: what a draw costs is the caller's to post, and a document
    prices its own delivery.
    """
    from app.schemas.item import ItemQuantityUpdate
    from app.services.items import get_by_id_for_update_async, update_quantity

    for draw in plan.draws:
        record = await get_by_id_for_update_async(db, organization_id, draw.record_id)
        if record is None:
            # Unreachable under the anchor the plan was read behind — every
            # writer of the group holds it — so the refusal is the keyed one
            # the door's other paths already answer with.
            raise ServiceRejectionError('item_not_found')
        held = record.quantity or Decimal('0')
        await update_quantity(
            db,
            record,
            ItemQuantityUpdate(quantity=held - draw.quantity),
            user_id=user_id,
            source_document_id=source_document_id,
            history_changes=history_changes,
            sync_valuation=False,
            post_the_change=False,
        )


async def take_from_the_records_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    storage_location_id: UUID | None,
    quantity: Decimal,
    lot_id: UUID | None = None,
    owner_id: UUID | None = None,
    *,
    require_active_lot: bool = True,
    any_owner: bool = False,
    removal_strategy: str | None = None,
    user_id: UUID | None = None,
    source_document_id: UUID | None = None,
    history_changes: dict[str, Any] | None = None,
    reference_type: str | None = None,
    reference_id: UUID | None = None,
) -> list[QuantConsumption]:
    """Take ``quantity`` off the records the draw plan names, one write each.

    The draw is planned from the records under the anchors
    (``plan_draw_async`` — the removal strategy's order, only what each
    grain has free of its reservation rows) and written to the records the
    plan named. The movements off the shelf are written here too, one per
    shelf, batch and owner the records gave up, naming ``reference_type``
    and ``reference_id`` — the records and the register's rows in one call.
    Returns what was taken, grain by grain.

    *storage_location_id* None draws on every shelf of the product, in one
    removal order: a production run asks for an ingredient, not for an
    ingredient on a particular shelf. *removal_strategy* overrides the
    product's.

    The owner scope follows the one rule every door answers by (the owner
    comes from the document line — ``docs/subsystems/STOCK.md``): a named
    ``owner_id`` takes only that owner's goods, ``any_owner`` takes whose
    goods stand there — a production run asks that way, because it consumes
    what is physically there — and the default (neither) is the
    organization's own.

    Refusals on one shelf speak the codes a door's user reads —
    ``NO_STOCK``, ``ALL_HELD``, ``NOT_ENOUGH`` — and on every shelf a
    ``ValueError`` naming what was asked for and what there is; nothing is
    written unless the whole of it can be. A door that names its batch
    (``lot_id``) takes that batch and no other, on ``require_active_lot``
    terms: a dispatch may not consume a held batch, a scrap of the batch the
    operator confirmed is how the recall leaves the building.
    """
    if storage_location_id is None and quantity <= 0:
        return []
    template = await db.scalar(
        select(ProductTemplate).where(ProductTemplate.id == product_template_id)
    )
    strategy = resolve_removal_strategy(template, override=removal_strategy)
    if lot_id is None:
        # The lift is about the named batch — a draw that follows the
        # strategy always honours the removal guard, scrap included.
        require_active_lot = True
    if lot_id is not None and require_active_lot:
        await assert_lot_consumable_async(db, lot_id, organization_id)

    plan = await _plan_under_the_anchors_async(
        db,
        organization_id,
        product_template_id,
        storage_location_id,
        quantity,
        strategy=strategy,
        owner_id=owner_id,
        any_owner=any_owner,
        lot_id=lot_id,
        require_active_lot=require_active_lot,
    )
    if storage_location_id is None:
        if plan.free < quantity:
            raise ServiceRejectionError(
                'stock_insufficient_for_template',
                template_id=product_template_id,
                requested=quantity,
                available=plan.free,
            )
    elif not plan.draws:
        raise await _refuse(
            db,
            StockUnavailableError.ALL_HELD
            if plan.on_shelf
            else StockUnavailableError.NO_STOCK,
            'stock_all_batches_held' if plan.on_shelf else 'stock_none_at_location',
            product_template_id,
            storage_location_id,
        )
    elif plan.free < quantity:
        raise await _refuse(
            db,
            StockUnavailableError.NOT_ENOUGH,
            'stock_not_enough',
            product_template_id,
            storage_location_id,
            available=plan.free,
            requested=quantity,
        )

    await _write_the_planned_records_async(
        db,
        organization_id,
        plan,
        user_id=user_id,
        source_document_id=source_document_id,
        history_changes=history_changes,
    )
    return await _move_off_the_shelves_async(
        db,
        organization_id,
        product_template_id,
        plan.draws,
        user_id=user_id,
        reference_type=reference_type,
        reference_id=reference_id,
    )


async def _move_off_the_shelves_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    draws: Iterable[RecordDraw],
    *,
    user_id: UUID | None,
    reference_type: str | None,
    reference_id: UUID | None,
) -> list[QuantConsumption]:
    """One movement off the shelf per shelf, batch and owner the records gave up, in the order first drawn on.

    Per batch, not per record: a movement names no record, so two records
    of one batch leaving together are that batch leaving — and a recall
    follows the batch. Per owner too: two owners of one batch are different
    goods, and the movement says whose they were, the way the reservation
    row and the record it changed already do. The answer is per grain,
    owner included, because a consignor's share is the caller's to settle.
    """
    from app.services import stock_moves_service

    draws = list(draws)
    moves: dict[tuple[UUID, UUID | None, UUID | None, date | None], Decimal] = {}
    first_record: dict[tuple[UUID, UUID | None, UUID | None, date | None], UUID] = {}
    for draw in draws:
        key = (draw.storage_location_id, draw.lot_id, draw.owner_id, draw.expiry_date)
        moves[key] = moves.get(key, Decimal('0')) + draw.quantity
        first_record.setdefault(key, draw.record_id)
    for (shelf, batch, owner, expiry), amount in moves.items():
        await stock_moves_service.create_async(
            db,
            organization_id=organization_id,
            product_template_id=product_template_id,
            from_location_id=shelf,
            quantity=amount,
            lot_id=batch,
            owner_id=owner,
            expiry_date=expiry,
            reference_type=reference_type,
            reference_id=reference_id,
            created_by=user_id,
        )
    # A batch's date is the batch's, so its grain stays one entry; goods with
    # no batch are told apart by the date they were received with.
    consumed: dict[tuple[UUID, UUID | None, UUID | None, date | None], Decimal] = {}
    records: dict[tuple[UUID, UUID | None, UUID | None, date | None], UUID] = {}
    for (shelf, batch, owner, expiry), amount in moves.items():
        key = (shelf, batch, owner, expiry if batch is None else None)
        consumed[key] = consumed.get(key, Decimal('0')) + amount
        records.setdefault(key, first_record[(shelf, batch, owner, expiry)])
    return [
        QuantConsumption(
            lot_id=batch,
            consumed=amount,
            storage_location_id=shelf,
            owner_id=owner,
            expiry_date=expiry,
            record_id=records.get((shelf, batch, owner, expiry)),
        )
        for (shelf, batch, owner, expiry), amount in consumed.items()
    ]


#: Where a pass that asks its shortage question once, at its end, keeps the
#: grains it moved stock off: ``(product, grain, quantity)`` per movement.
_ASKED_AT_THE_END = 'grains_asked_at_the_end'


async def _refuse_a_grain_left_short_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    grain: Grain,
    quantity: Decimal,
) -> None:
    """Refuse goods leaving a grain whose reservation rows they leave uncovered.

    The grain is a shelf, a batch and an owner. Asked after the records are
    stated — a door that carries its record to another shelf has written the
    shelf already, a correction states its number in this pass — so the
    question is where the grain ended: what its records hold, less what its
    reservation rows hold, must not be below zero. Taking more would leave an
    order's hold standing on goods that are gone; the pass is refused by
    name instead, and the caller's transaction takes the records back.

    Inside :func:`ask_what_each_grain_has_free_once` the question is kept for
    the end of that block instead.
    """
    if grain[0] is None:
        return
    session = getattr(db, 'sync_session', None)
    asked: list[tuple[UUID, Grain, Decimal]] | None = (
        session.info.get(_ASKED_AT_THE_END) if session is not None else None
    )
    if asked is not None:
        asked.append((product_template_id, grain, quantity))
        return
    await _refuse_grains_left_short_async(
        db, organization_id, [(product_template_id, grain, quantity)]
    )


async def _refuse_grains_left_short_async(
    db: AsyncSession,
    organization_id: UUID,
    movements: Sequence[tuple[UUID, Grain, Decimal]],
) -> None:
    """The refusal of :func:`_refuse_a_grain_left_short_async`, for many movements in one read.

    The first grain, in the order its stock was moved, that ended below zero
    is the one named; what was *requested* of it is everything that left it.
    """
    requested: dict[tuple[UUID, Grain], Decimal] = {}
    for template_id, grain, quantity in movements:
        key = (template_id, grain)
        requested[key] = requested.get(key, Decimal('0')) + quantity
    free = await free_in_grains_async(db, organization_id, requested)
    for (template_id, grain), taken in requested.items():
        left = free[(template_id, grain)]
        if left < 0:
            raise await _refuse(
                db,
                StockUnavailableError.NOT_ENOUGH,
                'stock_not_enough',
                template_id,
                grain[0],
                available=max(left + taken, Decimal('0')),
                requested=taken,
            )


@asynccontextmanager
async def ask_what_each_grain_has_free_once(
    db: AsyncSession, organization_id: UUID
) -> AsyncIterator[None]:
    """Ask the shortage question of a pass's movements once, when its lines are done.

    A correction or an adjustment moves stock line by line, and each movement
    used to be followed by its own read of what the grain has free. The
    movements are the same; the question is put when the last of them is
    written, in one statement, and a grain a later line brought back above
    zero is no longer refused for having dipped. The refusal is the same
    error, raised from the end of this block. Nesting joins the outer block.
    """
    info = db.sync_session.info
    if _ASKED_AT_THE_END in info:
        yield
        return
    asked: list[tuple[UUID, Grain, Decimal]] = []
    info[_ASKED_AT_THE_END] = asked
    try:
        yield
    finally:
        info.pop(_ASKED_AT_THE_END, None)
    await _refuse_grains_left_short_async(db, organization_id, asked)


async def _write_the_records(
    db: AsyncSession,
    organization_id: UUID,
    records: Sequence[RecordPostDTO],
    user_id: UUID | None,
) -> None:
    """State the records' numbers through the items service, locks held.

    The service call is the guarded one — the inventory-period gate, the
    interceptors, the audit trail ride on it — the same path a door took
    before this pass carried the record; the quantity is stated absolute,
    as the doors always stated it.
    """
    if not records:
        return
    from app.schemas.item import ItemQuantityUpdate
    from app.services.items import get_by_id_for_update_async, update_quantity

    for record in records:
        item = await get_by_id_for_update_async(db, organization_id, record.item_id)
        if item is None:
            raise ServiceRejectionError('item_not_found')
        await update_quantity(
            db=db,
            item=item,
            quantity_update=ItemQuantityUpdate(quantity=record.new_quantity),
            user_id=user_id,
            source_document_id=record.source_document_id,
            history_changes=record.history,
            # The movement is written by this pass; the posting would write it
            # a second time.
            post_the_change=False,
        )


async def post_movement_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    quantity: Decimal,
    *,
    from_location_id: UUID | None = None,
    to_location_id: UUID | None = None,
    lot_id: UUID | None = None,
    owner_id: UUID | None = None,
    require_active_lot: bool = True,
    reference_type: str,
    reference_id: UUID,
    created_by: UUID | None = None,
    records: Sequence[RecordPostDTO] = (),
) -> list[QuantConsumption]:
    """State the records handed over and write the movement — one pass.

    The records are the state, the movement is the journal line explaining
    how the state got there; a caller that writes one without the other is
    what the reconciliation's shelf-versus-ledger pair measures. This writes
    both, under the anchor locks it takes up front, and states the records
    the caller hands over (``records``) in the same pass — the doors used to
    change them on their own before the locks were taken.

    - *to* only — goods arrive: one movement in;
    - *from* only — goods leave: one movement out;
    - both — goods change shelves: one movement from one to the other.

    What leaves is the grain the caller names — the shelf *from*, the batch
    *lot_id* (the batch-less stock when it is None) and the owner *owner_id*
    — and once the records are stated it must still cover its reservation
    rows, or the pass refuses (``NOT_ENOUGH``) and the caller's transaction
    takes it all back. *require_active_lot* is for a named batch only:
    carrying a held batch into quarantine is the point of having one,
    consuming it is not. *owner_id* is whose goods move, at both ends — a
    consignor's stays the consignor's on the new shelf; without it, the
    organization's own.

    Valuation is not written here: what a movement costs differs by who
    moves it (a receipt's price, a run's cost, a transfer's nothing) and
    stays with the caller. Returns what was posted.
    """
    if from_location_id is None and to_location_id is None:
        # A call without either end is the caller's bug, not a refusal a
        # user could meet, so it is a TypeError like any missing argument.
        raise TypeError('post_movement_async needs from_location_id or to_location_id')

    # Both ends before either is written: a move from A to B taking A and
    # then B met a move from B to A holding B and waiting for A.
    await lock_stock_async(
        db,
        organization_id,
        keys=[
            (product_template_id, location)
            for location in (from_location_id, to_location_id)
            if location is not None
        ],
    )

    if from_location_id is not None and lot_id is not None and require_active_lot:
        await assert_lot_consumable_async(db, lot_id, organization_id)

    # The records' numbers are stated inside the locks, beside the movement
    # they are one operation with.
    await _write_the_records(db, organization_id, records, created_by)
    if from_location_id is not None:
        await _refuse_a_grain_left_short_async(
            db,
            organization_id,
            product_template_id,
            (from_location_id, lot_id, owner_id),
            quantity,
        )

    from app.services import stock_moves_service

    await stock_moves_service.record_async(
        db,
        organization_id=organization_id,
        product_template_id=product_template_id,
        quantity=quantity,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        lot_id=lot_id,
        owner_id=owner_id,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by=created_by,
    )
    return [
        QuantConsumption(
            lot_id=lot_id,
            consumed=quantity,
            storage_location_id=from_location_id or to_location_id,
            owner_id=owner_id,
        )
    ]
