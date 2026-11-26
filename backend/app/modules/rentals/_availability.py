"""What is free when — the one answer every screen and every check reads.

Busy time of an asset is the window of every booking unit it is named in,
widened by its buffer, plus its blocks and any hand-out the equipment module
made outside a booking. Availability of a model is its units that are not
retired, minus the busy ones, minus what other model bookings still hold as
a count (a model line is a promise of *some* unit until pickup resolves it).

Everything here is pure over one loaded ``World``: the write path loads it
inside the transaction that holds the locks, checks, and writes; the check
endpoint loads the same world and writes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.public_api import core_api
from app.modules.equipment.equipment_api import EquipmentAssetDTO, equipment_api

from .models import RentalBlock, RentalBooking, RentalBookingLine, RentalBufferRule
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
    """One busy stretch on one asset, and what put it there."""

    kind: str
    starts_at: datetime
    ends_at: datetime
    label: str = ''
    reason: str | None = None
    booking_id: UUID | None = None


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
        for rule in self.buffers:
            if rule.model == model:
                return rule.hours_before, rule.hours_after
        return 0, 0


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
) -> World:
    """Load every busy interval that can touch ``[starts_at, ends_at)``."""
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

    max_buffer = max(
        (max(rule.hours_before, rule.hours_after) for rule in buffers),
        default=0,
    )
    pad = timedelta(hours=max_buffer + 1)
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
                    RentalBooking.starts_at < ends_at + pad,
                    RentalBooking.ends_at > starts_at - pad,
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
                    RentalBlock.starts_at < ends_at,
                    RentalBlock.ends_at > starts_at,
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
                starts_at=booking.starts_at - timedelta(hours=before),
                ends_at=booking.starts_at,
                label='',
                booking_id=booking.id,
            )
        )
    if after:
        world.slots_by_item.setdefault(item_id, []).append(
            Slot(
                kind='buffer',
                starts_at=booking.ends_at,
                ends_at=booking.ends_at + timedelta(hours=after),
                label='',
                booking_id=booking.id,
            )
        )


def _add_booking_slots(
    world: World, bookings: list[RentalBooking], now: datetime
) -> None:
    for booking in bookings:
        active = booking.status in ACTIVE_STATUSES
        kind = _booking_kind(booking, now)
        for unit in booking.units:
            held_asset = world.assets_by_id.get(unit.item_id)
            if held_asset is None:
                continue
            world.slots_by_item.setdefault(unit.item_id, []).append(
                Slot(
                    kind=kind,
                    starts_at=booking.starts_at,
                    ends_at=booking.ends_at,
                    label=booking.borrower_name,
                    booking_id=booking.id,
                )
            )
            if active:
                _add_buffer_slots(world, booking, unit.item_id, held_asset)


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
    rental_holds = {unit.item_id for booking in bookings for unit in booking.units}
    for asset in world.assets:
        if asset.assignment_id is None or asset.id in rental_holds:
            continue
        ends = asset.assignment_expected_return_at or ends_at
        world.slots_by_item.setdefault(asset.id, []).append(
            Slot(
                kind='out',
                starts_at=min(asset.assignment_started_at or now, ends),
                ends_at=ends,
                label=asset.holder_name or '',
                reason='manual',
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
        and _overlaps(slot.starts_at, slot.ends_at, starts_at, ends_at)
    ]


def model_pool(
    world: World,
    model: str | None,
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_booking_id: UUID | None = None,
) -> PoolResult:
    units = world.assets_by_model.get(model, [])
    busy: list[tuple[EquipmentAssetDTO, list[Slot]]] = []
    for unit in units:
        conflicts = item_conflicts(
            world,
            unit.id,
            starts_at,
            ends_at,
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
            before, after = world.buffer_for_model(model or '')
            if _overlaps(
                booking.starts_at - timedelta(hours=before),
                booking.ends_at + timedelta(hours=after),
                starts_at,
                ends_at,
            ):
                waiting.append((booking, line))
    physically_free = max(0, len(units) - len(busy))
    held = sum(line.unresolved_count for _booking, line in waiting)
    return PoolResult(
        units=units,
        busy=busy,
        waiting=waiting,
        physically_free=physically_free,
        free=max(0, physically_free - held),
    )


def _slot_detail(slot: Slot, asset: EquipmentAssetDTO | None = None) -> ConflictDetail:
    return ConflictDetail(
        item_id=asset.id if asset is not None else None,
        item_name=asset.name if asset is not None else None,
        kind=slot.kind,
        label=slot.label,
        starts_at=slot.starts_at,
        ends_at=slot.ends_at,
        booking_id=slot.booking_id,
        reason=slot.reason,
    )


def check_line(
    world: World,
    line: BookingLineIn,
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_booking_id: UUID | None = None,
) -> LineCheck:
    """Whether one line fits the window, what is in the way, and the way out."""
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
        own = item_conflicts(
            world,
            asset.id,
            starts_at,
            ends_at,
            exclude_booking_id=exclude_booking_id,
        )
        conflicts.extend(_slot_detail(slot, asset) for slot in own)
        pool = model_pool(
            world,
            asset.model,
            starts_at,
            ends_at,
            exclude_booking_id=exclude_booking_id,
        )
        # The asset may be idle and still be spoken for: the free pool is
        # what model bookings have not claimed yet.
        if not own and pool.free < 1:
            conflicts.append(
                ConflictDetail(
                    item_id=asset.id,
                    item_name=asset.name,
                    kind='model_booking',
                    label='',
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
        world, model, starts_at, ends_at, exclude_booking_id=exclude_booking_id
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
    )
    return check


def nearest_window(
    world: World,
    line: BookingLineIn,
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_booking_id: UUID | None = None,
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
        )
        if check.ok:
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
    results: list[LineCheck] = []
    for index, line in enumerate(lines):
        check = check_line(
            world,
            line,
            starts_at,
            ends_at,
            exclude_booking_id=exclude_booking_id,
        )
        check.index = index
        results.append(
            attach_way_out(
                world,
                check,
                line,
                starts_at,
                ends_at,
                exclude_booking_id=exclude_booking_id,
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
            clipped = _clip(slot.starts_at, slot.ends_at, world)
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


def _mark_service_units(world: World, groups: dict[str | None, CalendarGroup]) -> None:
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
    for group in groups.values():
        group.units.sort(key=lambda unit: unit.name)
        group.service_units = sum(
            1 for unit in group.units if unit.item_id in service_ids
        )


def build_calendar(world: World) -> CalendarResponse:
    """Rows grouped by model, with the unresolved model bookings in their own row."""
    groups: dict[str | None, CalendarGroup] = {}
    ordered_models = sorted(
        world.assets_by_model, key=lambda model: (model is None, model or '')
    )
    for model in ordered_models:
        units = world.assets_by_model[model]
        groups[model] = CalendarGroup(
            model=model,
            total_units=len(units),
            service_units=0,
            units=_unit_rows(world, units),
            any_unit=[],
        )

    _add_any_unit_rows(world, groups)
    _add_buffer_bars(world, groups)
    _mark_service_units(world, groups)

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
