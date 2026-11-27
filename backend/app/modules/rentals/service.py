"""Bookings: create, check, hand out, take back, extend, cancel.

Every write that decides on free time takes an advisory lock first, loads the
world inside that lock, checks, and writes in the same transaction — the
booking, its lines and units, and the equipment hand-outs it opens. Two
requests for one asset and one window cannot both pass a check made before
the other's write (backend/AGENTS.md, and the test beside this file).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.contracts import AuditAction, AuditTargetType
from app.core.db_utils import acquire_advisory_lock, paginate_async
from app.core.module_sdk import (
    NotFoundException,
    ServiceRejectionError,
    get_current_lang,
)
from app.core.public_api import core_api
from app.modules.equipment.equipment_api import EquipmentAssetDTO, equipment_api

from ._availability import (
    ACTIVE_STATUSES,
    DisplacedBooking,
    Slot,
    World,
    add_extended_booking,
    add_picked_up_booking,
    build_calendar,
    checks_for_lines,
    displaced_bookings,
    item_busy_conflicts,
    item_promise_conflicts,
    load_world,
    model_pool,
    organization_today,
)
from ._blocks import block_schema
from .exceptions import RentalConflictError
from .models import (
    RentalBlock,
    RentalBooking,
    RentalBookingLine,
    RentalBookingUnit,
)
from .schemas import (
    BookingCheckResponse,
    BookingCreate,
    BookingListRow,
    BookingSchema,
    CalendarResponse,
    ExtendRequest,
    LineSchema,
    MoveIn,
    PickupRequest,
    ReturnRequest,
    TodayItem,
    TodayResponse,
    UnitSchema,
)

JOURNAL_TARGET = AuditTargetType.RENTAL_BOOKING


def _now() -> datetime:
    return datetime.now(UTC)


def _late_days(ends_at: datetime, now: datetime) -> int:
    """How many calendar days behind the promised return the loan is.

    The day after the due date is the first day late, so a loan due
    yesterday reads "1 day late" whether it is one hour or twenty behind.
    """
    if now <= ends_at:
        return 0
    days = (now.date() - ends_at.date()).days
    return max(1, days)


def _borrower_kind(booking: RentalBooking) -> str:
    if booking.borrower_partner_id is not None:
        return 'partner'
    if booking.borrower_user_id is not None:
        return 'user'
    return 'external'


async def _load_booking(
    db: AsyncSession, org_id: UUID, booking_id: UUID
) -> RentalBooking | None:
    result = await db.execute(
        select(RentalBooking)
        .options(
            selectinload(RentalBooking.lines).selectinload(RentalBookingLine.units),
            selectinload(RentalBooking.units),
        )
        .where(
            RentalBooking.id == booking_id,
            RentalBooking.organization_id == org_id,
        )
        .execution_options(populate_existing=True)
    )
    return result.unique().scalars().first()


async def _require_booking(
    db: AsyncSession, org_id: UUID, booking_id: UUID
) -> RentalBooking:
    booking = await _load_booking(db, org_id, booking_id)
    if booking is None:
        raise NotFoundException('rental_booking', get_current_lang())
    return booking


async def _assets_map(db: AsyncSession, org_id: UUID) -> dict[UUID, EquipmentAssetDTO]:
    assets = await equipment_api.list_bookable_assets_async(
        db, org_id, include_retired=True
    )
    return {asset.id: asset for asset in assets}


def _asset_name(assets: dict[UUID, EquipmentAssetDTO], item_id: UUID) -> str:
    asset = assets.get(item_id)
    return asset.name if asset is not None else ''


def _booking_summary(
    booking: RentalBooking, assets: dict[UUID, EquipmentAssetDTO]
) -> str:
    parts: list[str] = []
    for line in booking.lines:
        if line.item_id is not None:
            name = _asset_name(assets, line.item_id)
            parts.append(name or '—')
        else:
            model = line.model or ''
            parts.append(f'{model} ×{line.quantity}' if line.quantity > 1 else model)
    return ', '.join(part for part in parts if part)


def _unit_schema(
    unit: RentalBookingUnit, assets: dict[UUID, EquipmentAssetDTO]
) -> UnitSchema:
    asset = assets.get(unit.item_id)
    return UnitSchema(
        id=unit.id,
        item_id=unit.item_id,
        item_name=asset.name if asset is not None else '',
        model=asset.model if asset is not None else None,
        serial_number=asset.serial_number if asset is not None else None,
        asset_tag=asset.asset_tag if asset is not None else None,
        assignment_id=unit.assignment_id,
        condition=unit.condition,  # type: ignore[arg-type]
        note=unit.return_note,
        returned_at=unit.returned_at,
    )


def _line_schema(
    line: RentalBookingLine, assets: dict[UUID, EquipmentAssetDTO]
) -> LineSchema:
    return LineSchema(
        id=line.id,
        item_id=line.item_id,
        item_name=(
            assets[line.item_id].name
            if line.item_id is not None and line.item_id in assets
            else None
        ),
        model=line.model,
        quantity=line.quantity,
        resolved_count=len(line.units),
        units=[_unit_schema(unit, assets) for unit in line.units],
    )


async def booking_schema(
    db: AsyncSession,
    booking: RentalBooking,
    assets: dict[UUID, EquipmentAssetDTO] | None = None,
) -> BookingSchema:
    assets = (
        assets if assets is not None else await _assets_map(db, booking.organization_id)
    )
    now = _now()
    created_by_name = None
    if booking.created_by is not None:
        user = await core_api.users.get_async(
            db, booking.organization_id, booking.created_by
        )
        if user is not None:
            created_by_name = user.full_name or user.email
    is_late = booking.status == 'PICKED_UP' and booking.ends_at < now
    return BookingSchema(
        id=booking.id,
        status=booking.status,  # type: ignore[arg-type]
        is_late=is_late,
        late_days=_late_days(booking.ends_at, now),
        borrower_kind=_borrower_kind(booking),  # type: ignore[arg-type]
        borrower_partner_id=booking.borrower_partner_id,
        borrower_user_id=booking.borrower_user_id,
        borrower_name=booking.borrower_name,
        borrower_email=booking.borrower_email,
        starts_at=booking.starts_at,
        ends_at=booking.ends_at,
        note=booking.note,
        lines=[_line_schema(line, assets) for line in booking.lines],
        created_at=booking.created_at,
        created_by_name=created_by_name,
        can_pickup=booking.status == 'RESERVED',
        can_return=booking.status == 'PICKED_UP',
        can_cancel=booking.status == 'RESERVED',
        can_extend=booking.status in ACTIVE_STATUSES,
        handed_out_at=booking.picked_up_at,
        returned_at=booking.returned_at,
    )


async def _journal(
    db: AsyncSession,
    booking: RentalBooking,
    action: AuditAction,
    user_id: UUID | None,
    *,
    extra: dict | None = None,
) -> None:
    await core_api.audit_log.log_action_async(
        db,
        organization_id=booking.organization_id,
        user_id=user_id,
        action=action,
        target_type=JOURNAL_TARGET,
        target_id=booking.id,
        snapshot={
            'status': booking.status,
            'borrower_name': booking.borrower_name,
            'starts_at': booking.starts_at.isoformat(),
            'ends_at': booking.ends_at.isoformat(),
            'lines': [
                {
                    'item_id': str(line.item_id) if line.item_id else None,
                    'model': line.model,
                    'quantity': line.quantity,
                }
                for line in booking.lines
            ],
            **(extra or {}),
        },
    )


async def _resolve_borrower(
    db: AsyncSession, org_id: UUID, data: BookingCreate
) -> tuple[str, str | None]:
    if data.borrower_partner_id is not None:
        partner = await core_api.partners.get_async(
            db, org_id, data.borrower_partner_id
        )
        if partner is None:
            raise ServiceRejectionError('partner_not_found')
        return partner.name, partner.email
    if data.borrower_user_id is not None:
        user = await core_api.users.get_async(db, org_id, data.borrower_user_id)
        if user is None or user.organization_id != org_id:
            raise ServiceRejectionError('user_not_found')
        return user.full_name or user.email, user.email
    name = (data.borrower_name or '').strip()
    if not name:
        raise ServiceRejectionError('rental_borrower_needs_name')
    return name, (data.borrower_email or '').strip().lower() or None


@dataclass
class LockLine:
    """The part of a line a lock key is built from."""

    item_id: UUID | None = None
    model: str | None = None


def _line_lock_keys(
    org_id: UUID,
    lines: list[LockLine],
    assets_by_id: dict[UUID, EquipmentAssetDTO],
    assets_by_model: dict[str | None, list[EquipmentAssetDTO]],
) -> list[str]:
    """Lock every asset and model a line can decide about.

    A unit line decides about its model too: taking the last unit free for a
    model line's whole window breaks that promise, so the model is part of
    what this write reads and must be held while it does.
    """
    keys: set[str] = set()
    for line in lines:
        if line.item_id is not None:
            keys.add(f'rentals:item:{org_id}:{line.item_id}')
            asset = assets_by_id.get(line.item_id)
            if asset is not None and asset.model:
                keys.add(f'rentals:model:{org_id}:{asset.model}')
            continue
        keys.add(f'rentals:model:{org_id}:{line.model}')
        for asset in assets_by_model.get(line.model, []):
            keys.add(f'rentals:item:{org_id}:{asset.id}')
    return sorted(keys)


async def _lock(
    db: AsyncSession,
    org_id: UUID,
    lines: list[LockLine],
    assets_by_id: dict[UUID, EquipmentAssetDTO],
    assets_by_model: dict[str | None, list[EquipmentAssetDTO]],
) -> None:
    for key in _line_lock_keys(org_id, lines, assets_by_id, assets_by_model):
        await acquire_advisory_lock(db, key)


def _conflict_payload(checks: list) -> dict:
    return {
        'lines': [check.model_dump(mode='json') for check in checks if not check.ok]
    }


async def create_booking(
    db: AsyncSession,
    org_id: UUID,
    data: BookingCreate,
    user_id: UUID,
) -> RentalBooking:
    starts_at = data.starts_at
    ends_at = data.ends_at
    name, email = await _resolve_borrower(db, org_id, data)

    assets = await equipment_api.list_bookable_assets_async(db, org_id)
    by_id = {asset.id: asset for asset in assets}
    by_model: dict[str | None, list[EquipmentAssetDTO]] = {}
    for asset in assets:
        by_model.setdefault(asset.model, []).append(asset)

    for line in data.lines:
        if line.item_id is not None and line.item_id not in by_id:
            raise ServiceRejectionError('rental_asset_not_bookable')

    # The request's own lines, before any row exists: the lock keys come from
    # what is asked for, not from what was stored.
    await _lock(
        db,
        org_id,
        [LockLine(item_id=line.item_id, model=line.model) for line in data.lines],
        by_id,
        by_model,
    )

    world = await load_world(db, org_id, starts_at, ends_at, cover_bookings=True)
    checks = checks_for_lines(world, data.lines, starts_at, ends_at)
    if any(not check.ok for check in checks):
        raise RentalConflictError(
            'rental_booking_conflict',
            code='RENTAL_BOOKING_CONFLICT',
            details=_conflict_payload(checks),
        )

    booking = RentalBooking(
        organization_id=org_id,
        status='RESERVED',
        borrower_partner_id=data.borrower_partner_id,
        borrower_user_id=data.borrower_user_id,
        borrower_name=name,
        borrower_email=email,
        starts_at=starts_at,
        ends_at=ends_at,
        note=data.note,
        created_by=user_id,
    )
    db.add(booking)
    await db.flush()

    for line_in in data.lines:
        booking_line = RentalBookingLine(
            organization_id=org_id,
            booking_id=booking.id,
            item_id=line_in.item_id,
            model=line_in.model,
            quantity=line_in.quantity,
        )
        db.add(booking_line)
        await db.flush()
        if line_in.item_id is not None:
            db.add(
                RentalBookingUnit(
                    organization_id=org_id,
                    booking_id=booking.id,
                    line_id=booking_line.id,
                    item_id=line_in.item_id,
                )
            )
    await db.flush()
    fresh = await _require_booking(db, org_id, booking.id)
    await _journal(db, fresh, AuditAction.CREATE, user_id)
    return fresh


async def check_booking(
    db: AsyncSession,
    org_id: UUID,
    data,
) -> BookingCheckResponse:
    assets = await equipment_api.list_bookable_assets_async(db, org_id)
    by_id = {asset.id: asset for asset in assets}
    for line in data.lines:
        if line.item_id is not None and line.item_id not in by_id:
            raise ServiceRejectionError('rental_asset_not_bookable')
    # The way-out search looks further than the window it was asked about,
    # and a unit line is judged against the whole window of every promise it
    # could take a unit from.
    world = await load_world(
        db,
        org_id,
        data.starts_at,
        data.ends_at + timedelta(days=60),
        cover_bookings=True,
    )
    checks = checks_for_lines(
        world,
        data.lines,
        data.starts_at,
        data.ends_at,
        exclude_booking_id=data.booking_id,
    )
    return BookingCheckResponse(ok=all(check.ok for check in checks), lines=checks)


async def list_bookings(
    db: AsyncSession,
    org_id: UUID,
    *,
    status: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[RentalBooking], int]:
    stmt = (
        select(RentalBooking)
        .options(
            selectinload(RentalBooking.lines).selectinload(RentalBookingLine.units),
            selectinload(RentalBooking.units),
        )
        .where(RentalBooking.organization_id == org_id)
        .order_by(RentalBooking.starts_at.desc())
    )
    if status:
        stmt = stmt.where(RentalBooking.status == status)
    if search:
        pattern = f'%{search.strip()}%'
        stmt = stmt.where(
            or_(
                RentalBooking.borrower_name.ilike(pattern),
                RentalBooking.borrower_email.ilike(pattern),
                RentalBooking.note.ilike(pattern),
            )
        )
    return await paginate_async(db, stmt, limit=limit, offset=offset)


async def booking_rows(
    db: AsyncSession,
    org_id: UUID,
    bookings: list[RentalBooking],
) -> list[BookingListRow]:
    assets = await _assets_map(db, org_id)
    now = _now()
    rows: list[BookingListRow] = []
    for booking in bookings:
        is_late = booking.status == 'PICKED_UP' and booking.ends_at < now
        rows.append(
            BookingListRow(
                id=booking.id,
                status=booking.status,  # type: ignore[arg-type]
                is_late=is_late,
                late_days=_late_days(booking.ends_at, now),
                borrower_name=booking.borrower_name,
                borrower_kind=_borrower_kind(booking),  # type: ignore[arg-type]
                starts_at=booking.starts_at,
                ends_at=booking.ends_at,
                units_count=len(booking.units),
                summary=_booking_summary(booking, assets),
            )
        )
    return rows


async def cancel_booking(
    db: AsyncSession, org_id: UUID, booking_id: UUID, user_id: UUID
) -> RentalBooking:
    booking = await _require_booking(db, org_id, booking_id)
    if booking.status != 'RESERVED':
        raise ServiceRejectionError('rental_cancel_not_reserved')
    booking.status = 'CANCELLED'
    await db.flush()
    await _journal(db, booking, AuditAction.UPDATE, user_id, extra={'action': 'CANCEL'})
    return booking


async def pickup_booking(
    db: AsyncSession,
    org_id: UUID,
    booking_id: UUID,
    data: PickupRequest,
    user_id: UUID,
) -> RentalBooking:
    booking = await _require_booking(db, org_id, booking_id)
    if booking.status != 'RESERVED':
        raise ServiceRejectionError('rental_pickup_not_reserved')
    now = _now()
    # A loan handed out past its own end is overdue from the first minute and
    # holds its units against every later booking. Extending it first asks
    # whether they are free for the time it will really be out.
    if booking.ends_at <= now:
        raise ServiceRejectionError('rental_pickup_window_passed')

    assets = await equipment_api.list_bookable_assets_async(db, org_id)
    by_id = {asset.id: asset for asset in assets}
    by_model: dict[str | None, list[EquipmentAssetDTO]] = {}
    for asset in assets:
        by_model.setdefault(asset.model, []).append(asset)
    await _lock(
        db,
        org_id,
        [LockLine(item_id=line.item_id, model=line.model) for line in booking.lines],
        by_id,
        by_model,
    )

    scanned = list(data.item_ids)
    if len(set(scanned)) != len(scanned):
        raise ServiceRejectionError('rental_pickup_duplicate_scan')
    for item_id in scanned:
        if item_id not in by_id:
            raise ServiceRejectionError('rental_asset_not_bookable')

    # The world is read before the scans are pinned: a unit this pickup
    # resolves must be free for the booking's hold *and* must not be the
    # last unit another model line is counting on. Reading it after the
    # write would count this pickup's own units as already busy elsewhere.
    # The hold starts now when the hand-out comes before the window.
    world = await load_world(
        db,
        org_id,
        min(now, booking.starts_at),
        booking.ends_at,
        cover_bookings=True,
    )

    remaining = list(scanned)
    new_units, missing_count = _assign_scans(db, booking, remaining, by_id)
    if remaining or missing_count:
        raise RentalConflictError(
            'rental_pickup_incomplete',
            code='RENTAL_PICKUP_INCOMPLETE',
            details={
                'missing': missing_count,
                'unexpected': [str(item_id) for item_id in remaining],
            },
        )

    booking.picked_up_at = now
    await db.flush()
    # The scans are rows now: put the booking into the world the checks read as
    # it will be stored, its units resolved and held from this moment.
    add_picked_up_booking(world, booking, new_units)
    units_by_id = {unit.id: unit for line in booking.lines for unit in line.units}
    for unit in new_units:
        units_by_id[unit.id] = unit
    units = list(units_by_id.values())
    blocked = _blocked_units(
        world, booking, units, by_id, {unit.id for unit in new_units}
    )
    if blocked:
        raise RentalConflictError(
            'rental_pickup_asset_taken',
            code='RENTAL_PICKUP_ASSET_TAKEN',
            details={'units': blocked},
        )

    for unit in units:
        reference = await equipment_api.checkout_async(
            db,
            org_id,
            item_id=unit.item_id,
            assigned_to_name=booking.borrower_name,
            assigned_to_email=booking.borrower_email,
            assignee_partner_id=booking.borrower_partner_id,
            expected_return_at=booking.ends_at,
            notes=f'Booking {booking.id}',
            user_id=user_id,
        )
        if reference is None:
            raise ServiceRejectionError('equipment_module_unavailable')
        unit.assignment_id = reference.assignment_id

    booking.status = 'PICKED_UP'
    await db.flush()
    await _journal(db, booking, AuditAction.UPDATE, user_id, extra={'action': 'PICKUP'})
    return booking


def _assign_scans(
    db: AsyncSession,
    booking: RentalBooking,
    remaining: list[UUID],
    by_id: dict[UUID, EquipmentAssetDTO],
) -> tuple[list[RentalBookingUnit], int]:
    """Match scanned units to lines: an asset line needs its own, a model any.

    ``remaining`` is consumed in place; whatever is left over was not asked
    for. The count returned is how many slots no scan filled.
    """
    missing_count = 0
    for line in booking.lines:
        if line.item_id is None:
            continue
        if line.item_id in remaining:
            remaining.remove(line.item_id)
        else:
            missing_count += 1

    new_units: list[RentalBookingUnit] = []
    for line in booking.lines:
        if line.model is None:
            continue
        need = line.quantity - len(line.units)
        candidates = [
            item_id for item_id in remaining if by_id[item_id].model == line.model
        ][:need]
        for item_id in candidates:
            remaining.remove(item_id)
            unit = RentalBookingUnit(
                organization_id=booking.organization_id,
                booking_id=booking.id,
                line_id=line.id,
                item_id=item_id,
            )
            db.add(unit)
            new_units.append(unit)
        if len(candidates) < need:
            missing_count += need - len(candidates)
    return new_units, missing_count


def _blocked_units(
    world: World,
    booking: RentalBooking,
    units: list[RentalBookingUnit],
    by_id: dict[UUID, EquipmentAssetDTO],
    resolved: set[UUID],
) -> list[dict]:
    blocked: list[dict] = []
    for unit in units:
        conflicts = item_busy_conflicts(
            world,
            unit.item_id,
            booking.held_from,
            booking.ends_at,
            exclude_booking_id=booking.id,
        )
        reasons = [
            {
                'kind': slot.kind,
                'label': slot.label,
                'starts_at': slot.starts_at.isoformat(),
                'ends_at': slot.ends_at.isoformat(),
                'booking_id': str(slot.booking_id) if slot.booking_id else None,
            }
            for slot in conflicts
        ]
        # A scanned unit is new to this booking for the whole hold. A booked
        # unit's window was judged when it was booked, so only the time an
        # early hand-out adds before it is asked about.
        judged_to = booking.ends_at if unit.id in resolved else booking.starts_at
        if booking.held_from < judged_to:
            # Taking it must leave every model line enough units for its own
            # whole window, this booking's buffer included.
            reasons.extend(
                {
                    'kind': 'model_booking',
                    'label': displaced.booking.borrower_name,
                    'starts_at': displaced.booking.starts_at.isoformat(),
                    'ends_at': displaced.booking.ends_at.isoformat(),
                    'booking_id': str(displaced.booking.id),
                }
                for displaced in item_promise_conflicts(
                    world,
                    unit.item_id,
                    booking.held_from,
                    judged_to,
                    exclude_booking_id=booking.id,
                )
            )
        if not reasons:
            continue
        asset = by_id.get(unit.item_id)
        blocked.append(
            {
                'item_id': str(unit.item_id),
                'item_name': _asset_name(by_id, unit.item_id),
                'item_serial_number': (
                    asset.serial_number if asset is not None else None
                ),
                'reasons': reasons,
            }
        )
    return blocked


def _free_units_for_booking(
    world: World, booking: RentalBooking, model: str | None, leaving: UUID
) -> list[EquipmentAssetDTO]:
    """Units the booking could move to without starving another promise.

    ``leaving`` is the unit it moves off. Its hold there ends with the move, so
    it is taken out of the world first: the booking is judged where it goes,
    buffer included, and not on both units at once.
    """
    world = replace(
        world,
        slots_by_item={
            **world.slots_by_item,
            leaving: [
                slot
                for slot in world.slots_by_item.get(leaving, [])
                if slot.booking_id != booking.id
            ],
        },
    )
    pool = model_pool(
        world,
        model,
        booking.starts_at,
        booking.ends_at,
        exclude_booking_id=booking.id,
    )
    if pool.free < 1:
        return []
    taken = {unit.item_id for unit in booking.units}
    free: list[EquipmentAssetDTO] = []
    for asset in pool.units:
        if asset.id in taken:
            continue
        if item_busy_conflicts(
            world,
            asset.id,
            booking.starts_at,
            booking.ends_at,
            exclude_booking_id=booking.id,
        ):
            continue
        if item_promise_conflicts(
            world,
            asset.id,
            booking.starts_at,
            booking.ends_at,
            exclude_booking_id=booking.id,
        ):
            continue
        free.append(asset)
    return free


async def return_booking(
    db: AsyncSession,
    org_id: UUID,
    booking_id: UUID,
    data: ReturnRequest,
    user_id: UUID,
) -> RentalBooking:
    booking = await _require_booking(db, org_id, booking_id)
    if booking.status != 'PICKED_UP':
        raise ServiceRejectionError('rental_return_not_picked_up')
    units_by_id = {unit.id: unit for unit in booking.units}
    if {unit.unit_id for unit in data.units} != set(units_by_id):
        raise ServiceRejectionError('rental_return_needs_every_unit')

    now = _now()
    assets = await equipment_api.list_bookable_assets_async(db, org_id)
    by_id = {asset.id: asset for asset in assets}
    by_model: dict[str | None, list[EquipmentAssetDTO]] = {}
    for asset in assets:
        by_model.setdefault(asset.model, []).append(asset)
    # Lock the returned units, the units their models can promise, and every
    # unit a move may touch.
    lock_lines = [LockLine(item_id=unit.item_id) for unit in booking.units]
    for planned_move in data.moves:
        lock_lines.append(LockLine(item_id=planned_move.to_item_id))
    await _lock(db, org_id, lock_lines, by_id, by_model)

    planning = {unit.unit_id: unit for unit in data.units}
    world = await load_world(
        db,
        org_id,
        now - timedelta(days=1),
        now + timedelta(days=365),
    )

    # A unit that goes to service blocks its own time; a block that reaches a
    # later booking must either move that booking or end before it. The
    # blocks are part of the world before the moves are planned: a move must
    # not land on the unit this same return sends to service.
    planned_blocks = _planned_service_blocks(planning, units_by_id, now)
    _add_planned_service_blocks(world, planned_blocks)
    conflicts, applied_moves = _plan_service_moves(
        booking, world, by_id, planned_blocks, data.moves
    )

    if conflicts:
        raise RentalConflictError(
            'rental_service_block_conflict',
            code='RENTAL_SERVICE_BLOCK_CONFLICT',
            details={'conflicts': conflicts},
        )

    for unit, _start, block_end, reason in planned_blocks:
        db.add(
            RentalBlock(
                organization_id=org_id,
                item_id=unit.item_id,
                starts_at=now,
                ends_at=block_end,
                reason=reason,
                source='SERVICE',
                booking_id=booking.id,
                created_by=user_id,
            )
        )

    await _check_in_units(db, org_id, planning, units_by_id, user_id, now)

    booking.status = 'RETURNED'
    booking.returned_at = now
    await db.flush()
    await _journal(
        db,
        booking,
        AuditAction.UPDATE,
        user_id,
        extra={
            'action': 'RETURN',
            'conditions': {
                str(unit_id): plan.condition for unit_id, plan in planning.items()
            },
            'moves': len(applied_moves),
        },
    )
    return booking


def _planned_service_blocks(
    planning: dict,
    units_by_id: dict[UUID, RentalBookingUnit],
    now: datetime,
) -> list[tuple[RentalBookingUnit, datetime, datetime, str]]:
    planned: list[tuple[RentalBookingUnit, datetime, datetime, str]] = []
    for unit_id, plan in planning.items():
        if plan.condition != 'NEEDS_REPAIR':
            continue
        planned.append(
            (
                units_by_id[unit_id],
                now,
                plan.service_until or now,
                (plan.service_reason or '').strip(),
            )
        )
    return planned


def _add_planned_service_blocks(
    world: World,
    planned_blocks: list[tuple[RentalBookingUnit, datetime, datetime, str]],
) -> None:
    """Put the blocks this return would open into the world before moving."

    Without them the same request offers the unit it is about to take out of
    service as the free unit to move a later booking onto.
    """
    for unit, block_start, block_end, reason in planned_blocks:
        world.slots_by_item.setdefault(unit.item_id, []).append(
            Slot(
                kind='block',
                starts_at=block_start,
                ends_at=block_end,
                label=reason,
                reason=reason,
            )
        )


def _plan_service_moves(
    booking: RentalBooking,
    world: World,
    by_id: dict[UUID, EquipmentAssetDTO],
    planned_blocks: list[tuple[RentalBookingUnit, datetime, datetime, str]],
    moves: list[MoveIn],
) -> tuple[
    list[dict], list[tuple[RentalBooking, RentalBookingUnit, EquipmentAssetDTO]]
]:
    """Move the later bookings a service block would take, or name them."""
    conflicts: list[dict] = []
    moves_by_line = {(move.line_id, move.from_item_id): move for move in moves}
    applied: list[tuple[RentalBooking, RentalBookingUnit, EquipmentAssetDTO]] = []
    for unit, block_start, block_end, _reason in planned_blocks:
        for displaced in displaced_bookings(
            world,
            unit.item_id,
            block_start,
            block_end,
            exclude_booking_id=booking.id,
        ):
            later_booking = displaced.booking
            if displaced.unit is None:
                # The booking is a model-line promise: the block leaves it one
                # unit short, and no move can change which unit it takes.
                conflicts.append(
                    _service_pool_conflict(
                        world, later_booking, displaced, unit, by_id, block_start
                    )
                )
                continue
            later_unit = displaced.unit
            line = displaced.line or next(
                line for line in later_booking.lines if line.id == later_unit.line_id
            )
            before, _after = world.buffer_for(by_id[unit.item_id])
            busy_start = later_booking.starts_at - timedelta(hours=before)
            move: MoveIn | None = moves_by_line.get((line.id, unit.item_id))
            if move is None or later_booking.status != 'RESERVED':
                conflicts.append(
                    _service_conflict(
                        world, later_booking, line, unit, by_id, busy_start
                    )
                )
                continue
            moved = _apply_move(world, by_id, later_booking, later_unit, line, move)
            if moved is None:
                # The chosen unit is not free for the later booking once this
                # return's own blocks are in the world; the sheet is offered
                # the same conflict again, with no free unit to pick.
                conflicts.append(
                    _service_conflict(
                        world, later_booking, line, unit, by_id, busy_start
                    )
                )
                continue
            applied.append(moved)
    return conflicts, applied


def _service_conflict(
    world: World,
    later_booking: RentalBooking,
    line: RentalBookingLine,
    unit: RentalBookingUnit,
    by_id: dict[UUID, EquipmentAssetDTO],
    busy_start: datetime,
) -> dict:
    free_units = _free_units_for_booking(
        world, later_booking, by_id[unit.item_id].model, unit.item_id
    )
    return {
        'booking_id': str(later_booking.id),
        'line_id': str(line.id),
        'borrower_name': later_booking.borrower_name,
        'starts_at': later_booking.starts_at.isoformat(),
        'ends_at': later_booking.ends_at.isoformat(),
        'item_id': str(unit.item_id),
        'item_name': _asset_name(by_id, unit.item_id),
        'suggested_until': busy_start.isoformat(),
        'free_units': [
            {
                'item_id': str(asset.id),
                'name': asset.name,
                'serial_number': asset.serial_number,
            }
            for asset in free_units
        ],
    }


def _service_pool_conflict(
    world: World,
    later_booking: RentalBooking,
    displaced: DisplacedBooking,
    unit: RentalBookingUnit,
    by_id: dict[UUID, EquipmentAssetDTO],
    block_start: datetime,
) -> dict:
    """Name a model-line booking a service block would leave one unit short."""
    line = displaced.line
    return {
        'booking_id': str(later_booking.id),
        'line_id': str(line.id) if line is not None else '',
        'borrower_name': later_booking.borrower_name,
        'starts_at': later_booking.starts_at.isoformat(),
        'ends_at': later_booking.ends_at.isoformat(),
        'item_id': str(unit.item_id),
        'item_name': _asset_name(by_id, unit.item_id),
        'suggested_until': block_start.isoformat(),
        'free_units': [],
    }


def _apply_move(
    world: World,
    by_id: dict[UUID, EquipmentAssetDTO],
    later_booking: RentalBooking,
    later_unit: RentalBookingUnit,
    line: RentalBookingLine,
    move: MoveIn,
) -> tuple[RentalBooking, RentalBookingUnit, EquipmentAssetDTO] | None:
    """Move one pinned unit, or answer ``None`` when the target is not free."""
    target = by_id.get(move.to_item_id)
    if target is None or target.model != by_id[later_unit.item_id].model:
        raise ServiceRejectionError('rental_move_needs_same_model')
    if target.id in {unit.item_id for unit in later_booking.units}:
        raise ServiceRejectionError('rental_move_target_taken')
    if target.id not in {
        asset.id
        for asset in _free_units_for_booking(
            world,
            later_booking,
            by_id[later_unit.item_id].model,
            later_unit.item_id,
        )
    }:
        return None
    _move_booking_slots(world, later_booking.id, later_unit.item_id, target.id)
    later_unit.item_id = target.id
    if line.item_id is not None:
        line.item_id = target.id
    return later_booking, later_unit, target


def _move_booking_slots(
    world: World,
    booking_id: UUID,
    from_item_id: UUID,
    to_item_id: UUID,
) -> None:
    """Carry a moved booking's holds across in the planner's world.

    A later block is planned against the world the earlier move changed; a
    slot left on the old unit would answer for a booking that is no longer
    there.
    """
    moving = [
        slot
        for slot in world.slots_by_item.get(from_item_id, [])
        if slot.booking_id == booking_id
    ]
    if not moving:
        return
    world.slots_by_item[from_item_id] = [
        slot
        for slot in world.slots_by_item.get(from_item_id, [])
        if slot.booking_id != booking_id
    ]
    world.slots_by_item.setdefault(to_item_id, []).extend(moving)
    world.slots_by_item[to_item_id].sort(key=lambda slot: slot.starts_at)


async def _check_in_units(
    db: AsyncSession,
    org_id: UUID,
    planning: dict,
    units_by_id: dict[UUID, RentalBookingUnit],
    user_id: UUID,
    now: datetime,
) -> None:
    for unit_id, plan in planning.items():
        unit = units_by_id[unit_id]
        note = plan.note
        if plan.condition == 'NEEDS_REPAIR':
            note = (
                f'{(note or "").strip()} {(plan.service_reason or "").strip()}'.strip()
            )
        if unit.assignment_id is not None:
            reference = await equipment_api.checkin_async(
                db,
                org_id,
                assignment_id=unit.assignment_id,
                condition=plan.condition,
                notes=note or None,
                user_id=user_id,
            )
            if reference is None:
                raise ServiceRejectionError('equipment_module_unavailable')
        unit.condition = plan.condition
        unit.return_note = note or None
        unit.returned_at = now


def _extension_unit_conflicts(
    world: World,
    booking: RentalBooking,
    ends_at: datetime,
    assets_by_id: dict[UUID, EquipmentAssetDTO],
) -> list[dict]:
    """What a pinned unit's longer stay runs into, and whose promise it takes."""
    conflicts: list[dict] = []
    for unit in booking.units:
        asset = assets_by_id.get(unit.item_id)
        _before, after = world.buffer_for(asset) if asset is not None else (0, 0)
        for slot in item_busy_conflicts(
            world,
            unit.item_id,
            booking.ends_at,
            ends_at,
            exclude_booking_id=booking.id,
        ):
            conflicts.append(
                {
                    'kind': slot.kind,
                    'label': slot.label,
                    'starts_at': slot.starts_at.isoformat(),
                    'ends_at': slot.ends_at.isoformat(),
                    'booking_id': str(slot.booking_id) if slot.booking_id else None,
                    'item_id': str(unit.item_id),
                    'item_name': _asset_name(assets_by_id, unit.item_id),
                }
            )
        # An unresolved model booking promised the unit this extension keeps,
        # so the tail can leave it short; the pinned bookings above are already
        # named by their own slots.
        for displaced in displaced_bookings(
            world,
            unit.item_id,
            booking.ends_at,
            ends_at + timedelta(hours=after),
            exclude_booking_id=booking.id,
        ):
            if displaced.unit is not None:
                continue
            later = displaced.booking
            conflicts.append(
                {
                    'kind': 'model_booking',
                    'label': later.borrower_name,
                    'starts_at': later.starts_at.isoformat(),
                    'ends_at': later.ends_at.isoformat(),
                    'booking_id': str(later.id),
                    'item_id': str(unit.item_id),
                    'item_name': _asset_name(assets_by_id, unit.item_id),
                    'reason': (
                        str(displaced.line.unresolved_count)
                        if displaced.line is not None
                        else None
                    ),
                }
            )
    return conflicts


