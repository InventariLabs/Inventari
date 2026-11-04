"""A location that physically moves takes the history of its stock with it.

A location keeps its id when it moves in the tree, so the products inside
stay on the same shelf ids and their movements could not say anything had
happened. A physical move therefore writes a relocation document
(``LocationRelocation``: the location, the path it left, the path it
reached) and one movement per product, batch and owner standing in the
location or below it, both ends on its own shelf and the quantity unchanged
— the records do not change, so there is nothing for a posting to post and
the movement goes straight through ``stock_moves.create_async``. A move that
only corrects the layout writes none of it.

The stock on a past date reads the documents back
(:func:`parents_as_of_async`): a subtree counts in the warehouse it stood in
on that date, not in the one the tree names today.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import in_ids
from app.core.location_path import join_location_path
from app.models.location_relocation import LocationRelocation
from app.models.stock_move import StockMoveReferenceType
from app.models.stock_quants_from_records import stock_quants_from_records
from app.models.storage_location import StorageLocation
from app.services import stock_moves_service


def path_to(
    name_by_id: Mapping[UUID, str],
    parent_by_id: Mapping[UUID, UUID | None],
    node_id: UUID | None,
) -> str | None:
    """The full path of *node_id* ("Main Warehouse › Zone A"), None for no node."""
    names: list[str] = []
    seen: set[UUID] = set()
    current = node_id
    while current is not None and current not in seen:
        seen.add(current)
        names.append(name_by_id.get(current, ''))
        current = parent_by_id.get(current)
    return join_location_path(reversed(names)) if names else None


def top_of(parent_by_id: Mapping[UUID, UUID | None], node_id: UUID) -> UUID:
    """The top-level location above *node_id*, or the node itself at the top."""
    seen: set[UUID] = set()
    current = node_id
    while (parent := parent_by_id.get(current)) is not None and current not in seen:
        seen.add(current)
        current = parent
    return current


def subtree_of(
    parent_by_id: Mapping[UUID, UUID | None],
    node_id: UUID,
    excluded: set[UUID] | None = None,
) -> list[UUID]:
    """*node_id* and every location below it in *parent_by_id*."""
    excluded = excluded or set()
    children: dict[UUID, list[UUID]] = {}
    for child, parent in parent_by_id.items():
        if parent is not None and child not in excluded:
            children.setdefault(parent, []).append(child)
    found = [node_id]
    stack = [node_id]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in found:
                found.append(child)
                stack.append(child)
    return found


async def _groups_holding_stock_async(
    db: AsyncSession, organization_id: UUID, location_ids: list[UUID]
):
    view = stock_quants_from_records
    return (
        await db.execute(
            select(
                view.c.product_template_id,
                view.c.storage_location_id,
                view.c.lot_id,
                view.c.owner_id,
                view.c.quantity,
            ).where(
                view.c.organization_id == organization_id,
                in_ids(view.c.storage_location_id, location_ids),
                view.c.quantity > 0,
            )
        )
    ).all()


async def products_in_async(
    db: AsyncSession, organization_id: UUID, location_ids: list[UUID]
) -> int:
    """How many distinct products hold stock among *location_ids*."""
    rows = await _groups_holding_stock_async(db, organization_id, location_ids)
    return len({row.product_template_id for row in rows})


async def record_relocation_async(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID | None,
    location_id: UUID,
    location_name: str,
    from_parent_id: UUID | None,
    to_parent_id: UUID | None,
    from_path: str | None,
    to_path: str | None,
    location_ids: list[UUID],
) -> LocationRelocation:
    """Write the relocation document and a movement for every product inside.

    *location_ids* is the moved location and everything below it. Flushes,
    never commits: the move it records is in the caller's transaction.
    """
    document = LocationRelocation(
        organization_id=organization_id,
        location_id=location_id,
        location_name=location_name,
        from_parent_id=from_parent_id,
        to_parent_id=to_parent_id,
        from_path=from_path,
        to_path=to_path,
        created_by=user_id,
    )
    db.add(document)
    await db.flush()
    for row in await _groups_holding_stock_async(db, organization_id, location_ids):
        await stock_moves_service.create_async(
            db,
            organization_id=organization_id,
            product_template_id=row.product_template_id,
            quantity=row.quantity,
            from_location_id=row.storage_location_id,
            to_location_id=row.storage_location_id,
            lot_id=row.lot_id,
            owner_id=row.owner_id,
            reference_type=StockMoveReferenceType.LOCATION_RELOCATION,
            reference_id=document.id,
            created_by=user_id,
            completed_at=document.moved_at,
        )
    return document


async def _tree_async(
    db: AsyncSession, organization_id: UUID
) -> tuple[dict[UUID, str], dict[UUID, UUID | None]]:
    rows = (
        await db.execute(
            select(
                StorageLocation.id, StorageLocation.name, StorageLocation.parent_id
            ).where(StorageLocation.organization_id == organization_id)
        )
    ).all()
    return {row.id: row.name for row in rows}, {row.id: row.parent_id for row in rows}


async def record_moved_location_async(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID | None,
    location: StorageLocation,
    from_parent_id: UUID | None,
) -> LocationRelocation:
    """:func:`record_relocation_async` for one location already moved and flushed.

    The single edit's door: the tree is read as it stands after the move, so
    the path left is the old parent's — which the move did not touch.
    """
    name_by_id, parent_by_id = await _tree_async(db, organization_id)
    return await record_relocation_async(
        db,
        organization_id=organization_id,
        user_id=user_id,
        location_id=location.id,
        location_name=location.name,
        from_parent_id=from_parent_id,
        to_parent_id=location.parent_id,
        from_path=path_to(name_by_id, parent_by_id, from_parent_id),
        to_path=path_to(name_by_id, parent_by_id, location.parent_id),
        location_ids=subtree_of(parent_by_id, location.id),
    )


async def parents_as_of_async(
    db: AsyncSession, organization_id: UUID, as_of: datetime
) -> dict[UUID, UUID | None] | None:
    """The tree as it stood at *as_of*, or None when no physical move came since.

    Today's tree with every relocation after the date undone, newest first.
    A layout correction left no document, so it is not undone: the stock was
    always where the corrected tree puts it.
    """
    later = (
        await db.execute(
            select(LocationRelocation.location_id, LocationRelocation.from_parent_id)
            .where(
                LocationRelocation.organization_id == organization_id,
                LocationRelocation.moved_at > as_of,
                LocationRelocation.location_id.is_not(None),
            )
            .order_by(LocationRelocation.moved_at.desc(), LocationRelocation.id.desc())
        )
    ).all()
    if not later:
        return None
    _names, parent_by_id = await _tree_async(db, organization_id)
    for location_id, from_parent_id in later:
        parent_by_id[location_id] = from_parent_id
    return parent_by_id
