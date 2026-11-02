"""Where a warehouse that receives in two steps puts a delivery first.

A warehouse is a top-level location. Its row in ``WarehouseReceiving`` says
whether it receives in one step (no row, or ``two_step`` off — the shelf the
putaway rules choose) or in two: the receipt lands in the warehouse's
receiving area, and somebody puts the goods away later. The area is an
ordinary location inside the warehouse, so its stock counts like any other;
it is made the first time the mode needs it, and made again when somebody
has removed it since.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import StorageDTO
from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    ServiceRejectionError,
)
from app.core.public_api import core_api
from app.i18n.service import get_current_lang

from .models import WarehouseReceiving

#: The receiving area's name, in the language of whoever first needed it —
#: the way the seeded locations are named. A person may rename it after.
_AREA_NAMES = {
    'en': 'Receiving',
    'pl': 'Strefa przyjęć',
    'de': 'Wareneingang',
    'fr': 'Zone de réception',
    'es': 'Zona de recepción',
}

#: Deeper than any real tree; a cycle in bad data must not loop forever.
_MAX_DEPTH = 64


def _usable(location: StorageDTO | None) -> bool:
    return (
        location is not None
        and location.usage == 'internal'
        and (location.settings or {}).get('archived') is not True
    )


async def warehouse_of_async(
    db: AsyncSession, org_id: UUID, location_id: UUID | None
) -> UUID | None:
    """The top-level location ``location_id`` stands in (itself at the top)."""
    current = location_id
    for _ in range(_MAX_DEPTH):
        if current is None:
            return None
        location = await core_api.locations.get_async(db, org_id, current)
        if location is None:
            return None
        if location.parent_id is None:
            return location.id
        current = location.parent_id
    return None


async def _row_async(
    db: AsyncSession, org_id: UUID, warehouse_id: UUID, *, for_update: bool = False
) -> WarehouseReceiving | None:
    query = select(WarehouseReceiving).where(
        WarehouseReceiving.organization_id == org_id,
        WarehouseReceiving.warehouse_id == warehouse_id,
    )
    if for_update:
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


async def list_receiving_modes_async(
    db: AsyncSession, org_id: UUID
) -> list[WarehouseReceiving]:
    """Every warehouse that chose a mode; one missing receives in one step."""
    return list(
        (
            await db.execute(
                select(WarehouseReceiving)
                .where(WarehouseReceiving.organization_id == org_id)
                .order_by(WarehouseReceiving.created_at)
            )
        )
        .scalars()
        .all()
    )


async def _existing_child_async(
    db: AsyncSession, org_id: UUID, warehouse_id: UUID, name: str
) -> UUID | None:
    """A location of that name directly inside the warehouse, if there is one."""
    for location_id in await core_api.locations.descendant_ids_async(
        db, org_id, warehouse_id
    ):
        location = await core_api.locations.get_async(db, org_id, location_id)
        if (
            location is not None
            and location.parent_id == warehouse_id
            and location.name == name
        ):
            return location.id
    return None


async def _ensure_area_async(
    db: AsyncSession, org_id: UUID, user_id: UUID, row: WarehouseReceiving
) -> UUID:
    """The warehouse's receiving area, made now if it has none that takes goods.

    A location the warehouse already holds under the area's name becomes the
    area rather than a refusal: somebody who made "Receiving" by hand meant
    exactly this.
    """
    if row.receiving_location_id is not None and _usable(
        await core_api.locations.get_async(db, org_id, row.receiving_location_id)
    ):
        return row.receiving_location_id
    name = _AREA_NAMES.get(get_current_lang(), _AREA_NAMES['en'])
    try:
        area = await core_api.locations.create_async(
            db, org_id, name=name, user_id=user_id, parent_id=row.warehouse_id
        )
        area_id = area.id
    except ConflictException:
        existing = await _existing_child_async(db, org_id, row.warehouse_id, name)
        if existing is None:
            raise
        area_id = existing
    row.receiving_location_id = area_id
    await db.flush()
    return area_id


async def set_receiving_mode_async(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    warehouse_id: UUID,
    *,
    two_step: bool | None = None,
    free_placement: bool | None = None,
) -> WarehouseReceiving:
    """Choose how one warehouse receives and whether it keeps fixed places.

    Only a top-level location is a warehouse. Two steps make the area at once
    rather than at the first receipt, so a draft receipt can already say where
    its goods will land. A choice left out keeps what the warehouse had.
    """
    location = await core_api.locations.get_async(db, org_id, warehouse_id)
    if location is None or location.usage != 'internal':
        raise NotFoundException('storage', get_current_lang())
    if location.parent_id is not None:
        raise ServiceRejectionError('receiving_mode_needs_a_warehouse')
    row = await _row_async(db, org_id, warehouse_id, for_update=True)
    if row is None:
        row = WarehouseReceiving(
            organization_id=org_id,
            warehouse_id=warehouse_id,
            two_step=bool(two_step),
            free_placement=bool(free_placement),
        )
        db.add(row)
    if two_step is not None:
        row.two_step = two_step
    if free_placement is not None:
        row.free_placement = free_placement
    await db.flush()
    if two_step:
        await _ensure_area_async(db, org_id, user_id, row)
    return row


async def receiving_area_for_async(
    db: AsyncSession,
    org_id: UUID,
    location_id: UUID | None,
    *,
    user_id: UUID | None = None,
) -> UUID | None:
    """Where a receipt into ``location_id`` lands first, or ``None`` for one step.

    A receipt into a warehouse that receives in one step has no first stop.
    With ``user_id`` (a receipt being posted)
    a missing area is made; without it (a preview) the receipt is read as
    one step until the area exists again.
    """
    warehouse_id = await warehouse_of_async(db, org_id, location_id)
    if warehouse_id is None:
        return None
    row = await _row_async(db, org_id, warehouse_id)
    if row is None or not row.two_step:
        return None
    if user_id is not None:
        area_id: UUID | None = await _ensure_area_async(db, org_id, user_id, row)
    elif row.receiving_location_id is not None and _usable(
        await core_api.locations.get_async(db, org_id, row.receiving_location_id)
    ):
        area_id = row.receiving_location_id
    else:
        area_id = None
    return area_id
