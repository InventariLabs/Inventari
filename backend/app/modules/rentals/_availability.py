"""What is free when — the one answer every screen and every check reads.

Busy time of an asset is the window of every booking unit it is named in
(starting earlier when it was handed out early, and widened by its buffer),
plus its blocks and any hand-out the equipment module made outside a booking.
Availability of a model is its units that are not retired, minus the busy
ones, minus what other model bookings still hold as a count (a model line is a
promise of *some* unit until pickup resolves it).

Everything here is pure over one loaded ``World``: the write path loads it
inside the transaction that holds the locks, checks, and writes; the check
endpoint loads the same world and writes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.public_api import core_api
from app.modules.equipment.equipment_api import EquipmentAssetDTO, equipment_api

from .models import (
    RentalBlock,
    RentalBooking,
    RentalBookingLine,
    RentalBookingUnit,
    RentalBufferRule,
)
from .schemas import (
    BookingLineIn,
    CalendarAnyUnit,
    CalendarBar,
    CalendarGroup,
    CalendarResponse,
    CalendarUnit,
    ConflictDetail,
    LineCheck,
    WindowSuggestion,
)

ACTIVE_STATUSES = ('RESERVED', 'PICKED_UP')
#: How far the sheet may look for a free window of the same length.
NEAREST_HORIZON_DAYS = 60


@dataclass
class Slot:
    """One busy stretch on one asset, and what put it there.

    ``open_ended`` marks a loan that should have come back and has not: it
    holds the asset until the return is recorded, so no future window can
    promise that unit, while the calendar draws the hold only up to now.
    """

    kind: str
    starts_at: datetime
    ends_at: datetime
    label: str = ''
    reason: str | None = None
    booking_id: UUID | None = None
    open_ended: bool = False

    def covers(self, starts_at: datetime, ends_at: datetime) -> bool:
        """Whether this hold overlaps ``[starts_at, ends_at)``."""
        end = datetime.max.replace(tzinfo=UTC) if self.open_ended else self.ends_at
        return self.starts_at < ends_at and starts_at < end


@dataclass
class PoolResult:
    units: list[EquipmentAssetDTO]
    busy: list[tuple[EquipmentAssetDTO, list[Slot]]]
    waiting: list[tuple[RentalBooking, RentalBookingLine]]
    physically_free: int
    free: int


@dataclass
class World:
    organization_id: UUID
    starts_at: datetime
    ends_at: datetime
    now: datetime
    assets: list[EquipmentAssetDTO] = field(default_factory=list)
    assets_by_id: dict[UUID, EquipmentAssetDTO] = field(default_factory=dict)
    assets_by_model: dict[str | None, list[EquipmentAssetDTO]] = field(
        default_factory=dict
    )
    buffers: list[RentalBufferRule] = field(default_factory=list)
    bookings: list[RentalBooking] = field(default_factory=list)
    blocks: list[RentalBlock] = field(default_factory=list)
    slots_by_item: dict[UUID, list[Slot]] = field(default_factory=dict)

    def buffer_for(self, asset: EquipmentAssetDTO) -> tuple[int, int]:
        """The buffer an asset gets: its model's rule, else its category's."""
        if asset.model:
            for rule in self.buffers:
                if rule.model == asset.model:
                    return rule.hours_before, rule.hours_after
        if asset.category_id:
            for rule in self.buffers:
                if rule.category_id == asset.category_id:
                    return rule.hours_before, rule.hours_after
        return 0, 0

    def buffer_for_model(self, model: str) -> tuple[int, int]:
        """The buffer a model booking gets: its model's rule, else its units' categories.

        A model line promises *some* unit of the model, so until pickup it can
        land on any of them. Where no model rule names the model, the widest
        category rule among its units answers for the whole promise; a rule
        read only for model rows would let a category buffer go unapplied.
        """
        for rule in self.buffers:
            if rule.model == model:
                return rule.hours_before, rule.hours_after
        category_ids = {
            unit.category_id
            for unit in self.assets_by_model.get(model, [])
            if unit.category_id is not None
        }
        before = after = 0
        matched = False
        for rule in self.buffers:
            if rule.category_id in category_ids:
                matched = True
                before = max(before, rule.hours_before)
                after = max(after, rule.hours_after)
        return (before, after) if matched else (0, 0)


def _overlaps(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> bool:
    return a_start < b_end and b_start < a_end


async def load_world(
    db: AsyncSession,
    org_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
    *,
    include_returned: bool = True,
    cover_bookings: bool = False,
) -> World:
    """Load every busy interval that can touch ``[starts_at, ends_at)``.

    ``cover_bookings`` widens what is loaded to the whole window of every
    active booking the asked window touches. A model line promises *some*
    unit for its whole window, so a stretch on one day can take the unit that
    booking needs on another; the pool must see the other busy stretches of
    that booking's window to answer it.
    """
    now = datetime.now(UTC)
    assets = await equipment_api.list_bookable_assets_async(db, org_id)
    buffers = list(
        (
            await db.execute(
                select(RentalBufferRule).where(
                    RentalBufferRule.organization_id == org_id
                )
            )
        )
        .scalars()
        .all()
    )
    max_buffer = max(
        (max(rule.hours_before, rule.hours_after) for rule in buffers),
        default=0,
    )
    pad = timedelta(hours=max_buffer + 1)
    # ``RentalBooking.held_from`` in SQL: LEAST skips a hand-out not yet made.
    held_from = func.least(RentalBooking.starts_at, RentalBooking.picked_up_at)
    load_start, load_end = starts_at, ends_at
    if cover_bookings:
        span = (
            await db.execute(
                select(
                    func.min(held_from),
                    func.max(RentalBooking.ends_at),
                ).where(
                    RentalBooking.organization_id == org_id,
                    RentalBooking.status.in_(ACTIVE_STATUSES),
                    held_from < ends_at + pad,
                    RentalBooking.ends_at > starts_at - pad,
                )
            )
        ).one()
        if span[0] is not None:
            load_start = min(load_start, span[0])
            load_end = max(load_end, span[1])

    world = World(
        organization_id=org_id,
        starts_at=starts_at,
        ends_at=ends_at,
        now=now,
        assets=assets,
        buffers=buffers,
    )
    world.assets_by_id = {asset.id: asset for asset in assets}
    for asset in assets:
        world.assets_by_model.setdefault(asset.model, []).append(asset)
    for model_assets in world.assets_by_model.values():
        model_assets.sort(key=lambda asset: asset.name)

    statuses = list(ACTIVE_STATUSES)
    if include_returned:
        statuses.append('RETURNED')
    bookings = list(
        (
            await db.execute(
                select(RentalBooking)
                .options(
                    selectinload(RentalBooking.lines).selectinload(
                        RentalBookingLine.units
                    ),
                    selectinload(RentalBooking.units),
                )
                .where(
                    RentalBooking.organization_id == org_id,
                    RentalBooking.status.in_(statuses),
                    or_(
                        and_(
                            held_from < load_end + pad,
                            RentalBooking.ends_at > load_start - pad,
                        ),
                        # A loan past its due date is still out, so it holds
                        # its unit for a window that starts after that date.
                        and_(
                            RentalBooking.status == 'PICKED_UP',
                            RentalBooking.ends_at < now,
                        ),
                    ),
                )
                .order_by(RentalBooking.starts_at)
            )
        )
        .unique()
        .scalars()
        .all()
    )
    blocks = list(
        (
            await db.execute(
                select(RentalBlock).where(
                    RentalBlock.organization_id == org_id,
                    RentalBlock.starts_at < load_end + pad,
                    RentalBlock.ends_at > load_start - pad,
                )
            )
        )
        .scalars()
        .all()
    )
    world.bookings = bookings
    world.blocks = blocks

    _add_booking_slots(world, bookings, now)
    _add_block_slots(world, blocks)
    _add_manual_handouts(world, bookings, ends_at, now)

    for slots in world.slots_by_item.values():
        slots.sort(key=lambda slot: slot.starts_at)
    return world


def _booking_kind(booking: RentalBooking, now: datetime) -> str:
    if booking.status == 'RETURNED':
        return 'returned'
    if booking.status == 'PICKED_UP':
        return 'late' if booking.ends_at < now else 'out'
    return 'reserved'


def _add_buffer_slots(
    world: World, booking: RentalBooking, item_id: UUID, asset: EquipmentAssetDTO
) -> None:
    before, after = world.buffer_for(asset)
    if before:
        world.slots_by_item.setdefault(item_id, []).append(
            Slot(
                kind='buffer',
                starts_at=booking.held_from - timedelta(hours=before),
                ends_at=booking.held_from,
                label=booking.borrower_name,
                booking_id=booking.id,
            )
        )
    if after:
        world.slots_by_item.setdefault(item_id, []).append(
            Slot(
                kind='buffer',
                starts_at=booking.ends_at,
                ends_at=booking.ends_at + timedelta(hours=after),
                label=booking.borrower_name,
                booking_id=booking.id,
            )
        )


def _add_booking_slots(
    world: World, bookings: list[RentalBooking], now: datetime
) -> None:
    for booking in bookings:
        active = booking.status in ACTIVE_STATUSES
        kind = _booking_kind(booking, now)
        # A picked-up loan holds its unit until the return is recorded, and
        # the late state is what says so. A reservation holds only its window.
        open_ended = booking.status == 'PICKED_UP' and booking.ends_at < now
        for unit in booking.units:
            held_asset = world.assets_by_id.get(unit.item_id)
            if held_asset is None:
                continue
            if booking.status == 'PICKED_UP' and unit.returned_at is not None:
                # A partly returned booking keeps its status while the rest
                # is out; the unit that came back is free from that moment.
                world.slots_by_item.setdefault(unit.item_id, []).append(
                    Slot(
                        kind='returned',
                        starts_at=booking.held_from,
                        ends_at=unit.returned_at,
                        label=booking.borrower_name,
                        booking_id=booking.id,
                    )
                )
                continue
            if open_ended:
                # The loan up to its due date is drawn as handed out, and the
                # late stretch from there to now as a hold of its own.
                slots = [
                    Slot(
                        kind='out',
                        starts_at=booking.held_from,
                        ends_at=booking.ends_at,
                        label=booking.borrower_name,
                        booking_id=booking.id,
                    ),
                    Slot(
                        kind='late',
                        starts_at=booking.ends_at,
                        ends_at=now,
                        label=booking.borrower_name,
                        booking_id=booking.id,
                        open_ended=True,
                    ),
                ]
            else:
                slots = [
                    Slot(
                        kind=kind,
                        starts_at=booking.held_from,
                        ends_at=booking.ends_at,
                        label=booking.borrower_name,
                        booking_id=booking.id,
                    )
                ]
            for slot in slots:
                world.slots_by_item.setdefault(unit.item_id, []).append(slot)
            if active:
                _add_buffer_slots(world, booking, unit.item_id, held_asset)


def add_picked_up_booking(
    world: World, booking: RentalBooking, units: list[RentalBookingUnit]
) -> None:
    """Put a booking being handed out into the world as it will be stored.

    The world is read before the scans are pinned, so the booking still reads
    as a promise waiting for its count while the unit it resolves reads free,
    and an early hand-out still reads as starting with the window. Asking
    another promise about such a world would count one resolution twice and
    miss the time before the window. Here each scan resolves its line, and
    every unit is held from the hand-out on.
    """
    lines = {line.id: line for line in booking.lines}
    for unit in units:
        line = lines.get(unit.line_id)
        if line is not None:
            line.units.append(unit)
        booking.units.append(unit)
    for item_id, slots in world.slots_by_item.items():
        world.slots_by_item[item_id] = [
            slot for slot in slots if slot.booking_id != booking.id
        ]
    _add_booking_slots(world, [booking], world.now)


def add_extended_booking(
    world: World, booking: RentalBooking, ends_at: datetime
) -> None:
    """Put a booking's longer stay into the world before its tail is judged.

    The world was read with the window the booking is stored with, so its
    units still read free on the days this extension wants. Judging the units
    one at a time would let a pair of them take the units a model promise
    needs for the whole of its own window.
    """
    kind = _booking_kind(booking, world.now)
    for unit in booking.units:
        if unit.returned_at is not None:
            continue
        asset = world.assets_by_id.get(unit.item_id)
        if asset is None:
            continue
        world.slots_by_item.setdefault(unit.item_id, []).append(
            Slot(
                kind=kind,
                starts_at=booking.ends_at,
                ends_at=ends_at,
                label=booking.borrower_name,
                booking_id=booking.id,
            )
        )
        _before, after = world.buffer_for(asset)
        if after:
            world.slots_by_item[unit.item_id].append(
                Slot(
                    kind='buffer',
                    starts_at=ends_at,
                    ends_at=ends_at + timedelta(hours=after),
                    label=booking.borrower_name,
                    booking_id=booking.id,
                )
            )


def _add_block_slots(world: World, blocks: list[RentalBlock]) -> None:
    for block in blocks:
        if block.item_id not in world.assets_by_id:
            continue
        world.slots_by_item.setdefault(block.item_id, []).append(
            Slot(
                kind='block',
                starts_at=block.starts_at,
                ends_at=block.ends_at,
                label=block.reason,
                reason=block.reason,
                booking_id=block.booking_id,
            )
        )


def _add_manual_handouts(
    world: World,
    bookings: list[RentalBooking],
    ends_at: datetime,
    now: datetime,
) -> None:
    """A hand-out the register made outside a booking still holds the asset."""
    # Only the assignment a booking opened *is* that booking's hold. Any
    # other open assignment on the asset — a hand-out made after an early
    # return, or beside a reservation — is a hold of its own and is drawn.
    rental_holds = {
        unit.assignment_id
        for booking in bookings
        if booking.status == 'PICKED_UP'
        for unit in booking.units
        if unit.assignment_id is not None
    }
    for asset in world.assets:
        if asset.assignment_id is None or asset.assignment_id in rental_holds:
            continue
        expected = asset.assignment_expected_return_at
        # An open hand-out past its expected return is still out; it holds
        # the asset until the register records the check-in.
        open_ended = expected is None or expected < now
        ends = expected or ends_at
        world.slots_by_item.setdefault(asset.id, []).append(
            Slot(
                kind='out',
                starts_at=min(asset.assignment_started_at or now, ends),
                ends_at=ends,
                label=asset.holder_name or '',
                reason='manual',
                open_ended=open_ended,
            )
        )


def item_conflicts(
    world: World,
    item_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_booking_id: UUID | None = None,
) -> list[Slot]:
    return [
        slot
        for slot in world.slots_by_item.get(item_id, [])
        if slot.kind != 'returned'
        and not (
            exclude_booking_id is not None and slot.booking_id == exclude_booking_id
        )
        and slot.covers(starts_at, ends_at)
    ]


def item_busy_conflicts(
    world: World,
    item_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_booking_id: UUID | None = None,
) -> list[Slot]:
    """Conflicts for a booking that also needs its own buffer around the window."""
    asset = world.assets_by_id.get(item_id)
    before, after = world.buffer_for(asset) if asset is not None else (0, 0)
    return item_conflicts(
        world,
        item_id,
        starts_at - timedelta(hours=before),
        ends_at + timedelta(hours=after),
        exclude_booking_id=exclude_booking_id,
    )


def model_pool(
    world: World,
    model: str | None,
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_booking_id: UUID | None = None,
    busy_before: int | None = None,
    busy_after: int | None = None,
    taken: int = 0,
    pinned_beside: frozenset[UUID] = frozenset(),
) -> PoolResult:
    """What a window of this model can promise, buffers included.

    ``busy_before``/``busy_after`` widen the window for the caller's own
    buffer when it differs from the model's (a specific unit's category).
    ``taken`` counts units already promised by the caller's own request (a
    sibling model line), and ``pinned_beside`` names the units its sibling
    lines pin. No pool query can see either before the booking exists. A
    pinned unit that is busy for this window anyway takes nothing more.
    """
    model_before, model_after = world.buffer_for_model(model or '')
    before = model_before if busy_before is None else busy_before
    after = model_after if busy_after is None else busy_after
    window_start = starts_at - timedelta(hours=before)
    window_end = ends_at + timedelta(hours=after)
    units = world.assets_by_model.get(model, [])
    busy: list[tuple[EquipmentAssetDTO, list[Slot]]] = []
    for unit in units:
        conflicts = item_conflicts(
            world,
            unit.id,
            window_start,
            window_end,
            exclude_booking_id=exclude_booking_id,
        )
        if conflicts:
            busy.append((unit, conflicts))
    waiting: list[tuple[RentalBooking, RentalBookingLine]] = []
    for booking in world.bookings:
        if booking.id == exclude_booking_id:
            continue
        if booking.status not in ACTIVE_STATUSES:
            continue
        for line in booking.lines:
            if line.model != model or line.unresolved_count <= 0:
                continue
            if _overlaps(
                booking.starts_at - timedelta(hours=model_before),
                booking.ends_at + timedelta(hours=model_after),
                window_start,
                window_end,
            ):
                waiting.append((booking, line))
    physically_free = max(0, len(units) - len(busy))
    held = _peak_promise_demand(
        waiting, window_start, window_end, model_before, model_after
    )
    busy_ids = {unit.id for unit, _slots in busy}
    beside = sum(
        1 for unit in units if unit.id in pinned_beside and unit.id not in busy_ids
    )
    # The excluded booking's own pinned units are committed to its other
    # lines, so its remaining model promise cannot count on them.
    own_taken = 0
    if exclude_booking_id is not None:
        excluded = next(
            (booking for booking in world.bookings if booking.id == exclude_booking_id),
            None,
        )
        if excluded is not None:
            own_taken = sum(
                1
                for unit in excluded.units
                if unit.returned_at is None
                and unit.item_id not in busy_ids
                and unit.item_id in world.assets_by_id
                and world.assets_by_id[unit.item_id].model == model
            )
    return PoolResult(
        units=units,
        busy=busy,
        waiting=waiting,
        physically_free=physically_free,
        free=max(0, physically_free - held - own_taken - taken - beside),
    )


def _peak_promise_demand(
    waiting: list[tuple[RentalBooking, RentalBookingLine]],
    window_start: datetime,
    window_end: datetime,
    model_before: int,
    model_after: int,
) -> int:
    """How many units the promises hold at the busiest moment of the window.

    Promises that never overlap each other never compete for the same unit:
    two bookings on Monday and two on Wednesday leave the fleet free on
    Tuesday, and a week-long booking fits between them. Summing them as if
    they all ran at once would answer "nothing is free" for a fleet that is
    half idle every day.
    """
    events: list[tuple[datetime, int]] = []
    for booking, line in waiting:
        start = max(booking.starts_at - timedelta(hours=model_before), window_start)
        end = min(booking.ends_at + timedelta(hours=model_after), window_end)
        if end <= start:
            continue
        count = line.unresolved_count
        events.append((start, count))
        events.append((end, -count))
    # Half-open windows: an end at the instant another promise starts leaves
    # the two non-overlapping, so ends are applied before starts.
    events.sort(key=lambda event: (event[0], event[1]))
    peak = current = 0
    for _moment, delta in events:
        current += delta
        peak = max(peak, current)
    return peak


@dataclass
class DisplacedBooking:
    """A booking a new busy stretch would take the asset from.

    ``unit`` is the specific unit the booking pinned; ``None`` means the
    booking is a model-line promise that would be left one unit short.
    """

    booking: RentalBooking
    unit: RentalBookingUnit | None
    line: RentalBookingLine | None


def displaced_bookings(
    world: World,
    item_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_booking_id: UUID | None = None,
    taken: int = 0,
    pinned_beside: frozenset[UUID] = frozenset(),
) -> list[DisplacedBooking]:
    """Bookings that this busy stretch on one asset would break.

    ``taken`` and ``pinned_beside`` are what the same request takes beside this
    unit (see ``model_pool``). A booking that names the unit is broken when the
    stretch meets its hold: its window, its buffers, the time since an early
    hand-out, and everything from the due date on while it is overdue.
    """
    asset = world.assets_by_id.get(item_id)
    if asset is None:
        return []
    model_before, model_after = world.buffer_for_model(asset.model or '')
    displaced: list[DisplacedBooking] = []
    for booking in world.bookings:
        if booking.id == exclude_booking_id:
            continue
        if booking.status not in ACTIVE_STATUSES:
            continue
        pinned = next((unit for unit in booking.units if unit.item_id == item_id), None)
        if pinned is not None:
            if any(
                slot.booking_id == booking.id
                for slot in item_conflicts(world, item_id, starts_at, ends_at)
            ):
                line = next(
                    (line for line in booking.lines if line.id == pinned.line_id),
                    None,
                )
                displaced.append(DisplacedBooking(booking, pinned, line))
            continue
        if asset.model is None:
            continue
        lines = [
            line
            for line in booking.lines
            if line.model == asset.model and line.unresolved_count > 0
        ]
        if not lines:
            continue
        if not _overlaps(
            booking.starts_at - timedelta(hours=model_before),
            booking.ends_at + timedelta(hours=model_after),
            starts_at,
            ends_at,
        ):
            continue
        pool = model_pool(
            world,
            asset.model,
            booking.starts_at,
            booking.ends_at,
            exclude_booking_id=booking.id,
            taken=taken,
            pinned_beside=pinned_beside,
        )
        # A unit that is already busy for this booking is not taken from it
        # by the new stretch; only a free unit is.
        already_busy = {unit.id for unit, _slots in pool.busy}
        lost = 0 if item_id in already_busy else 1
        need = sum(line.unresolved_count for line in lines)
        if max(0, pool.free - lost) < need:
            displaced.append(DisplacedBooking(booking, None, lines[0]))
    return displaced


def promise_conflicts(
    world: World,
    item_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_booking_id: UUID | None = None,
    taken: int = 0,
    pinned_beside: frozenset[UUID] = frozenset(),
) -> list[DisplacedBooking]:
    """Model-line promises this busy stretch on one asset would leave short.

    A promise is judged over its own window, not over the stretch: taking a
    unit for one day breaks a week's booking if it was the last unit free for
    the whole week.
    """
    return [
        displaced
        for displaced in displaced_bookings(
            world,
            item_id,
            starts_at,
            ends_at,
            exclude_booking_id=exclude_booking_id,
            taken=taken,
            pinned_beside=pinned_beside,
        )
        if displaced.unit is None
    ]


def item_promise_conflicts(
    world: World,
    item_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_booking_id: UUID | None = None,
    taken: int = 0,
    pinned_beside: frozenset[UUID] = frozenset(),
) -> list[DisplacedBooking]:
    """Promises a booking of this unit for this window would leave short.

    The unit is held for its buffer on both sides of the window as well as the
    window itself, so a stretch that reaches a promised unit only through that
    buffer still takes it. Blocks carry no buffer and the extension adds its
    after-buffer itself, which is why the widening lives here rather than in
    ``displaced_bookings``.
    """
    asset = world.assets_by_id.get(item_id)
    before, after = world.buffer_for(asset) if asset is not None else (0, 0)
    return promise_conflicts(
        world,
        item_id,
        starts_at - timedelta(hours=before),
        ends_at + timedelta(hours=after),
        exclude_booking_id=exclude_booking_id,
        taken=taken,
        pinned_beside=pinned_beside,
    )


def _slot_detail(slot: Slot, asset: EquipmentAssetDTO | None = None) -> ConflictDetail:
    return ConflictDetail(
        item_id=asset.id if asset is not None else None,
        item_name=asset.name if asset is not None else None,
        item_serial_number=asset.serial_number if asset is not None else None,
        kind=slot.kind,
        label=slot.label,
        starts_at=slot.starts_at,
        ends_at=slot.ends_at,
        booking_id=slot.booking_id,
        reason=slot.reason,
        # A slot starts when the unit really left: the booked window when
        # nobody came early, the hand-out when they did. An open-ended late
        # loan has no end until the return is recorded.
        held_from=slot.starts_at,
        held_until=None if slot.open_ended else slot.ends_at,
    )


def check_line(
    world: World,
    line: BookingLineIn,
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_booking_id: UUID | None = None,
    taken: int = 0,
    pinned_beside: frozenset[UUID] = frozenset(),
) -> LineCheck:
    """Whether one line fits the window, what is in the way, and the way out.

    ``taken`` and ``pinned_beside`` are what the request's sibling lines take
    of the same model, which only the caller that sees all lines knows (see
    ``model_pool``). A unit line needs them too: the unit it pins may be the
    one a promise no longer has room for once the siblings are pinned beside
    it.
    """
    conflicts: list[ConflictDetail] = []
    if line.item_id is not None:
        asset = world.assets_by_id.get(line.item_id)
        label = asset.name if asset is not None else ''
        if asset is None:
            conflicts.append(
                ConflictDetail(kind='missing', label=label or str(line.item_id))
            )
            return LineCheck(
                index=0,
                ok=False,
                label=label,
                requested=1,
                available=0,
                conflicts=conflicts,
            )
        own = item_busy_conflicts(
            world,
            asset.id,
            starts_at,
            ends_at,
            exclude_booking_id=exclude_booking_id,
        )
        conflicts.extend(_slot_detail(slot, asset) for slot in own)
        # The unit may be idle and still be the one a model line is counting
        # on for a window that reaches past this booking, buffer included.
        for displaced in item_promise_conflicts(
            world,
            asset.id,
            starts_at,
            ends_at,
            exclude_booking_id=exclude_booking_id,
            taken=taken,
            pinned_beside=pinned_beside,
        ):
            promised = displaced.booking
            conflicts.append(
                ConflictDetail(
                    item_id=asset.id,
                    item_name=asset.name,
                    item_serial_number=asset.serial_number,
                    kind='model_booking',
                    label=promised.borrower_name,
                    starts_at=promised.starts_at,
                    ends_at=promised.ends_at,
                    booking_id=promised.id,
                    reason=(
                        str(displaced.line.unresolved_count)
                        if displaced.line is not None
                        else None
                    ),
                )
            )
        ok = not conflicts
        return LineCheck(
            index=0,
            ok=ok,
            label=label,
            requested=1,
            available=1 if ok else 0,
            conflicts=conflicts,
            max_quantity=1 if ok else 0,
        )

    model = line.model
    label = f'{model} ×{line.quantity}'
    pool = model_pool(
        world,
        model,
        starts_at,
        ends_at,
        exclude_booking_id=exclude_booking_id,
        taken=taken,
        pinned_beside=pinned_beside,
    )
    for unit, slots in pool.busy:
        for slot in slots:
            conflicts.append(_slot_detail(slot, unit))
    for booking, waiting_line in pool.waiting:
        conflicts.append(
            ConflictDetail(
                kind='model_booking',
                label=booking.borrower_name,
                starts_at=booking.starts_at,
                ends_at=booking.ends_at,
                booking_id=booking.id,
                reason=str(waiting_line.unresolved_count),
            )
        )
    if not pool.units:
        conflicts.append(ConflictDetail(kind='no_units', label=model or ''))
    ok = pool.free >= line.quantity
    return LineCheck(
        index=0,
        ok=ok,
        label=label,
        requested=line.quantity,
        available=pool.free,
        conflicts=conflicts if not ok else [],
        max_quantity=pool.free,
    )


def attach_way_out(
    world: World,
    check: LineCheck,
    line: BookingLineIn,
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_booking_id: UUID | None = None,
    taken: int = 0,
    pinned_beside: frozenset[UUID] = frozenset(),
) -> LineCheck:
    """Fill the two ways out of a line that does not fit."""
    if check.ok:
        return check
    check.nearest_window = nearest_window(
        world,
        line,
        starts_at,
        ends_at,
        exclude_booking_id=exclude_booking_id,
        taken=taken,
        pinned_beside=pinned_beside,
    )
    return check


def nearest_window(
    world: World,
    line: BookingLineIn,
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_booking_id: UUID | None = None,
    taken: int = 0,
    pinned_beside: frozenset[UUID] = frozenset(),
) -> WindowSuggestion | None:
    """The nearest window of the same length in which the line fits."""
    duration = ends_at - starts_at
    horizon = min(
        world.ends_at - duration,
        starts_at + timedelta(days=NEAREST_HORIZON_DAYS),
    )
    cursor = starts_at
    checks = 0
    while cursor + duration <= horizon and checks < 24 * 30:
        candidate_end = cursor + duration
        check = check_line(
            world,
            line,
            cursor,
            candidate_end,
            exclude_booking_id=exclude_booking_id,
            taken=taken,
            pinned_beside=pinned_beside,
        )
        if check.ok:
            return WindowSuggestion(starts_at=cursor, ends_at=candidate_end)
        cursor += timedelta(hours=1)
        checks += 1
    return None


def nearest_window_for_lines(
    world: World,
    lines: list[BookingLineIn],
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_booking_id: UUID | None = None,
) -> WindowSuggestion | None:
    """The nearest window of the same length in which every line fits.

    A kit is handed out as one set, so its way out is a window where all its
    members are free together, not the first member's own nearest window.
    """
    duration = ends_at - starts_at
    horizon = min(
        world.ends_at - duration,
        starts_at + timedelta(days=NEAREST_HORIZON_DAYS),
    )
    cursor = starts_at
    checks = 0
    while cursor + duration <= horizon and checks < 24 * 30:
        candidate_end = cursor + duration
        world_checks = checks_for_lines(
            world,
            lines,
            cursor,
            candidate_end,
            exclude_booking_id=exclude_booking_id,
        )
        if all(check.ok for check in world_checks):
            return WindowSuggestion(starts_at=cursor, ends_at=candidate_end)
        cursor += timedelta(hours=1)
        checks += 1
    return None


def checks_for_lines(
    world: World,
    lines: list[BookingLineIn],
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_booking_id: UUID | None = None,
) -> list[LineCheck]:
    # A request's own lines compete for the same units: an asset line pins
    # one, a model line promises its count. Each line is judged against what
    # its siblings leave, not against the whole fleet — a pinned unit line
    # included, since two of them can take both units a promise counts on.
    promised: dict[str, int] = {}
    pinned: dict[str, set[UUID]] = {}
    for line in lines:
        if line.model is not None:
            promised[line.model] = promised.get(line.model, 0) + line.quantity
            continue
        asset = world.assets_by_id.get(line.item_id) if line.item_id else None
        if asset is not None and asset.model:
            pinned.setdefault(asset.model, set()).add(asset.id)
    seen_units: dict[UUID, int] = {}
    for line in lines:
        if line.item_id is not None:
            seen_units[line.item_id] = seen_units.get(line.item_id, 0) + 1
    results: list[LineCheck] = []
    for index, line in enumerate(lines):
        if line.model is not None:
            model = line.model
            taken = promised[model] - line.quantity
        else:
            asset = world.assets_by_id.get(line.item_id) if line.item_id else None
            model = asset.model or '' if asset is not None else ''
            taken = promised.get(model, 0)
        beside = frozenset(pinned.get(model, set()) - {line.item_id})
        check = check_line(
            world,
            line,
            starts_at,
            ends_at,
            exclude_booking_id=exclude_booking_id,
            taken=taken,
            pinned_beside=beside,
        )
        check.index = index
        if line.item_id is not None and seen_units.get(line.item_id, 0) > 1:
            asset = world.assets_by_id.get(line.item_id)
            check.ok = False
            check.available = 0
            check.max_quantity = 0
            check.nearest_window = None
            check.conflicts.append(
                ConflictDetail(
                    item_id=line.item_id,
                    item_name=asset.name if asset is not None else None,
                    item_serial_number=(
                        asset.serial_number if asset is not None else None
                    ),
                    kind='duplicate_unit',
                    label=asset.name if asset is not None else '',
                )
            )
        results.append(
            attach_way_out(
                world,
                check,
                line,
                starts_at,
                ends_at,
                exclude_booking_id=exclude_booking_id,
                taken=taken,
                pinned_beside=beside,
            )
        )
    return results


def _clip(
    starts_at: datetime, ends_at: datetime, world: World
) -> tuple[datetime, datetime] | None:
    start = max(starts_at, world.starts_at)
    end = min(ends_at, world.ends_at)
    if end <= start:
        return None
    return start, end


def _unit_rows(world: World, units: list[EquipmentAssetDTO]) -> list[CalendarUnit]:
    rows: list[CalendarUnit] = []
    for asset in units:
        bars: list[CalendarBar] = []
        for slot in world.slots_by_item.get(asset.id, []):
            # A late loan holds the unit for every future window, but the
            # timeline draws the stretch from its due date to now.
            displayed_end = world.now if slot.open_ended else slot.ends_at
            clipped = _clip(slot.starts_at, displayed_end, world)
            if clipped is None or slot.kind == 'buffer':
                continue
            bars.append(
                CalendarBar(
                    kind=slot.kind,
                    label=slot.label,
                    starts_at=clipped[0],
                    ends_at=clipped[1],
                    booking_id=slot.booking_id,
                )
            )
        rows.append(
            CalendarUnit(
                item_id=asset.id,
                name=asset.name,
                serial_number=asset.serial_number,
                asset_tag=asset.asset_tag,
                status=asset.status,
                bars=bars,
            )
        )
    return rows


def _add_any_unit_rows(world: World, groups: dict[str | None, CalendarGroup]) -> None:
    for booking in world.bookings:
        if booking.status not in ACTIVE_STATUSES:
            continue
        clipped = _clip(booking.starts_at, booking.ends_at, world)
        if clipped is None:
            continue
        for line in booking.lines:
            if line.model is None or line.unresolved_count <= 0:
                continue
            group = groups.get(line.model)
            if group is None:
                continue
            group.any_unit.append(
                CalendarAnyUnit(
                    booking_id=booking.id,
                    borrower_name=booking.borrower_name,
                    quantity=line.unresolved_count,
                    starts_at=clipped[0],
                    ends_at=clipped[1],
                    status=booking.status,
                )
            )


def _add_buffer_bars(world: World, groups: dict[str | None, CalendarGroup]) -> None:
    """Buffers are drawn in the row of the booking they belong to."""
    for group in groups.values():
        for unit in group.units:
            for slot in world.slots_by_item.get(unit.item_id, []):
                if slot.kind != 'buffer':
                    continue
                clipped = _clip(slot.starts_at, slot.ends_at, world)
                if clipped is None:
                    continue
                unit.bars.append(
                    CalendarBar(
                        kind='buffer',
                        label='',
                        starts_at=clipped[0],
                        ends_at=clipped[1],
                        booking_id=slot.booking_id,
                    )
                )
            unit.bars.sort(key=lambda bar: bar.starts_at)


def build_calendar(world: World) -> CalendarResponse:
    """Rows grouped by model, with the unresolved model bookings in their own row."""
    moment = (
        world.now if world.starts_at <= world.now < world.ends_at else world.starts_at
    )
    service_ids = {
        item_id
        for item_id, slots in world.slots_by_item.items()
        if any(
            slot.kind == 'block' and slot.starts_at <= moment < slot.ends_at
            for slot in slots
        )
    }
    groups: dict[str | None, CalendarGroup] = {}
    ordered_models = sorted(
        world.assets_by_model, key=lambda model: (model is None, model or '')
    )
    for model in ordered_models:
        units = world.assets_by_model[model]
        unit_rows = _unit_rows(world, units)
        groups[model] = CalendarGroup(
            model=model,
            total_units=len(units),
            service_units=sum(1 for unit in unit_rows if unit.item_id in service_ids),
            units=unit_rows,
            any_unit=[],
        )

    _add_any_unit_rows(world, groups)
    _add_buffer_bars(world, groups)

    return CalendarResponse(
        starts_at=world.starts_at,
        ends_at=world.ends_at,
        groups=list(groups.values()),
    )


async def organization_today(
    db: AsyncSession, org_id: UUID, now: datetime | None = None
) -> tuple[datetime, datetime]:
    """The organization's current local day, as the two instants that bound it."""
    tz = await core_api.organizations.timezone_async(db, org_id)
    local_now = (now or datetime.now(UTC)).astimezone(tz)
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return day_start, day_start + timedelta(days=1)
