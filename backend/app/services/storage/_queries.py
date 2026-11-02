from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import exists, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql.elements import ColumnElement

from app.core.db_utils import acquire_advisory_lock, in_ids
from app.core.logging import get_logger
from app.models.item import Item
from app.models.label_pool import LabelPool
from app.models.stock_quants_from_records import stock_quants_from_records
from app.models.storage_location import StorageLocation
from app.schemas.storage_location import (
    StorageLocationBreadcrumb,
    StorageLocationNode,
)

logger = get_logger(__name__)


async def list_storage_ids_async(db: AsyncSession, organization_id: UUID) -> list[UUID]:
    """Return just the storage location IDs for *organization_id*."""
    result = await db.scalars(
        select(StorageLocation.id).where(
            StorageLocation.organization_id == organization_id
        )
    )
    return list(result.all())


async def display_names_by_ids_async(
    db: AsyncSession,
    organization_id: UUID,
    storage_ids: Iterable[UUID],
) -> dict[UUID, str]:
    """The name of each shelf these ids name, asked in one read.

    A report that prints a shelf beside a stored id used to fetch each
    location on its own, or list the shelves and filter — and the list hides
    archived ones, while the document filed there still prints. Only ids of
    this organization answer; an id of another organization, or one that no
    longer exists, is absent and the caller keeps its fallback.
    """
    ids = list(dict.fromkeys(storage_ids))
    if not ids:
        return {}
    rows = await db.execute(
        select(StorageLocation.id, StorageLocation.name).where(
            StorageLocation.organization_id == organization_id,
            in_ids(StorageLocation.id, ids),
        )
    )
    return {row[0]: row[1] for row in rows.all()}


async def locations_holding_stock_async(
    db: AsyncSession, organization_id: UUID, location_ids: list[UUID]
) -> set[UUID]:
    """The locations among *location_ids* where the register still holds stock.

    Stock on hand and stock promised to a reservation both count: either is
    something a deletion would take out of the register with no movement to
    say so. Both numbers come from ``stock_quants_from_records`` — the live
    records and the reservation rows of each group, which are the stock and
    what is promised out of it.
    """
    if not location_ids:
        return set()
    rows = await db.scalars(
        select(stock_quants_from_records.c.storage_location_id)
        .where(
            stock_quants_from_records.c.organization_id == organization_id,
            in_ids(stock_quants_from_records.c.storage_location_id, location_ids),
            or_(
                stock_quants_from_records.c.quantity > 0,
                stock_quants_from_records.c.reserved_quantity > 0,
            ),
        )
        .distinct()
    )
    return set(rows.all())


def get_organization_storage_ids(
    db: Session, organization_id: UUID | None
) -> list[UUID]:
    """Sync helper: all storage location IDs for a given organization."""
    if organization_id is None:
        return []
    storages = db.scalars(
        select(StorageLocation.id).where(
            StorageLocation.organization_id == organization_id
        )
    ).all()
    return list(storages)


async def get_storage_with_type_async(
    db: AsyncSession, organization_id: UUID, storage_id: UUID
) -> StorageLocation | None:
    """Return a storage location with eager-loaded storage_type, or ``None``."""
    result = await db.scalar(
        select(StorageLocation)
        .options(joinedload(StorageLocation.storage_type))
        .where(
            StorageLocation.id == storage_id,
            StorageLocation.organization_id == organization_id,
        )
    )
    return result


async def list_for_org_with_filters_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    usage: str | None = None,
    context_tag: str | None = None,
) -> list[StorageLocation]:
    """List storage locations for *organization_id* with optional filters."""
    query = select(StorageLocation).where(
        StorageLocation.organization_id == organization_id,
        not_archived_condition(),
    )
    if usage:
        query = query.where(StorageLocation.usage == usage)
    if context_tag == '__none__':
        query = query.where(StorageLocation.context_tag.is_(None))
    elif context_tag:
        query = query.where(StorageLocation.context_tag == context_tag)

    result = await db.scalars(query)
    return list(result.unique().all())


