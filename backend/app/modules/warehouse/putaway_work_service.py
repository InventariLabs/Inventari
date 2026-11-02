"""Putting away what a two-step warehouse received: the task and the move.

A receipt into a warehouse that receives in two steps leaves its goods in the
receiving area. Every receipt line whose goods still wait there is one
putaway task — "Put away 40 pcs Jasmine Rice to Shelf A - Top". Two lines of
one product, or two deliveries of it, share one stock record in the area,
but they stay two tasks: each is its own carry, and the shelf that had room
for the first may have none left for the second.

What a line still has waiting is what it received, less what the putaway
moves naming it took (``DocumentLine.puts_away_line_id``), and never more
than its record still holds: goods that left the area some other way — a
move typed by hand, a dispatch straight off the dock — end the oldest lines
first, the way the oldest goods leave first.

The suggested shelf is the putaway planner's, asked as if the waiting lines
were being received into the warehouse now, oldest first — the same rules,
the same capacity check, each line measured against a shelf that already
knows what the line before it was sent there. Where no rule names a shelf,
the task names none and the person putting the goods away chooses one.
Doing the task posts a transfer (MM) of that line's goods from the
receiving area through the one-step door, under every rule a transfer is
posted under.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ItemDTO
from app.core.exceptions import NotFoundException, ServiceRejectionError
from app.core.public_api import core_api
from app.i18n.service import get_current_lang

from . import document_types as dt
from ._receipt_planning import (
    _RECEIVED_FROM_SUPPLIERS,
    SOURCE_RULE,
    ReceiptLocationPlanner,
    most_stocked_shelf_async,
)
from ._receiving_area import list_receiving_modes_async
from ._schemas_work_items import WorkItemSchema
from .document_profile_service import get_profile
from .home_shelf_service import (
    home_refusal_async,
    home_shelf_offer_async,
    is_silenced_async,
)
from .models import Document, DocumentLine, DocumentStatus, WarehouseReceiving
from .putaway_schemas import HomeShelfOffer
from .schemas import DocumentCreate, DocumentLineCreate

#: ``source_kind`` of a putaway task: its ``source_id`` is the receipt line.
PUTAWAY_SOURCE_KIND = 'putaway'

#: A putaway move that holds its goods: posted, or on its way to being.
_UNDER_WAY = (
    DocumentStatus.PENDING_APPROVAL,
    DocumentStatus.CONFIRMED,
    DocumentStatus.COMPLETED,
)


def _goods(item: ItemDTO) -> tuple[UUID | None, UUID | None, date | None]:
    """What a record holds, as against which record holds it."""
    return item.template_id, item.lot_id, item.expiry_date


@dataclass(frozen=True)
class _Waiting:
    """One receipt line's goods still standing in a receiving area."""

    line_id: UUID
    #: The records in the area holding the same goods, the line's own first.
    #: A move of part of a record takes the record with it and leaves the
    #: rest behind as a new one, so the line cannot follow one record id.
    records: tuple[ItemDTO, ...]
    #: In the records' stock unit.
    quantity: Decimal
    number: str
    received_on: date

    @property
    def item(self) -> ItemDTO:
        return self.records[0]


