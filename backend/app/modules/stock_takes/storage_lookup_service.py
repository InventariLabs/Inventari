from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.module_sdk import join_location_path
from app.core.public_api import core_api


async def storage_exists(
    db: AsyncSession,
    organization_id: UUID | None,
    storage_location_id: UUID,
) -> bool:
    if organization_id is None:
        return False
    storage = await core_api.locations.get_async(
        db, organization_id, storage_location_id
    )
    return storage is not None


async def get_storage_tree(
    db: AsyncSession,
    organization_id: UUID | None,
    storage_location_id: UUID,
) -> tuple[list[UUID], list[UUID], dict[UUID, str]]:
    """Return (snapshot ids, family ids, {id: name path}) for a location.

    Recursive stock take: a stock take of a parent location covers
    products in every descendant (``snapshot_ids`` = the location plus its
    descendants). Locks and active-stock-take checks use ``family_ids`` —
    the location, its descendants AND its ancestors — so an active stock
    take of a rack blocks a shelf stock take and vice versa (full tree
    locks). The path is the chain of location names
    from the top down (``"Rack A / Shelf 1"``), used as a fallback for
    ``location_in_storage`` when the item has no shelf code of its own.

    Returns ``([], [], {})`` when the location does not exist.
    """
    if organization_id is None:
        return [], [], {}
    subtree, ancestors = await core_api.locations.subtree_and_ancestors_async(
        db, organization_id, storage_location_id
    )
    if not subtree:
        return [], [], {}
    by_id = {storage.id: storage for storage in [*subtree, *ancestors]}

    children: dict[UUID, list[UUID]] = {}
    for storage in subtree:
        if storage.parent_id is not None:
            children.setdefault(storage.parent_id, []).append(storage.id)

    snapshot_ids: list[UUID] = []
    stack = [storage_location_id]
    while stack:
        current = stack.pop()
        snapshot_ids.append(current)
        stack.extend(children.get(current, []))

    family_ids = [storage.id for storage in ancestors] + snapshot_ids

    paths: dict[UUID, str] = {}
    for location_id in snapshot_ids:
        chain: list[str] = []
        current_path: UUID | None = location_id
        while current_path is not None and current_path in by_id:
            chain.append(by_id[current_path].name)
            current_path = by_id[current_path].parent_id
        paths[location_id] = join_location_path(reversed(chain))

    return snapshot_ids, family_ids, paths