async def item_counts_by_location_async(
    db: AsyncSession,
    organization_id: UUID,
    storage_ids: list[UUID],
    module_scope: str | None = None,
    *,
    claimed_tags: set[str] | None = None,
) -> dict[UUID, int]:
    """Count the organization's own non-deleted items per storage location.

    The org filter is not decoration: the write side does not validate that an
    item's storage reference stays inside its organization, so without this
    filter a foreign organization's record parked in one of our locations
    inflates our count, and counting by storage id alone would let a caller
    learn the size of another organization's storage.

    With ``module_scope`` the count answers for that module's records only,
    asking the same two questions in the same order the location filter asks
    them (category first, ``module_name`` for the uncategorised) — a module
    screen's numbers must describe what its screen lists, and an
    "Equipment Locations" row counting the organization's groceries reads as
    a count of IT assets. A module nobody registered claims nothing, so its
    count is zero rather than every record.

    ``claimed_tags`` is the general screens' mirror of that: only the records
    ``GET /items`` shows under ``exclude_module_contexts`` are counted, so a
    location and the list it opens agree about how much stands in it.
    """
    if not storage_ids:
        return {}
    # A module's records are counted where they stand now — the place the
    # module put one for a while, not its home — so a module screen's count
    # and the module's list filtered by the place agree (see
    # ``standing_location``). Every other count reads the home.
    where: ColumnElement[UUID] = Item.storage_location_id.expression
    if module_scope is not None:
        from app.core.module_ownership import claimed_by_module, standing_location

        where = standing_location(module_scope, organization_id)
    stmt = (
        select(where, func.count(Item.id).label('total'))
        .where(Item.is_deleted.is_(False))
        .where(Item.organization_id == organization_id)
        .where(in_ids(where, storage_ids))
    )
    if module_scope is not None:
        from app.core.module_scope import get_context_tags_of

        tags = get_context_tags_of(module_scope)
        if not tags:
            return {}
        stmt = stmt.where(claimed_by_module(module_scope, tags))
    elif claimed_tags:
        from app.core.module_ownership import unclaimed_by_a_module

        stmt = stmt.where(unclaimed_by_a_module(claimed_tags))
    result = await db.execute(stmt.group_by(where))
    return {row[0]: row[1] for row in result.all()}


def subtree_item_counts(
    direct_counts: dict[UUID, int],
    parents: dict[UUID, UUID | None],
) -> dict[UUID, int]:
    """Items in each location's subtree, the location itself included.

    Folded upwards in Python rather than asked of a recursive CTE: the caller
    already holds the parent map and the direct counts, the tree is small
    enough that walking it costs nothing next to the queries that produced
    those two, and a display counter does not earn its own recursive query.
    ``count_items_in_subtree_async`` is the single-location question asked of
    the database when the caller holds no maps.

    The walk carries a ``seen`` set. Cycles are refused on write and repaired
    when found, but this runs on whatever is in the table — and a counter is
    not the place to discover a cycle by hanging.
    """
    totals: dict[UUID, int] = dict.fromkeys(parents, 0)
    for node_id, count in direct_counts.items():
        if not count:
            continue
        current: UUID | None = node_id
        seen: set[UUID] = set()
        while current is not None and current not in seen:
            seen.add(current)
            if current in totals:
                totals[current] += count
            current = parents.get(current)
    return totals