def _extension_model_conflicts(
    world: World, booking: RentalBooking, ends_at: datetime
) -> list[dict]:
    """What a model line's longer promise runs into.

    The line promises a unit for the whole enlarged window, not only for the
    tail: a unit free next week is no use if it is taken next month, and the
    old window's own holds are part of the answer.
    """
    conflicts: list[dict] = []
    for line in booking.lines:
        if line.model is None or line.unresolved_count <= 0:
            continue
        pool = model_pool(
            world,
            line.model,
            booking.starts_at,
            ends_at,
            exclude_booking_id=booking.id,
        )
        if pool.free >= line.unresolved_count:
            continue
        for booking_row, waiting in pool.waiting:
            conflicts.append(
                {
                    'kind': 'model_booking',
                    'label': booking_row.borrower_name,
                    'starts_at': booking_row.starts_at.isoformat(),
                    'ends_at': booking_row.ends_at.isoformat(),
                    'booking_id': str(booking_row.id),
                    'reason': str(waiting.unresolved_count),
                }
            )
        for busy_asset, slots in pool.busy:
            for slot in slots:
                conflicts.append(
                    {
                        'kind': slot.kind,
                        'label': slot.label,
                        'starts_at': slot.starts_at.isoformat(),
                        'ends_at': slot.ends_at.isoformat(),
                        'item_id': str(busy_asset.id),
                        'item_name': busy_asset.name,
                    }
                )
    return conflicts