async def _waiting_async(
    db: AsyncSession, org_id: UUID, area_id: UUID
) -> list[_Waiting]:
    """The receipt lines waiting in one receiving area, oldest first."""
    held: dict[tuple[UUID | None, UUID | None, date | None], list[ItemDTO]] = {}
    for item in await core_api.locations.list_items_in_location_async(
        db, org_id, area_id
    ):
        if (item.quantity or 0) > 0:
            held.setdefault(_goods(item), []).append(item)
    if not held:
        return []
    rows = (
        await db.execute(
            select(DocumentLine, Document.number, Document.completed_at)
            .join(Document, DocumentLine.document_id == Document.id)
            .where(
                Document.organization_id == org_id,
                Document.type.in_(_RECEIVED_FROM_SUPPLIERS),
                Document.status == DocumentStatus.COMPLETED,
                DocumentLine.executed_location_id == area_id,
                DocumentLine.product_template_id.in_({key[0] for key in held}),
            )
            .order_by(Document.completed_at, DocumentLine.line_number)
        )
    ).all()
    # A move waiting for approval has claimed its goods already: showing the
    # task again would invite a second carry of the same goods.
    moved = case(
        (Document.status == DocumentStatus.COMPLETED, DocumentLine.done_quantity),
        else_=DocumentLine.expected_quantity,
    )
    taken = dict(
        (
            await db.execute(
                select(DocumentLine.puts_away_line_id, func.sum(moved))
                .join(Document, DocumentLine.document_id == Document.id)
                .where(
                    Document.organization_id == org_id,
                    Document.status.in_(_UNDER_WAY),
                    DocumentLine.puts_away_line_id.in_([line.id for line, *_ in rows]),
                )
                .group_by(DocumentLine.puts_away_line_id)
            )
        )
        .tuples()
        .all()
    )

    # What each kind of goods still has to answer for, in the area: a line
    # claiming more than is left lost the difference some other way, and the
    # oldest goods are the ones that left.
    left_of = {
        key: sum((item.quantity or Decimal('0') for item in items), Decimal('0'))
        for key, items in held.items()
    }
    # Newest first, so what is left goes to the newest lines; and once every
    # kind of goods is answered for, the older lines cannot have anything
    # waiting, so they are never looked up.
    waiting: list[_Waiting] = []
    for line, number, completed_at in reversed(rows):
        if all(quantity <= 0 for quantity in left_of.values()):
            break
        origin = (
            await core_api.items.get_async(db, org_id, line.item_id)
            if line.item_id is not None
            else None
        )
        if origin is None:
            continue
        twins = held.get(_goods(origin))
        if twins is None:
            continue
        received = await core_api.uoms.to_stock_uom_async(
            db,
            org_id,
            origin.template_id,
            line.done_quantity - (line.held_quantity or Decimal('0')),
            line.uom_id,
        )
        claim = min(
            received - (taken.get(line.id) or Decimal('0')),
            left_of[_goods(origin)],
        )
        if claim > 0:
            left_of[_goods(origin)] -= claim
            waiting.append(
                _Waiting(
                    line_id=line.id,
                    records=tuple(sorted(twins, key=lambda item: item.id != origin.id)),
                    quantity=claim,
                    number=number,
                    received_on=completed_at.date() if completed_at else date.min,
                )
            )
    waiting.reverse()
    return waiting


def _task(
    entry: _Waiting,
    *,
    date_to: date,
    place_id: UUID | None,
    place: str | None,
    place_code: str | None = None,
    place_source: str | None = None,
    shelf_scan_required: bool = False,
) -> WorkItemSchema:
    item = entry.item
    return WorkItemSchema(
        key=f'{PUTAWAY_SOURCE_KIND}:{entry.line_id}',
        kind='putaway',
        state='todo',
        source_kind=PUTAWAY_SOURCE_KIND,
        source_id=entry.line_id,
        due_date=entry.received_on,
        overdue=entry.received_on < date_to,
        next_action='put_away',
        subject=item.template_name or item.name,
        number=entry.number,
        count=entry.quantity,
        unit=item.uom.symbol if item.uom is not None else item.uom_symbol,
        place=place,
        place_id=place_id,
        place_code=place_code,
        place_source=place_source,
        shelf_scan_required=shelf_scan_required,
    )


async def _offer_shelves_async(
    db: AsyncSession,
    org_id: UUID,
    *,
    warehouse_id: UUID,
    area_id: UUID,
) -> list[UUID]:
    """The shelves a task may be sent to: the warehouse's, without the area.

    The receiving area is the goods' current shelf, not an answer — offering
    it would send the worker back where they stand.
    """
    shelves = set(
        await core_api.locations.descendant_ids_async(db, org_id, warehouse_id)
    )
    shelves.discard(area_id)
    shelves.difference_update(
        await core_api.locations.descendant_ids_async(db, org_id, area_id)
    )
    return sorted(shelves)


async def _shelf_offer_async(
    db: AsyncSession,
    org_id: UUID,
    shelves: list[UUID],
    template_id: UUID | None,
) -> tuple[UUID, str] | None:
    """The shelf to offer when no rule names one: where the goods already lie,
    else the shelf the last move into this warehouse put goods on.

    ``None`` when the warehouse has no other shelf or nothing tells which
    one: the worker names one.
    """
    if not shelves:
        return None
    if template_id is not None:
        stocked = await most_stocked_shelf_async(db, org_id, shelves, template_id)
        if stocked is not None:
            return stocked, 'stock'
    last = await db.scalar(
        select(Document.target_location_id)
        .where(
            Document.organization_id == org_id,
            Document.type == dt.INT,
            Document.status == DocumentStatus.COMPLETED,
            Document.target_location_id.in_(shelves),
        )
        .order_by(Document.completed_at.desc().nulls_last())
        .limit(1)
    )
    return (last, 'zone') if last is not None else None