async def list_items_in_location_async(
    db: AsyncSession,
    organization_id: UUID,
    storage_id: UUID,
    *,
    include_inside: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> list[Item]:
    """List non-deleted items in *storage_id* ordered by expiry ascending.

    With ``include_inside`` the places standing below *storage_id*, at any
    depth, are read in the same statement: one ask for the subtree instead of
    one per place.

    ``limit`` and ``offset`` slice in the database, so a caller paging a
    subtree hydrates the page it returns, not the subtree once per page. The
    item id breaks ties in the expiry order, which keeps the pages disjoint.
    """
    where = [
        Item.organization_id == organization_id,
        Item.is_deleted.is_(False),
    ]
    if include_inside:
        scope_ids = [storage_id] + await descendant_ids_async(
            db, organization_id, storage_id
        )
        where.append(in_ids(Item.storage_location_id, scope_ids))
    else:
        where.append(Item.storage_location_id == storage_id)
    result = await db.scalars(
        select(Item)
        .options(joinedload(Item.category), joinedload(Item.uom))
        .where(*where)
        .order_by(Item.effective_expiry_date.asc().nullslast(), Item.id)
        .offset(offset)
        .limit(limit)
    )
    return list(result.all())


async def count_items_in_location_async(
    db: AsyncSession, organization_id: UUID, storage_id: UUID
) -> int:
    """Count non-deleted items in *storage_id*."""
    result = await db.scalar(
        select(func.count(Item.id)).where(
            Item.organization_id == organization_id,
            Item.storage_location_id == storage_id,
            Item.is_deleted.is_(False),
        )
    )
    return result or 0


async def count_items_in_subtree_async(
    db: AsyncSession, organization_id: UUID, storage_id: UUID
) -> int:
    """Count non-deleted items in *storage_id* and all its descendants.

    Mirrors the relocation scope of ``archive_storage`` — no usage filter, so
    the UI can require a move target exactly when the backend would.
    """
    scope_ids = [storage_id] + await descendant_ids_async(
        db, organization_id, storage_id
    )
    counts = await item_counts_by_location_async(db, organization_id, scope_ids)
    return sum(counts.values())


async def expiring_counts_by_location_async(
    db: AsyncSession,
    organization_id: UUID | None,
    storage_ids: list[UUID],
    days: int = 7,
) -> dict[UUID, int]:
    """Count non-deleted items expiring within *days*, per storage location.

    The window is ``items.expiry.is_expiring_soon``, the same one the storages
    list and the dashboard draw. A missing organization owns nothing — zero
    counts, never another tenant's rows (same drift as the items count).
    """
    if not storage_ids:
        return {}
    from app.services.items.expiry import expiry_today_async, is_expiring_soon

    today = await expiry_today_async(db, organization_id)
    rows = (
        await db.execute(
            select(
                Item.storage_location_id,
                func.count(Item.id).label('expiring'),
            )
            .where(
                Item.organization_id == organization_id,
                Item.is_deleted.is_(False),
                in_ids(Item.storage_location_id, storage_ids),
                is_expiring_soon(today, days),
            )
            .group_by(Item.storage_location_id)
        )
    ).all()
    return {row[0]: row[1] for row in rows}


async def count_expiring_soon_async(
    db: AsyncSession, organization_id: UUID, storage_id: UUID, *, days: int = 7
) -> int:
    """Count non-deleted items in *storage_id* expiring within *days*.

    One location asked of ``expiring_counts_by_location_async``, so the detail
    screen and the list can never draw different windows.
    """
    counts = await expiring_counts_by_location_async(
        db, organization_id, [storage_id], days
    )
    return counts.get(storage_id, 0)


async def get_storage_async(
    db: AsyncSession, organization_id: UUID, storage_id: UUID
) -> StorageLocation | None:
    """Async: fetch a single storage location by ID within organization."""
    return await db.scalar(
        select(StorageLocation).where(
            StorageLocation.id == storage_id,
            StorageLocation.organization_id == organization_id,
        )
    )


async def find_by_context_tag_async(
    db: AsyncSession, organization_id: UUID, context_tag: str
) -> StorageLocation | None:
    """Async: find first storage location with given context_tag."""
    return await db.scalar(
        select(StorageLocation).where(
            StorageLocation.organization_id == organization_id,
            StorageLocation.context_tag == context_tag,
        )
    )


async def list_storages_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    context_tag: str | None = None,
    usage: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[StorageLocation]:
    """Async: return storage locations for *organization_id* with optional filters."""
    query = select(StorageLocation).where(
        StorageLocation.organization_id == organization_id,
        not_archived_condition(),
    )
    if context_tag:
        query = query.where(StorageLocation.context_tag == context_tag)
    if usage:
        query = query.where(StorageLocation.usage == usage)
    result = await db.scalars(
        query.order_by(StorageLocation.name.asc()).offset(offset).limit(limit)
    )
    return list(result.all())


async def is_descendant_async(
    db: AsyncSession,
    organization_id: UUID,
    ancestor_id: UUID,
    node_id: UUID,
) -> bool:
    """Return True if *node_id* is a descendant of *ancestor_id*.

       Walks the parent chain with a recursive CTE instead of loading the
    whole tree into memory (parent validation).
    """
    cte = (
        select(StorageLocation.id)
        .where(
            StorageLocation.parent_id == ancestor_id,
            StorageLocation.organization_id == organization_id,
        )
        .cte(name='descendants', recursive=True)
    )
    cte = cte.union_all(
        select(StorageLocation.id)
        .join(cte, StorageLocation.parent_id == cte.c.id)
        .where(StorageLocation.organization_id == organization_id)
    )
    result = await db.scalar(select(cte.c.id).where(cte.c.id == node_id).limit(1))
    return result is not None


async def descendant_ids_async(
    db: AsyncSession, organization_id: UUID, node_id: UUID
) -> list[UUID]:
    """All descendant ids below *node_id* (recursive CTE, excludes the node)."""
    cte = (
        select(StorageLocation.id)
        .where(
            StorageLocation.parent_id == node_id,
            StorageLocation.organization_id == organization_id,
        )
        .cte(name='descendant_ids', recursive=True)
    )
    cte = cte.union_all(
        select(StorageLocation.id)
        .join(cte, StorageLocation.parent_id == cte.c.id)
        .where(StorageLocation.organization_id == organization_id)
    )
    result = await db.scalars(select(cte.c.id))
    return list(result.all())


async def subtree_and_ancestors_async(
    db: AsyncSession, organization_id: UUID, node_id: UUID
) -> tuple[list[StorageLocation], list[StorageLocation]]:
    """The location with everything below it, and the chain above it.

    Returns ``(subtree, ancestors)``: the node followed by its descendants
    (unordered below the node), and its ancestors nearest first. Archived
    locations are hidden as the listings hide them, and hide what hangs from
    them: an archived node answers ``([], [])``, an archived ancestor ends
    the chain. Two recursive queries, so the cost follows the size of the
    subtree and the depth of the tree, never the size of the organization.
    """
    visible = (
        StorageLocation.organization_id == organization_id,
        not_archived_condition(),
    )
    below = (
        select(StorageLocation.id)
        .where(StorageLocation.id == node_id, *visible)
        .cte(name='subtree_ids', recursive=True)
    )
    below = below.union_all(
        select(StorageLocation.id)
        .join(below, StorageLocation.parent_id == below.c.id)
        .where(*visible)
    )
    subtree_rows = (
        await db.scalars(
            select(StorageLocation).where(StorageLocation.id.in_(select(below.c.id)))
        )
    ).all()
    node = next((row for row in subtree_rows if row.id == node_id), None)
    if node is None:
        return [], []
    subtree = [node, *(row for row in subtree_rows if row.id != node_id)]

    above = (
        select(StorageLocation.id, StorageLocation.parent_id, literal(1).label('depth'))
        .where(StorageLocation.id == node.parent_id, *visible)
        .cte(name='ancestor_ids', recursive=True)
    )
    above = above.union_all(
        select(StorageLocation.id, StorageLocation.parent_id, above.c.depth + 1)
        .join(above, StorageLocation.id == above.c.parent_id)
        .where(*visible)
    )
    ancestor_rows = (
        await db.scalars(
            select(StorageLocation)
            .join(above, StorageLocation.id == above.c.id)
            .order_by(above.c.depth)
        )
    ).all()
    return subtree, list(ancestor_rows)


async def list_holding_stock_with_ancestors_async(
    db: AsyncSession, organization_id: UUID, *, usage: str
) -> list[StorageLocation]:
    """The locations of *usage* that hold a live record, and the chains above them.

    For a reader that has to speak of every location holding something (a
    count task per shelf) and show where each stands: the holders and their
    ancestors come back in one statement, so a warehouse's empty shelves are
    never read. Archived locations are hidden as the listings hide them, and
    hide the chain above them.
    """
    visible = (
        StorageLocation.organization_id == organization_id,
        not_archived_condition(),
    )
    holders = (
        select(StorageLocation.id, StorageLocation.parent_id)
        .where(
            *visible,
            StorageLocation.usage == usage,
            exists().where(
                Item.storage_location_id == StorageLocation.id,
                Item.organization_id == organization_id,
                Item.is_deleted.is_(False),
            ),
        )
        .cte(name='holders_and_ancestors', recursive=True)
    )
    holders = holders.union(
        select(StorageLocation.id, StorageLocation.parent_id)
        .join(holders, StorageLocation.id == holders.c.parent_id)
        .where(*visible)
    )
    rows = await db.scalars(
        select(StorageLocation)
        .where(StorageLocation.id.in_(select(holders.c.id)))
        .order_by(StorageLocation.name.asc())
    )
    return list(rows.all())


async def list_storages_by_ids_async(
    db: AsyncSession, organization_id: UUID, storage_ids: Iterable[UUID]
) -> list[StorageLocation]:
    """The listed locations that exist and are not archived, by name."""
    wanted = list(set(storage_ids))
    found: list[StorageLocation] = []
    for start in range(0, len(wanted), 5000):
        found += (
            await db.scalars(
                select(StorageLocation).where(
                    StorageLocation.organization_id == organization_id,
                    StorageLocation.id.in_(wanted[start : start + 5000]),
                    not_archived_condition(),
                )
            )
        ).all()
    return sorted(found, key=lambda row: row.name)


def not_archived_condition():
    """SQLAlchemy condition: archived rows are hidden from lists.

       The flag lives in the existing JSON ``settings`` (no Core column, per
    the decision) — ``settings->>'archived' IS DISTINCT FROM 'true'``
       keeps rows with NULL/missing flags visible.
    """
    return StorageLocation.settings['archived'].as_string().is_distinct_from('true')


async def list_archived_async(
    db: AsyncSession,
    organization_id: UUID,
    claimed_tags: set[str] | None = None,
) -> list[StorageLocation]:
    """The locations every other listing hides — the screen that restores them.

    ``claimed_tags`` applies the same module-data policy the active tab
    follows: the two tabs of one screen must describe one population, or a
    restore is confirmed on a screen the row can never appear on.
    """
    stmt = (
        select(StorageLocation)
        .where(
            StorageLocation.organization_id == organization_id,
            StorageLocation.settings['archived'].as_string() == 'true',
        )
        .order_by(StorageLocation.name.asc())
    )
    if claimed_tags:
        stmt = stmt.where(
            or_(
                StorageLocation.context_tag.is_(None),
                ~StorageLocation.context_tag.in_(claimed_tags),
            )
        )
    result = await db.scalars(stmt)
    return list(result.all())


async def get_breadcrumb_async(
    db: AsyncSession, storage_id, organization_id
) -> list[StorageLocationBreadcrumb]:
    path: list[StorageLocationBreadcrumb] = []
    current_id = storage_id
    visited: set = set()
    while current_id and current_id not in visited:
        visited.add(current_id)
        loc = await db.scalar(
            select(StorageLocation).where(
                StorageLocation.id == current_id,
                StorageLocation.organization_id == organization_id,
            )
        )
        if not loc:
            break
        path.insert(0, StorageLocationBreadcrumb(id=loc.id, name=loc.name))
        current_id = loc.parent_id
    return path


def build_tree(
    locations: list[StorageLocation],
    item_counts: dict,
) -> list[StorageLocationNode]:
    """Builds a nested tree from a flat list of StorageLocation objects."""
    node_map: dict = {}
    below: dict = {}
    for loc in locations:
        if loc.parent_id is not None and loc.parent_id != loc.id:
            below[loc.parent_id] = below.get(loc.parent_id, 0) + 1
    for loc in locations:
        node_map[loc.id] = StorageLocationNode(
            id=loc.id,
            name=loc.name,
            parent_id=loc.parent_id,
            usage=loc.usage,
            location_type_id=loc.storage_type_id,
            short_code=loc.short_code,
            sequence=loc.sequence,
            # Module scoping, and NULL means universal -- so a node left at
            # the default does not omit the tag, it asserts the opposite of
            # it. The flat list carries it; the tree has to agree.
            context_tag=loc.context_tag,
            items_count=item_counts.get(loc.id, 0),
            children_count=below.get(loc.id, 0),
            children=[],
        )

    roots: list[StorageLocationNode] = []
    for loc in locations:
        node = node_map[loc.id]
        if loc.parent_id and loc.parent_id in node_map:
            node_map[loc.parent_id].children.append(node)
        else:
            roots.append(node)

    # nodes whose parent chain never reaches a root (a cycle, or a
    # node hanging below one) would be silently dropped here — they existed
    # in GET /locations but not in GET /locations/tree, making their items
    # unreachable from the whole UI. Append them as standalone roots instead
    # and log a warning so pre-existing damage stays visible and repairable.
    reachable: set = set()
    stack = list(roots)
    while stack:
        node = stack.pop()
        reachable.add(node.id)
        stack.extend(node.children)

    unreachable = [node for node in node_map.values() if node.id not in reachable]
    if unreachable:
        for node in unreachable:
            node.children = []  # break loop edges; the tree must stay finite
        roots.extend(unreachable)
        logger.warning(
            'Storage tree: %d node(s) unreachable from the roots '
            '(cycle or dangling parent), attached as roots: %s',
            len(unreachable),
            [str(node.id) for node in unreachable],
        )

    _fill_subtree_counts(roots)
    return roots


def ids_below(locations: list[StorageLocation], parent_id: UUID | None) -> list[UUID]:
    """Every location under ``parent_id`` (all of them for ``None``), each once.

    Cycle-guarded: it runs on whatever is in the table.
    """
    children_of: dict[UUID | None, list[UUID]] = {}
    for loc in locations:
        children_of.setdefault(loc.parent_id, []).append(loc.id)
    if parent_id is None:
        return [loc.id for loc in locations]
    seen: set[UUID] = set()
    stack = list(children_of.get(parent_id, ()))
    while stack:
        node_id = stack.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        stack.extend(children_of.get(node_id, ()))
    return list(seen)


def tree_level(
    roots: list[StorageLocationNode],
    *,
    parent_id: UUID | None,
    depth: int,
) -> list[StorageLocationNode]:
    """Cut a built tree to ``depth`` levels, starting at the roots or below one.

    With ``parent_id`` the answer is the levels *below* that location (an
    unknown one has none). The nodes keep their ``children_count`` and
    subtree counts from the whole tree; only ``children`` is dropped past the
    last level, so a screen opens a branch by asking for it.
    """
    start = roots
    if parent_id is not None:
        found: StorageLocationNode | None = None
        stack = list(roots)
        while stack and found is None:
            node = stack.pop()
            if node.id == parent_id:
                found = node
            else:
                stack.extend(node.children)
        start = found.children if found is not None else []

    def cut(nodes: list[StorageLocationNode], left: int) -> list[StorageLocationNode]:
        return [
            node.model_copy(
                update={'children': cut(node.children, left - 1) if left > 1 else []}
            )
            for node in nodes
        ]

    return cut(start, depth)


def _fill_subtree_counts(nodes: list[StorageLocationNode]) -> int:
    """Sum each node's own items with everything below it (ADR-018).

    Post-order over the tree that was just built, so it needs no parent map
    and cannot loop: the loop edges were already broken above, which is why
    this runs last rather than while the nodes are being made.
    """
    total = 0
    for node in nodes:
        node.subtree_items_count = node.items_count + _fill_subtree_counts(
            node.children
        )
        total += node.subtree_items_count
    return total


async def ensure_short_code_async(
    db: AsyncSession, storage: StorageLocation, *, user_id: UUID | None = None
) -> StorageLocation:
    """Give a location that has no code the one it would get as a new place.

    Journalled the way a renumber journals a code it changes — the same
    fact, the same entry — under *user_id*. A location that has a code keeps
    it and writes nothing.
    """
    if not storage.short_code:
        # The organization's code lock first, the order a renumber and a
        # create take it in, then the row read again under its own lock: a
        # second request for the same location waited here while the first
        # gave the code, and finds it given — it returns that code and
        # journals nothing, instead of drawing another over it and calling
        # the location uncoded before.
        await acquire_advisory_lock(db, f'storage_codes:{storage.organization_id}')
        await db.refresh(storage, with_for_update=True)
    if not storage.short_code:
        from app.models.audit_log import AuditAction, AuditTargetType
        from app.services.audit_service import log_action_async
        from app.services.storage._codes import code_for_new_location_async

        storage.short_code = await code_for_new_location_async(
            db, storage.organization_id, storage.parent_id
        )
        await db.flush()
        await db.refresh(storage)
        await log_action_async(
            db,
            organization_id=storage.organization_id,
            user_id=user_id,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.STORAGE,
            target_id=storage.id,
            snapshot={
                'name': storage.name,
                'before': {'short_code': None},
                'after': {'short_code': storage.short_code},
            },
        )
    return storage


async def scannable_code_async(
    db: AsyncSession, organization_id: UUID, storage_id: UUID
) -> str | None:
    """The code a worker can scan to name a location, or ``None`` when none exists.

    Its own short code, else the lowest code of a STORAGE pool label printed
    for it — the two shapes ``find_by_scanned_code_async`` answers to, so a
    place this names is a place that scan can find.
    """
    own = await db.scalar(
        select(StorageLocation.short_code).where(
            StorageLocation.id == storage_id,
            StorageLocation.organization_id == organization_id,
        )
    )
    if own:
        return own
    return await db.scalar(
        select(func.min(LabelPool.short_code)).where(
            LabelPool.target_storage_location_id == storage_id,
            LabelPool.organization_id == organization_id,
            LabelPool.label_type == 'STORAGE',
        )
    )


async def find_by_scanned_code_async(
    db: AsyncSession, organization_id: UUID, code: str
) -> StorageLocation | None:
    """The location a scanned code names, without taking a scan's side effects.

    The code is the location's own short code or the code of a pool label
    printed for it — the two shapes the scan chain's storage providers answer
    to. Unlike that chain this only reads: a caller that wants to know which
    shelf a worker is standing at must not count the label as scanned.
    """
    shelf = await db.scalar(
        select(StorageLocation).where(
            StorageLocation.short_code == code,
            StorageLocation.organization_id == organization_id,
        )
    )
    if shelf is not None:
        return shelf
    return await db.scalar(
        select(StorageLocation)
        .join(
            LabelPool,
            LabelPool.target_storage_location_id == StorageLocation.id,
        )
        .where(
            LabelPool.short_code == code,
            LabelPool.organization_id == organization_id,
            LabelPool.label_type == 'STORAGE',
        )
    )