async def extend_booking(
    db: AsyncSession,
    org_id: UUID,
    booking_id: UUID,
    data: ExtendRequest,
    user_id: UUID,
) -> RentalBooking:
    booking = await _require_booking(db, org_id, booking_id)
    if booking.status not in ACTIVE_STATUSES:
        raise ServiceRejectionError('rental_extend_not_active')
    if data.ends_at <= booking.ends_at:
        raise ServiceRejectionError('rental_extend_not_later')

    assets = await equipment_api.list_bookable_assets_async(db, org_id)
    by_id = {asset.id: asset for asset in assets}
    by_model: dict[str | None, list[EquipmentAssetDTO]] = {}
    for asset in assets:
        by_model.setdefault(asset.model, []).append(asset)
    await _lock(
        db,
        org_id,
        [LockLine(item_id=line.item_id, model=line.model) for line in booking.lines],
        by_id,
        by_model,
    )

    world = await load_world(
        db, org_id, booking.starts_at, data.ends_at, cover_bookings=True
    )
    assets_by_id = {asset.id: asset for asset in assets}
    # The longer stay is part of the world the checks read: an extension of a
    # booking that holds several units must be judged as the whole stay, or
    # each unit reads free on the days its siblings are taking.
    add_extended_booking(world, booking, data.ends_at)
    conflicts = _extension_unit_conflicts(
        world, booking, data.ends_at, assets_by_id
    ) + _extension_model_conflicts(world, booking, data.ends_at)
    if conflicts:
        raise RentalConflictError(
            'rental_extension_blocked',
            code='RENTAL_EXTENSION_BLOCKED',
            details={'conflicts': conflicts},
        )

    booking.ends_at = data.ends_at
    for unit in booking.units:
        if unit.assignment_id is not None:
            await equipment_api.set_expected_return_async(
                db,
                org_id,
                assignment_id=unit.assignment_id,
                expected_return_at=data.ends_at,
                user_id=user_id,
            )
    await db.flush()
    await _journal(db, booking, AuditAction.UPDATE, user_id, extra={'action': 'EXTEND'})
    return booking