@dataclass(frozen=True)
class _Suggestion:
    """The shelf one waiting line is sent to, and who named it."""

    place_id: UUID | None
    #: ``rule``, ``stock`` or ``zone``; ``None`` when nothing names a shelf.
    source: str | None
    #: True when a rule named the shelf only because every shelf it lists is
    #: full: the goods have nowhere better to go, so a worker who carries them
    #: elsewhere says nothing about where the product belongs.
    over_capacity: bool = False


async def _suggest_area_async(
    db: AsyncSession,
    org_id: UUID,
    row: WarehouseReceiving,
    area_id: UUID,
    waiting: list[_Waiting],
) -> dict[UUID, _Suggestion]:
    """The shelf each line waiting in one receiving area is sent to.

    A receipt into the warehouse, never stored: the rules are asked the
    question a one-step receipt would have asked, line after line.
    """
    planner = await ReceiptLocationPlanner.for_document(
        db,
        Document(
            organization_id=org_id,
            type=dt.IN,
            target_location_id=row.warehouse_id,
        ),
    )
    shelves = await _offer_shelves_async(
        db,
        org_id,
        warehouse_id=row.warehouse_id,
        area_id=area_id,
    )
    offers: dict[UUID | None, tuple[UUID, str] | None] = {}
    suggestions: dict[UUID, _Suggestion] = {}
    for entry in waiting:
        decision = await planner.decide(
            named=entry.item,
            stock_template_id=entry.item.template_id,
            quantity_stock=entry.quantity,
        )
        if decision.source == SOURCE_RULE and decision.location_id != area_id:
            suggestions[entry.line_id] = _Suggestion(
                decision.location_id, 'rule', decision.over_capacity
            )
            continue
        # No rule names a shelf: offer where the product already lies,
        # else the shelf the last move into this warehouse used, else
        # nothing and the worker chooses.
        template_id = entry.item.template_id
        if template_id not in offers:
            offers[template_id] = await _shelf_offer_async(
                db, org_id, shelves, template_id
            )
        offer = offers[template_id]
        suggestions[entry.line_id] = (
            _Suggestion(offer[0], offer[1]) if offer else _Suggestion(None, None)
        )
    return suggestions


async def putaway_items_async(
    db: AsyncSession,
    org_id: UUID,
    *,
    date_to: date,
    limit: int,
    warehouse_ids: list[UUID] | None = None,
) -> tuple[list[WorkItemSchema], int]:
    """The goods waiting in every receiving area, oldest first, as tasks.

    ``warehouse_ids`` keeps only the areas of those warehouses.
    """
    profile = await get_profile(db, org_id)
    scan_the_shelf = bool(profile and profile.confirm_shelf_by_scan)
    tasks: list[WorkItemSchema] = []
    for row in await list_receiving_modes_async(db, org_id):
        area_id = row.receiving_location_id
        if area_id is None:
            continue
        if warehouse_ids is not None and row.warehouse_id not in warehouse_ids:
            continue
        waiting = await _waiting_async(db, org_id, area_id)
        if not waiting:
            continue
        suggestions = await _suggest_area_async(db, org_id, row, area_id, waiting)
        # Name and code of each shelf the tasks name, fetched once per area.
        places: dict[UUID, tuple[str | None, str | None]] = {}
        for entry in waiting:
            suggested = suggestions[entry.line_id].place_id
            if suggested is not None and suggested not in places:
                shelf = await core_api.locations.get_async(db, org_id, suggested)
                places[suggested] = (
                    shelf.name if shelf else None,
                    shelf.short_code if shelf else None,
                )
            place_name, place_code = (
                places[suggested] if suggested is not None else (None, None)
            )
            tasks.append(
                _task(
                    entry,
                    date_to=date_to,
                    place_id=suggested,
                    place=place_name,
                    place_code=place_code,
                    place_source=suggestions[entry.line_id].source,
                    shelf_scan_required=scan_the_shelf,
                )
            )
    tasks.sort(
        key=lambda task: (
            task.due_date is None,
            task.due_date or date.min,
            task.subject or '',
        )
    )
    return tasks[:limit], len(tasks)


