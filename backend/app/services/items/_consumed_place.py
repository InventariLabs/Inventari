"""Where a record stands once it has nothing left — and where it comes back to.

Taking the last unit of a record files it under the organization's virtual
Consumed place, so it leaves the products list, the overview's attention list
and the statistics counters (``_query_get``, ``low_stock``). Every door that
takes a record to nothing files it the same way through
:func:`file_under_consumed_async`, and a record that gets stock again while it
stands there returns to the shelf it left through
:func:`bring_back_from_consumed_async`: a positive quantity in a place that
counts no stock is a record no screen shows.

The shelf it left is kept on the record (``meta_data['emptied_from']``) for
that return.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item
from app.models.storage_location import LocationUsage, StorageLocation

from ._stock_relocation import lock_shelf_change_async

EMPTIED_FROM = 'emptied_from'


async def file_under_consumed_async(
    db: AsyncSession,
    item: Item,
    user_id: UUID | None,
    *,
    virtual_usage: LocationUsage = LocationUsage.CUSTOMER,
) -> UUID | None:
    """Move an emptied record to the virtual place of *virtual_usage*.

    Returns the shelf it left, or None when the record was not moved (no
    virtual place, or it already stands in one).
    """
    from app.services.storage._defaults import (
        ensure_virtual_locations_async,
        get_virtual_location_async,
    )

    organization_id = str(item.organization_id)
    await ensure_virtual_locations_async(
        db,
        organization_id,
        str(user_id) if user_id else organization_id,
        align_names=False,
    )
    virtual_loc = await get_virtual_location_async(db, organization_id, virtual_usage)
    if virtual_loc is None or virtual_loc.id == item.storage_location_id:
        return None
    shelf = item.storage_location_id
    await lock_shelf_change_async(db, [item], virtual_loc.id)
    item.storage_location_id = virtual_loc.id
    item.meta_data = {**(item.meta_data or {}), EMPTIED_FROM: str(shelf)}
    return shelf


async def bring_back_from_consumed_async(db: AsyncSession, item: Item) -> None:
    """Return a record that stands in the Consumed place to the shelf it left.

    A no-op for a record on a real shelf, and for one whose shelf is not
    known (filed there before the shelf was kept) or is gone.
    """
    place = await db.get(StorageLocation, item.storage_location_id)
    if place is None or place.usage not in (
        LocationUsage.CUSTOMER,
        LocationUsage.INVENTORY,
    ):
        return
    meta: dict[str, Any] = dict(item.meta_data or {})
    shelf_id = meta.get(EMPTIED_FROM)
    if not shelf_id:
        return
    shelf = await db.get(StorageLocation, UUID(str(shelf_id)))
    if (
        shelf is None
        or shelf.organization_id != item.organization_id
        or shelf.usage != LocationUsage.INTERNAL
    ):
        return
    await lock_shelf_change_async(db, [item], shelf.id)
    item.storage_location_id = shelf.id
    meta.pop(EMPTIED_FROM)
    item.meta_data = meta or None