async def calendar_view(
    db: AsyncSession,
    org_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
    *,
    model: str | None = None,
    category_id: UUID | None = None,
) -> CalendarResponse:
    world = await load_world(db, org_id, starts_at, ends_at)
    if model:
        world.assets = [asset for asset in world.assets if asset.model == model]
        world.assets_by_id = {asset.id: asset for asset in world.assets}
        world.assets_by_model = {model: world.assets}
    if category_id is not None:
        world.assets = [
            asset for asset in world.assets if asset.category_id == category_id
        ]
        world.assets_by_id = {asset.id: asset for asset in world.assets}
        by_model: dict[str | None, list[EquipmentAssetDTO]] = {}
        for asset in world.assets:
            by_model.setdefault(asset.model, []).append(asset)
        world.assets_by_model = by_model
    return build_calendar(world)


def _today_item(
    booking: RentalBooking, assets: dict[UUID, EquipmentAssetDTO]
) -> TodayItem:
    return TodayItem(
        booking_id=booking.id,
        borrower_name=booking.borrower_name,
        what=_booking_summary(booking, assets),
        at=booking.starts_at,
        until=booking.ends_at,
        late_days=_late_days(booking.ends_at, _now()),
    )


async def today_view(db: AsyncSession, org_id: UUID) -> TodayResponse:
    day_start, day_end = await organization_today(db, org_id)
    now = _now()
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
                    RentalBooking.status.in_(ACTIVE_STATUSES),
                )
            )
        )
        .unique()
        .scalars()
        .all()
    )
    assets = await _assets_map(db, org_id)
    late = sorted(
        [b for b in bookings if b.status == 'PICKED_UP' and b.ends_at < now],
        key=lambda b: b.ends_at,
    )
    pickups = sorted(
        [
            b
            for b in bookings
            if b.status == 'RESERVED' and day_start <= b.starts_at < day_end
        ],
        key=lambda b: b.starts_at,
    )
    returns = sorted(
        [
            b
            for b in bookings
            if b.status == 'PICKED_UP' and day_start <= b.ends_at < day_end
        ],
        key=lambda b: b.ends_at,
    )
    blocks = (
        (
            await db.execute(
                select(RentalBlock)
                .where(
                    RentalBlock.organization_id == org_id,
                    RentalBlock.starts_at <= now,
                    RentalBlock.ends_at > now,
                )
                .order_by(RentalBlock.ends_at)
            )
        )
        .scalars()
        .all()
    )
    return TodayResponse(
        date=day_start,
        pickups_count=len(pickups),
        returns_count=len(returns),
        late_count=len(late),
        late=[_today_item(booking, assets) for booking in late],
        pickups=[_today_item(booking, assets) for booking in pickups],
        returns=[_today_item(booking, assets) for booking in returns],
        in_service=[block_schema(block, assets) for block in blocks],
    )