def _move_lines(entry: _Waiting) -> list[DocumentLineCreate]:
    """The line's quantity, taken from its own record first, then its twins'."""
    lines: list[DocumentLineCreate] = []
    rest = entry.quantity
    for item in entry.records:
        take = min(rest, item.quantity or Decimal('0'))
        if take <= 0:
            continue
        lines.append(
            DocumentLineCreate(
                item_id=item.id,
                product_template_id=item.template_id,
                expected_quantity=take,
                uom_id=item.uom_id,
            )
        )
        rest -= take
    return lines


async def _home_shelf_offer_async(
    db: AsyncSession,
    org_id: UUID,
    *,
    area_id: UUID,
    waiting: list[_Waiting],
    entry: _Waiting,
    chosen_id: UUID,
) -> HomeShelfOffer | None:
    """Whether putting this line on ``chosen_id`` should ask about a home shelf.

    Never in a warehouse of free storage, never for a product the question was
    silenced for; and not when the worker was forced off the suggested shelf —
    it was full, or one goods cannot be put on.
    """
    template_id = entry.item.template_id
    row = next(
        (
            row
            for row in await list_receiving_modes_async(db, org_id)
            if row.receiving_location_id == area_id
        ),
        None,
    )
    if (
        template_id is None
        or row is None
        or row.free_placement
        or await is_silenced_async(db, org_id, template_id)
    ):
        return None
    suggestion = (await _suggest_area_async(db, org_id, row, area_id, waiting))[
        entry.line_id
    ]
    forced = suggestion.over_capacity or (
        suggestion.place_id is not None
        and await home_refusal_async(db, org_id, suggestion.place_id) is not None
    )
    return await home_shelf_offer_async(
        db,
        org_id,
        template_id=template_id,
        chosen_id=chosen_id,
        suggested_by_rule=suggestion.place_id if suggestion.source == 'rule' else None,
        forced=forced,
    )


async def put_away_async(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    line_id: UUID,
    *,
    location_id: UUID,
    scanned_code: str | None = None,
) -> tuple[Document, HomeShelfOffer | None]:
    """Carry what one receipt line left in its receiving area onto ``location_id``.

    Answers the posted move and what the put-away has to say about the shelf
    (``HomeShelfOffer``): the offer to make it the product's home.

    A line with nothing waiting — put away already, or never received into
    a receiving area — is no putaway task, and answers as one that does not
    exist. With the profile's ``confirm_shelf_by_scan`` on, ``scanned_code``
    has to resolve to ``location_id``: the label, not the screen, says the
    goods stand on the right shelf. The code is answered here rather than
    trusted from the request, so a scan cannot be skipped by a call that
    never made one.
    """
    from ._document_workflow_crud import create_document
    from ._document_workflow_transitions import post_document_now

    line = await db.get(DocumentLine, line_id)
    area_id = line.executed_location_id if line is not None else None
    waiting = await _waiting_async(db, org_id, area_id) if area_id is not None else []
    entry = next((entry for entry in waiting if entry.line_id == line_id), None)
    if entry is None or area_id is None:
        raise NotFoundException('work_item', get_current_lang())
    if location_id == area_id:
        raise ServiceRejectionError('putaway_needs_another_location')
    profile = await get_profile(db, org_id)
    if profile is not None and profile.confirm_shelf_by_scan:
        scanned = (
            await core_api.locations.find_by_scanned_code_async(
                db, org_id, scanned_code
            )
            if scanned_code
            else None
        )
        if scanned is None or scanned.id != location_id:
            raise ServiceRejectionError('putaway_shelf_scan_required')
    # Asked before the move: afterwards the line has nothing waiting, and the
    # shelf the rules suggested for it can no longer be told.
    offer = await _home_shelf_offer_async(
        db, org_id, area_id=area_id, waiting=waiting, entry=entry, chosen_id=location_id
    )
    doc = await create_document(
        db,
        org_id,
        DocumentCreate(
            type=dt.INT,
            source_location_id=area_id,
            target_location_id=location_id,
            lines=_move_lines(entry),
        ),
        user_id,
    )
    for move_line in doc.lines:
        move_line.puts_away_line_id = line_id
    return await post_document_now(db, org_id, doc.id, user_id), offer
