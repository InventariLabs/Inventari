"""Storage query helpers — complex counting and summary queries for storage endpoints.

These functions are kept separate from storage_service.py (CRUD operations) to avoid
bloating that file with read-only analytics logic.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.db_utils import in_ids
from app.models.audit_log import AuditAction, AuditLog, AuditTargetType
from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.schemas.storage_location import (
    ArchivedStorageLocation,
    InheritedFieldDefinition,
    InheritedTrackedField,
    StorageLocationSummary,
)
from app.services.storage._queries import (
    expiring_counts_by_location_async,
    item_counts_by_location_async,
    list_archived_async,
    not_archived_condition,
    subtree_item_counts,
)


def _compute_full_path(
    storage_id: UUID,
    id_to_name: dict,
    id_to_parent: dict,
    visited: set | None = None,
) -> str:
    """Recursively build full path string for a storage location."""
    if visited is None:
        visited = set()
    if storage_id in visited:
        return id_to_name.get(storage_id, '')
    visited.add(storage_id)
    parent_id = id_to_parent.get(storage_id)
    name = id_to_name.get(storage_id, '')
    if parent_id and parent_id in id_to_name:
        parent_path = _compute_full_path(parent_id, id_to_name, id_to_parent, visited)
        return f'{parent_path} → {name}' if parent_path else name
    return name


def _inherited_fields(storage_id: UUID, tree_by_id: dict) -> dict[str, list]:
    """The product fields a location takes from the locations above it.

    Walks up from the parent, nearest level first; the first level that sets
    a key gives it, so a rack's definition of a field wins over the
    warehouse's. The location's own lists are left out of the walk — the
    effective fields are the own ones plus these, and the own definition wins
    a clash (the form merges them). That clash is also why the own keys seed
    the seen sets below: a field the location defines itself is not one it
    takes from above, and listing the ancestor's shadowed copy of it showed
    one field twice on the settings screen — own and "Set on a level above".
    Cycle-guarded for legacy data.
    """
    tracked: list[InheritedTrackedField] = []
    custom: list[InheritedFieldDefinition] = []
    own = tree_by_id[storage_id]
    seen_tracked: set[str] = set(own.context_schema or [])
    seen_custom: set[str] = set()
    for definition in own.field_definitions or []:
        key = definition.get('key') if isinstance(definition, dict) else None
        if key:
            seen_custom.add(key)
    visited = {storage_id}
    current = own.parent_id
    while current is not None and current in tree_by_id and current not in visited:
        visited.add(current)
        node = tree_by_id[current]
        for key in node.context_schema or []:
            if key not in seen_tracked:
                seen_tracked.add(key)
                tracked.append(
                    InheritedTrackedField(key=key, from_id=node.id, from_name=node.name)
                )
        for definition in node.field_definitions or []:
            key = definition.get('key') if isinstance(definition, dict) else None
            if key and key not in seen_custom:
                seen_custom.add(key)
                custom.append(
                    InheritedFieldDefinition(
                        **definition, from_id=node.id, from_name=node.name
                    )
                )
        current = node.parent_id
    return {
        'inherited_context_schema': tracked,
        'inherited_field_definitions': custom,
    }


async def _backfill_filtered_ancestors_async(
    db: AsyncSession,
    organization_id: UUID,
    id_to_name: dict,
    id_to_parent: dict,
) -> None:
    """Extend the naming maps with ancestors the listing filter dropped.

    A location whose parent is hidden by the module-data policy would
    otherwise present itself as a root — nameable, but homeless. Walk the
    missing links upward until the chain closes; cycle-guarded for legacy
    data, org-scoped like every read in this module.
    """
    missing = {p for p in id_to_parent.values() if p and p not in id_to_name}
    while missing:
        rows = (
            await db.scalars(
                select(StorageLocation).where(
                    in_ids(StorageLocation.id, missing),
                    StorageLocation.organization_id == organization_id,
                )
            )
        ).all()
        for row in rows:
            id_to_name[row.id] = row.name
            id_to_parent[row.id] = row.parent_id
        missing = {
            row.parent_id
            for row in rows
            if row.parent_id is not None and row.parent_id not in id_to_name
        }


async def location_paths_async(
    db: AsyncSession,
    organization_id: UUID,
    locations: list[StorageLocation],
) -> dict[UUID, str]:
    """Each location's path as the storages list writes it, root first.

    The names of the locations given are the starting point; the ancestors
    above them are read in as many round trips as the tree is deep.
    """
    id_to_name = {loc.id: loc.name for loc in locations}
    id_to_parent = {loc.id: loc.parent_id for loc in locations}
    await _backfill_filtered_ancestors_async(
        db, organization_id, id_to_name, id_to_parent
    )
    return {
        loc.id: _compute_full_path(loc.id, id_to_name, id_to_parent)
        for loc in locations
    }


def _belongs_to_module(module_name: str, organization_id: UUID) -> ColumnElement[bool]:
    """Locations one vertical module may call its own.

    Two answers, not one. A location tagged for the module is obviously its
    own; so is an untagged location with the module's records standing in it,
    and leaving those out is what makes a tag-only filter wrong. The equipment
    form has never required a tagged location, so most of an installation's
    assets stand in ordinary ones.

    A module nobody registered claims nothing — a mistyped scope narrows to an
    empty list rather than quietly handing back the whole organization, which
    is the failure the parameter exists to end.

    A record holds both its home and the place it stands in now
    (``standing_location``): a place the module put one in for a while is
    listed with the count its link opens, and the home stays listed, since
    the record still belongs there and keeps it from being deleted.
    """
    from app.core.module_ownership import claimed_by_module, standing_location
    from app.core.module_scope import get_context_tags_of

    tags = get_context_tags_of(module_name)
    if not tags:
        return false()

    records = (
        Item.organization_id == organization_id,
        claimed_by_module(module_name, tags),
        Item.is_deleted.is_(False),
    )
    homes = select(Item.storage_location_id).where(*records)
    standing = select(standing_location(module_name, organization_id)).where(*records)
    return or_(
        StorageLocation.context_tag.in_(tags),
        StorageLocation.id.in_(homes),
        StorageLocation.id.in_(standing),
    )


def _descendants_of(
    roots: list[UUID], children_of: dict[UUID, list[UUID]]
) -> list[UUID]:
    """The given locations and everything below them, each once.

    The ``seen`` set is what keeps a cycle in legacy data from looping: the
    walk runs on whatever is in the table.
    """
    seen: set[UUID] = set()
    stack = list(roots)
    while stack:
        node_id = stack.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        stack.extend(children_of.get(node_id, ()))
    return list(seen)


def _listing_conditions(
    organization_id: UUID,
    usage: str | None,
    *,
    context_tag: str | None,
    claimed_tags: set[str] | None,
    module_scope: str | None,
    include_archived: bool,
    type_ids: list[UUID] | None = None,
) -> list[ColumnElement[bool]]:
    conditions = [StorageLocation.organization_id == organization_id]
    # Archived rows stay hidden unless the ask names them: a listing that
    # names what records stand in reaches them, a picker never does.
    if not include_archived:
        conditions.append(not_archived_condition())
    if usage:
        conditions.append(StorageLocation.usage == usage)
    if type_ids is not None:
        conditions.append(StorageLocation.storage_type_id.in_(type_ids))
    if module_scope is not None:
        conditions.append(_belongs_to_module(module_scope, organization_id))
    elif context_tag == '__none__':
        conditions.append(StorageLocation.context_tag.is_(None))
    elif context_tag:
        conditions.append(StorageLocation.context_tag == context_tag)
    elif claimed_tags:
        conditions.append(
            or_(
                StorageLocation.context_tag.is_(None),
                ~StorageLocation.context_tag.in_(claimed_tags),
            )
        )
    return conditions


def _matching_rows(
    listed: Sequence[Any],
    *,
    id_to_name: dict[UUID, str],
    all_parents: dict[UUID, UUID | None],
    ids: list[UUID] | None,
    parent_id: UUID | None,
    below: set[UUID] | None,
    top_level: bool,
    query: str | None,
) -> list[Any]:
    """The listed rows the ask names, in walk order and then by name."""
    wanted_ids = set(ids) if ids is not None else None
    needle = query.strip().casefold() if query else ''

    def matches(row: Any) -> bool:
        if wanted_ids is not None and row.id not in wanted_ids:
            return False
        if parent_id is not None and row.parent_id != parent_id:
            return False
        if below is not None and row.id not in below:
            return False
        if top_level and row.parent_id is not None:
            return False
        if not needle:
            return True
        return (
            needle in row.name.casefold()
            or bool(row.short_code and needle in row.short_code.casefold())
            or needle in _compute_full_path(row.id, id_to_name, all_parents).casefold()
        )

    selected = [row for row in listed if matches(row)]

    def rank(row: Any) -> int:
        # What was typed names a place by its own name or code first; a place
        # that matches only through the path of its ancestors comes after
        # them. In walk order the shelves of a warehouse would fill a page
        # before the warehouse typed in full did.
        if not needle:
            return 0
        own = (row.name.casefold(), (row.short_code or '').casefold())
        if needle in own:
            return 0
        if any(needle in text for text in own):
            return 1
        return 2

    selected.sort(
        key=lambda row: (
            rank(row),
            row.sequence is None,
            row.sequence or 0,
            row.name.casefold(),
            str(row.id),
        )
    )
    return selected


def _children_index(parents: dict[UUID, UUID | None]) -> dict[UUID, list[UUID]]:
    children_of: dict[UUID, list[UUID]] = {}
    for child_id, parent in parents.items():
        if parent is not None:
            children_of.setdefault(parent, []).append(child_id)
    return children_of


class _PageCounts:
    """The record counts of one page of locations, each map keyed by location."""

    def __init__(self) -> None:
        self.direct: dict[UUID, int] = {}
        self.subtree: dict[UUID, int] = {}
        self.expiring: dict[UUID, int] = {}
        self.total_direct: dict[UUID, int] = {}
        self.total_subtree: dict[UUID, int] = {}


async def _page_counts_async(
    db: AsyncSession,
    organization_id: UUID,
    page_ids: list[UUID],
    *,
    listed_parents: dict[UUID, UUID | None],
    all_parents: dict[UUID, UUID | None],
    module_scope: str | None,
    claimed_tags: set[str] | None,
    narrowed_to_general: bool,
) -> _PageCounts:
    """Count the records the page shows, and what stands below its places.

    Only the page's places and their descendants are asked of the records, so
    a page of shelves costs a page of shelves; the root of a warehouse costs
    the warehouse, which is why a caller that prints no number does not ask.
    """
    counts = _PageCounts()
    # Subtree counts fold over the rows the listing shows on purpose: a
    # narrowed listing counts what it can open.
    below = _descendants_of(page_ids, _children_index(listed_parents))
    # The delete consequence travels with the SUBTREE, so its all-modules
    # count rides every listing, scoped or not, and folds over the full
    # organization tree below the page's rows, never over this listing's:
    # a fold over the rows would undersell the consequence by exactly the
    # records the filter removed.
    below_all = _descendants_of(page_ids, _children_index(all_parents))
    narrowed = module_scope is not None or narrowed_to_general
    if narrowed:
        counts_below = await item_counts_by_location_async(
            db,
            organization_id,
            below,
            module_scope=module_scope,
            claimed_tags=claimed_tags if narrowed_to_general else None,
        )
        all_direct = await item_counts_by_location_async(db, organization_id, below_all)
        # When the counts were narrowed to a module, the all-modules total
        # travels alongside: deleting a location is refused while any
        # module's record stands DIRECTLY in it, so a screen showing narrowed
        # numbers would enable a delete the server refuses, justified by a
        # number it never showed. Direct on purpose: children are reparented
        # on delete, not asked first.
        counts.total_direct = {i: all_direct.get(i, 0) for i in page_ids}
    else:
        # Nothing narrows the count: one read answers both folds.
        all_direct = await item_counts_by_location_async(
            db, organization_id, list({*below, *below_all})
        )
        counts_below = all_direct
    counts.direct = {i: counts_below.get(i, 0) for i in page_ids}
    counts.subtree = subtree_item_counts(
        counts_below, {i: listed_parents.get(i) for i in below}
    )
    counts.expiring = await expiring_counts_by_location_async(
        db, organization_id, page_ids
    )
    counts.total_subtree = subtree_item_counts(
        all_direct, {i: all_parents.get(i) for i in below_all}
    )
    return counts


async def list_storages_with_counts_async(
    db: AsyncSession,
    organization_id: UUID,
    usage: str | None,
    *,
    context_tag: str | None = None,
    claimed_tags: set[str] | None = None,
    module_scope: str | None = None,
    include_archived: bool = False,
    query: str | None = None,
    ids: list[UUID] | None = None,
    parent_id: UUID | None = None,
    under: UUID | None = None,
    top_level: bool = False,
    type_ids: list[UUID] | None = None,
    with_fields: bool = False,
    with_counts: bool = True,
    offset: int = 0,
    limit: int | None = None,
) -> tuple[list[StorageLocationSummary], int]:
    """One page of the organization's locations, and how many match in all.

    The selection (filters, ``query``, ``ids``, ``parent_id``, ``top_level``)
    and the order are settled on a light read of the matching rows, so a page
    costs what the page holds: only its rows are loaded whole, and the record
    counts are asked of the locations the page shows (and what stands below
    them) instead of of the whole organization. A screen that shows a place
    asks for that place; it never reads the catalogue to find it.

    ``with_counts=False`` leaves every record count at zero and skips the
    aggregate over the records: a picker offering places does not print a
    number beside them, and a root's subtree count is a scan of everything in
    the warehouse.
    """
    # One read answers both what the listing matches and the organization's
    # whole tree, because the children a delete lifts are a number no listing
    # carries on its rows: a module scope drops the locations its filter
    # leaves out, and an unscoped listing still hides archived rows and
    # whatever the usage and context filters take away. A child the listing
    # dropped is still a child the delete reparents. Light query (links,
    # names and the two field lists, no relations). The fields a location
    # inherits come from the same rows: an ancestor the listing's filter
    # drops still applies its fields to everything inside it, and a row the
    # filter still shows can say where it lives even when the module-data
    # policy keeps its parent off the list. One statement rather than two so
    # both are one picture of the table: a location deleted between a
    # listing read and a tree read was on the first and missing from the
    # second, and looking it up in the tree answered 500.
    tree_rows = (
        await db.execute(
            select(
                StorageLocation.id,
                StorageLocation.parent_id,
                StorageLocation.name,
                StorageLocation.short_code,
                StorageLocation.sequence,
                StorageLocation.context_schema,
                StorageLocation.field_definitions,
                and_(
                    *_listing_conditions(
                        organization_id,
                        usage,
                        context_tag=context_tag,
                        claimed_tags=claimed_tags,
                        module_scope=module_scope,
                        include_archived=include_archived,
                        type_ids=type_ids,
                    )
                ).label('listed'),
            ).where(StorageLocation.organization_id == organization_id)
        )
    ).all()
    listed = [row for row in tree_rows if row.listed]
    all_parents: dict[UUID, UUID | None] = {row.id: row.parent_id for row in tree_rows}
    tree_by_id = {row.id: row for row in tree_rows}
    id_to_name: dict[UUID, str] = {row.id: row.name for row in tree_rows}

    selected = _matching_rows(
        listed,
        id_to_name=id_to_name,
        all_parents=all_parents,
        ids=ids,
        parent_id=parent_id,
        below=(
            set(_descendants_of([under], _children_index(all_parents))) - {under}
            if under is not None
            else None
        ),
        top_level=top_level,
        query=query,
    )
    if with_fields:
        selected = [row for row in selected if row.field_definitions]
    total = len(selected)
    page_rows = selected[offset : offset + limit if limit is not None else None]
    page_ids = [row.id for row in page_rows]
    if not page_ids:
        return [], total

    loaded = (
        await db.scalars(
            select(StorageLocation)
            .options(joinedload(StorageLocation.storage_type))
            .where(StorageLocation.id.in_(page_ids))
        )
    ).unique()
    by_id = {s.id: s for s in loaded}
    storages = [by_id[i] for i in page_ids if i in by_id]

    listed_parents: dict[UUID, UUID | None] = {row.id: row.parent_id for row in listed}
    ids_with_children: set = {p for p in listed_parents.values() if p is not None}
    direct_children_map: dict[UUID, int] = {}
    for parent in all_parents.values():
        if parent is not None:
            direct_children_map[parent] = direct_children_map.get(parent, 0) + 1
    listed_children_map: dict[UUID, int] = {}
    for parent in listed_parents.values():
        if parent is not None:
            listed_children_map[parent] = listed_children_map.get(parent, 0) + 1

    # The general screens' filter narrows the counts as well as the rows: the
    # locations it keeps still hold module records, and a row counting them
    # disagrees with the list it opens, asked with the same flag.
    narrowed_to_general = (
        module_scope is None and not context_tag and bool(claimed_tags)
    )
    counts = (
        await _page_counts_async(
            db,
            organization_id,
            page_ids,
            listed_parents=listed_parents,
            all_parents=all_parents,
            module_scope=module_scope,
            claimed_tags=claimed_tags,
            narrowed_to_general=narrowed_to_general,
        )
        if with_counts
        else _PageCounts()
    )

    return [
        StorageLocationSummary(
            id=s.id,
            name=s.name,
            parent_id=s.parent_id,
            short_code=s.short_code,
            sequence=s.sequence,
            settings=s.settings,
            location_type=s.storage_type,  # type: ignore[arg-type]
            context_schema=s.context_schema or [],
            behavior_mode=s.behavior_mode or 'STOCK',
            field_definitions=s.field_definitions or [],
            **_inherited_fields(s.id, tree_by_id),
            context_tag=s.context_tag,
            usage=s.usage,
            items_count=counts.direct.get(s.id, 0),
            subtree_items_count=counts.subtree.get(s.id, 0),
            total_items_count=counts.total_direct.get(s.id, 0),
            total_subtree_items_count=counts.total_subtree.get(s.id, 0),
            direct_children_count=direct_children_map.get(s.id, 0),
            listed_children_count=listed_children_map.get(s.id, 0),
            expiring_soon_count=counts.expiring.get(s.id, 0),
            full_path=_compute_full_path(s.id, id_to_name, all_parents),
            is_leaf=s.id not in ids_with_children,
        )
        for s in storages
    ], total


async def _archived_dates_async(
    db: AsyncSession,
    organization_id: UUID,
    storage_ids: list[UUID],
) -> dict[UUID, datetime]:
    """When each location left the lists — the organization journal's account.

    ``archive_storage`` records a ``SOFT_DELETE`` / ``storage`` entry and
    writes no date of its own (the flag lives in ``settings``), so the journal
    is where that moment lives. The latest entry wins: a location that was
    restored and archived again is dated by the archive that holds now. A row
    flagged outside the API has no entry and is simply absent here.
    """
    if not storage_ids:
        return {}
    rows = (
        await db.execute(
            select(
                AuditLog.target_id,
                func.max(AuditLog.created_at).label('archived_at'),
            )
            .where(
                AuditLog.organization_id == organization_id,
                AuditLog.action == AuditAction.SOFT_DELETE,
                AuditLog.target_type == AuditTargetType.STORAGE,
                in_ids(AuditLog.target_id, storage_ids),
            )
            .group_by(AuditLog.target_id)
        )
    ).all()
    return {row[0]: row[1] for row in rows}


async def list_archived_with_details_async(
    db: AsyncSession,
    organization_id: UUID,
    claimed_tags: set[str] | None = None,
) -> list[ArchivedStorageLocation]:
    """``GET /locations/archived``: where each location stood, and when it left.

    The screen's job is choosing between rows that may share a name, so the
    row carries the path — the identity every other screen uses (the active
    listing's ``full_path``, the cards' parent overline) and the archive used
    to drop. The parent chain is backfilled past archived and filtered-out
    ancestors alike: a "Shelf 1" under a parent that is itself archived is
    still that parent's shelf.
    """
    storages = await list_archived_async(db, organization_id, claimed_tags)
    if not storages:
        return []
    id_to_name: dict = {s.id: s.name for s in storages}
    id_to_parent: dict = {s.id: s.parent_id for s in storages}
    await _backfill_filtered_ancestors_async(
        db, organization_id, id_to_name, id_to_parent
    )
    archived_at_map = await _archived_dates_async(
        db, organization_id, [s.id for s in storages]
    )
    result_list = []
    for s in storages:
        row = ArchivedStorageLocation.model_validate(s)
        row.full_path = _compute_full_path(s.id, id_to_name, id_to_parent)
        row.archived_at = archived_at_map.get(s.id)
        result_list.append(row)
    return result_list
