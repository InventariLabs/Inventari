"""A location that physically moves takes the history of its stock with it.

A location keeps its id when it moves in the tree, so the products inside
stay on the same shelf ids and their movements could not say anything had
happened. A physical move therefore writes a relocation document
(``LocationRelocation``: the location, the path it left, the path it
reached) and one movement per product, batch and owner standing in the
location or below it, both ends on its own shelf and the quantity unchanged
— the records do not change, so there is nothing for a posting to post and
the movement goes straight through ``stock_moves_service.create_async``. A
move that only corrects the layout writes none of it.

The stock on a past date reads the documents back
(:func:`parents_as_of_async`): a subtree counts in the warehouse it stood in
on that date, not in the one the tree names today. The movement register
reads them the same way (:func:`paths_then_async`): a movement names the
path its shelf had when the goods moved, and a filter by a location lists the
movements made in it as it was then (:func:`subtree_epochs_async`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import in_ids
from app.core.location_path import join_location_path
from app.models.location_relocation import LocationRelocation
from app.models.stock_move import StockMove, StockMoveReferenceType
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
) -> Sequence[Row[Any]]:
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


async def paths_then_async(
    db: AsyncSession, organization_id: UUID, moves: Sequence[StockMove]
) -> dict[UUID, tuple[str | None, str | None]]:
    """The paths each movement's two ends had when it happened, where not today's.

    A location keeps its id when it physically moves, so today's tree would
    name the place it was carried to for every movement made before the move.
    The tree a movement stood in is today's with the physical moves after it
    undone, newest first, as in :func:`parents_as_of_async`. An end whose path
    then is its path today answers ``None``, and a movement both of whose ends
    do is left out of the answer. A movement a physical move wrote is left out
    too: it names the same shelf on both ends, and its document says where the
    shelf went.

    One query answers a page no physical move came after, which is every page
    of an organization that never moved a location physically.
    """
    moments = {
        move.id: move.completed_at or move.created_at
        for move in moves
        if move.reference_type != StockMoveReferenceType.LOCATION_RELOCATION
    }
    if not moments:
        return {}
    later = (
        await db.execute(
            select(
                LocationRelocation.location_id,
                LocationRelocation.from_parent_id,
                LocationRelocation.moved_at,
            )
            .where(
                LocationRelocation.organization_id == organization_id,
                LocationRelocation.moved_at > min(moments.values()),
                LocationRelocation.location_id.is_not(None),
            )
            .order_by(LocationRelocation.moved_at.desc(), LocationRelocation.id.desc())
        )
    ).all()
    if not later:
        return {}
    name_by_id, today = await _tree_async(db, organization_id)
    # Keyed by how many of the newest physical moves are undone.
    trees: dict[int, dict[UUID, UUID | None]] = {0: today}

    def tree_before(undone: int) -> dict[UUID, UUID | None]:
        if undone not in trees:
            parents = dict(today)
            for location_id, from_parent_id, _moved_at in later[:undone]:
                parents[location_id] = from_parent_id
            trees[undone] = parents
        return trees[undone]

    def path_then(
        location_id: UUID | None, parents: Mapping[UUID, UUID | None]
    ) -> str | None:
        if location_id is None or parents is today:
            return None
        then = path_to(name_by_id, parents, location_id)
        return None if then == path_to(name_by_id, today, location_id) else then

    paths: dict[UUID, tuple[str | None, str | None]] = {}
    for move in moves:
        if (moment := moments.get(move.id)) is None:
            continue
        parents = tree_before(sum(1 for row in later if row.moved_at > moment))
        ends = (
            path_then(move.from_location_id, parents),
            path_then(move.to_location_id, parents),
        )
        if ends != (None, None):
            paths[move.id] = ends
    return paths


async def subtree_epochs_async(
    db: AsyncSession, organization_id: UUID, location_id: UUID
) -> list[tuple[datetime | None, datetime | None, list[UUID]]] | None:
    """What stood in and below *location_id* over time, or None for always today's.

    Each entry is ``(start, end, ids)``: the location and everything below it
    from *start* (inclusive, None for the beginning) to *end* (exclusive,
    None for now), as the tree stood between two physical moves. Neighbouring
    stretches with the same members are one. None means no physical move
    changed the members, which is every location of an organization that
    never moved one physically.
    """
    moves = (
        await db.execute(
            select(
                LocationRelocation.location_id,
                LocationRelocation.from_parent_id,
                LocationRelocation.moved_at,
            )
            .where(
                LocationRelocation.organization_id == organization_id,
                LocationRelocation.location_id.is_not(None),
            )
            .order_by(LocationRelocation.moved_at.desc(), LocationRelocation.id.desc())
        )
    ).all()
    if not moves:
        return None
    _names, parents = await _tree_async(db, organization_id)
    epochs: list[tuple[datetime | None, datetime | None, list[UUID]]] = []
    end: datetime | None = None
    for move in moves:
        members = subtree_of(parents, location_id)
        if epochs and set(epochs[-1][2]) == set(members):
            epochs[-1] = (move.moved_at, epochs[-1][1], epochs[-1][2])
        else:
            epochs.append((move.moved_at, end, members))
        # Undone, the tree is what it was before this move.
        parents[move.location_id] = move.from_parent_id
        end = move.moved_at
    members = subtree_of(parents, location_id)
    if epochs and set(epochs[-1][2]) == set(members):
        epochs[-1] = (None, epochs[-1][1], epochs[-1][2])
    else:
        epochs.append((None, end, members))
    return None if len(epochs) == 1 else epochs
