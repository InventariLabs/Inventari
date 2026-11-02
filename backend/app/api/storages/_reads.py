import io
from uuid import UUID

from fastapi import Depends, Query
from fastapi.responses import StreamingResponse

from app.config import settings
from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import (
    NotFoundException,
    catalogue_refusal,
)
from app.core.public_api import core_api
from app.i18n.service import get_current_lang
from app.schemas.pagination import PaginatedResponse
from app.schemas.storage_location import (
    StorageLocationSummary,
)
from app.services.storage._labels import (
    label_shows_description,
    storage_label_caption,
)
from app.services.storage._queries import (
    build_tree,
    get_breadcrumb_async,
    ids_below,
    item_counts_by_location_async,
    list_for_org_with_filters_async,
    tree_level,
)
from app.services.storage_query_service import (
    list_archived_with_details_async,
    list_storages_with_counts_async,
)


def _resolve_claimed_tags(exclude_module_contexts: bool) -> set[str] | None:
    """Resolve claimed context tags when exclude_module_contexts is set."""
    if not exclude_module_contexts:
        return None
    from app.core.module_scope import get_claimed_context_tags

    return get_claimed_context_tags() or None


async def get_storages(
    usage: str | None = Query(
        'internal',
        description='Filter by usage (internal, customer, inventory). '
        "Pass 'all' to include the virtual counterparts the default hides.",
    ),
    include_archived: bool = Query(
        False,
        description='Include archived locations. The default hides them; a '
        'caller that names what records stand in needs the ask, a picker '
        'does not.',
    ),
    context_tag: str | None = Query(
        None,
        description='Filter by module context tag (e.g. equipment, food). '
        'Use __none__ to get only untagged (universal) locations.',
    ),
    exclude_module_contexts: bool = Query(
        False,
        description='Hide locations whose context_tag belongs to a vertical module',
    ),
    module_scope: str | None = Query(
        None,
        description=(
            'Locations one vertical module may call its own: tagged for it, or '
            'holding its records. A module screen wants this rather than '
            'context_tag, which alone loses the untagged locations its records '
            'actually stand in.'
        ),
    ),
    q: str | None = Query(
        None,
        max_length=100,
        description='Only locations whose name, code or path contains this text.',
    ),
    ids: list[UUID] | None = Query(
        None,
        max_length=200,
        description='Only these locations: how a screen names the places its '
        'rows stand in without reading the catalogue.',
    ),
    parent_id: UUID | None = Query(
        None, description='Only the direct children of this location.'
    ),
    under: UUID | None = Query(
        None,
        description='Only the locations below this one, at any depth: how a '
        'screen asks which of a few places lie inside a zone.',
    ),
    top_level: bool = Query(
        False, description='Only locations with no parent: the warehouses.'
    ),
    type_ids: list[UUID] | None = Query(
        None,
        max_length=200,
        description='Only locations of these location types: how a screen asks '
        'whether any place keeps a shelf life without reading them all.',
    ),
    with_fields: bool = Query(
        False,
        description='Only locations that set product fields of their own: '
        'what the import dialog offers as columns.',
    ),
    counts: bool = Query(
        True,
        description='Count the records in each location. A picker offering '
        'places passes false: the counts are an aggregate over the records '
        'and no row of it prints one. The counts then read zero.',
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.STORAGES_READ),
):
    """One page of the user's storage locations, with item counts.

    The page is selected, ordered (walk order, then name) and counted from
    light columns, so a request costs what its page holds however many
    locations the organization has.
    """
    assert current_user.organization_id is not None, 'Organization required'
    claimed_tags = _resolve_claimed_tags(exclude_module_contexts)
    storages, total = await list_storages_with_counts_async(
        db,
        current_user.organization_id,
        None if usage == 'all' else usage,
        context_tag=context_tag,
        claimed_tags=claimed_tags,
        module_scope=module_scope,
        include_archived=include_archived,
        query=q,
        ids=ids,
        parent_id=parent_id,
        under=under,
        top_level=top_level,
        type_ids=type_ids,
        with_fields=with_fields,
        with_counts=counts,
        offset=offset,
        limit=limit,
    )
    return PaginatedResponse.from_slice(storages, offset, limit, total)


async def get_storage_tree(
    usage: str | None = Query(
        'internal',
        description='Filter by usage (internal, customer, inventory). '
        "Pass 'all' to include the virtual counterparts the default hides.",
    ),
    context_tag: str | None = Query(
        None,
        description='Filter by module context tag (e.g. equipment, food). '
        'Use __none__ to get only untagged (universal) locations.',
    ),
    exclude_module_contexts: bool = Query(
        False,
        description='Hide locations whose context_tag belongs to a vertical module',
    ),
    parent_id: UUID | None = Query(
        None,
        description='Answer the levels below this location instead of from '
        'the roots; one level unless depth says more.',
    ),
    depth: int | None = Query(
        None,
        ge=1,
        le=20,
        description='How many levels to answer; the nodes at the last level '
        'carry children_count and an empty children list. Without it the '
        'whole tree comes back, which a screen asks for only when it draws '
        'all of it.',
    ),
    counts: bool = Query(
        True,
        description='Count the records in each node. A screen that draws '
        'no number passes false: the counts are an aggregate over every '
        'record below the nodes answered.',
    ),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.STORAGES_READ),
):
    """Hierarchical tree of the organization's storage locations, whole or one level at a time."""
    org_id = require_org(current_user)

    # Core-internal endpoint: tree building needs ORM parents/children, so it
    # uses the service directly (the module-facing facade returns DTOs only).
    locations = await list_for_org_with_filters_async(
        db,
        org_id,
        usage=None if usage == 'all' else usage,
        context_tag=context_tag,
    )
    claimed_tags = _resolve_claimed_tags(exclude_module_contexts)
    if claimed_tags:
        locations = [
            loc
            for loc in locations
            if not loc.context_tag or loc.context_tag not in claimed_tags
        ]
    if parent_id is not None and depth is None:
        depth = 1

    # The counts answer the flag too: a location the filter keeps goes on
    # holding module records, and counting them put "27" on a storage bar
    # beside a product list that — asked with the same flag — held none.
    # A level is counted over what stands below its nodes and nothing else;
    # near the roots that is still most of the warehouse, and a screen that
    # prints no number says so with counts=false.
    counted = (
        ids_below(locations, parent_id)
        if depth is not None
        else [loc.id for loc in locations]
    )
    counts_map = (
        await item_counts_by_location_async(
            db, org_id, counted, claimed_tags=claimed_tags
        )
        if counts
        else {}
    )

    tree = build_tree(locations, counts_map)
    if depth is not None:
        return tree_level(tree, parent_id=parent_id, depth=depth)
    return tree


async def get_storage_breadcrumb(
    location_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.STORAGES_READ),
):
    """Returns ordered path from root to this location."""
    lang = get_current_lang()
    org_id = require_org(current_user)
    storage = await core_api.locations.get_async(db, org_id, location_id)
    if not storage:
        raise NotFoundException('storage', lang)
    return await get_breadcrumb_async(db, location_id, org_id)


async def list_archived_storages(
    exclude_module_contexts: bool = Query(
        False,
        description='Hide locations whose context_tag belongs to a vertical module',
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.STORAGES_READ),
):
    """Archived locations — the same module scope as the active tab next to it.

    The pair of tabs describes one population: an archive that lists rows the
    active tab filters out confirms restores that the active tab can never
    show. Each row carries its path and archive date: the screen's choice is
    between locations that may share a name.
    """
    org_id = require_org(current_user)
    claimed_tags = _resolve_claimed_tags(exclude_module_contexts)
    archived = await list_archived_with_details_async(db, org_id, claimed_tags)
    return PaginatedResponse.from_full_list(archived, offset=offset, limit=limit)


async def get_storage_detail(
    location_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.STORAGES_READ),
):
    """Storage location details."""
    lang = get_current_lang()
    org_id = require_org(current_user)
    storage = await core_api.locations.get_with_type_async(db, org_id, location_id)
    if not storage:
        raise NotFoundException('storage', lang)
    return storage


async def get_storage_summary(
    location_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.STORAGES_READ),
):
    """Storage location status summary."""
    lang = get_current_lang()
    org_id = require_org(current_user)
    storage = await core_api.locations.get_with_type_async(db, org_id, location_id)
    if not storage:
        raise NotFoundException('storage', lang)

    items_count = await core_api.locations.count_items_in_location_async(
        db, org_id, location_id
    )
    subtree_items_count = await core_api.locations.count_items_in_subtree_async(
        db, org_id, location_id
    )
    expiring_soon_count = await core_api.locations.count_expiring_soon_async(
        db, org_id, location_id
    )

    return StorageLocationSummary(
        id=storage.id,
        name=storage.name,
        location_type=storage.location_type,  # type: ignore[arg-type]
        usage=storage.usage,
        items_count=items_count,
        subtree_items_count=subtree_items_count,
        expiring_soon_count=expiring_soon_count,
    )


async def get_storage_items(
    location_id: UUID,
    include_inside: bool = Query(
        False,
        description='Also the products of every location below this one, at '
        'any depth, in one answer.',
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.STORAGES_READ),
):
    """List of products in given storage location."""
    lang = get_current_lang()
    org_id = require_org(current_user)
    storage = await core_api.locations.get_async(db, org_id, location_id)
    if not storage:
        raise NotFoundException('storage', lang)

    # A place's products grow with the stock, and with include_inside with the
    # whole subtree: the page is cut in the database, never from a full list.
    count_items = (
        core_api.locations.count_items_in_subtree_async
        if include_inside
        else core_api.locations.count_items_in_location_async
    )
    total = await count_items(db, org_id, location_id)
    items = await core_api.locations.list_items_in_location_async(
        db,
        org_id,
        location_id,
        include_inside=include_inside,
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse.from_slice(items, offset=offset, limit=limit, total=total)


async def print_storage_label(
    location_id: UUID,
    width: float = Query(50.0),
    height: float = Query(24.0),
    base_url: str | None = Query(None),
    show_description: bool | None = Query(None),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.STORAGES_READ),
):
    """Generates a PNG label for a specific storage location."""
    from app.core.label_rendering import render_label_png

    storage = await core_api.locations.get_async(
        db, require_org(current_user), location_id
    )

    if not storage:
        raise NotFoundException('storage')

    if not storage.short_code:
        raise catalogue_refusal('storage_no_short_code')

    class MockLabel:
        def __init__(self, code, desc):
            self.short_code = code
            self.description = desc
            self.label_type = 'STORAGE'

    target_base_url = base_url if base_url else settings.FRONTEND_URL

    if show_description is not None:
        show_desc = show_description
    else:
        show_desc = label_shows_description(storage)
    label_desc = storage_label_caption(storage, show_desc)

    mock_label = MockLabel(storage.short_code, label_desc)

    try:
        png_data = render_label_png(
            mock_label,
            width_mm=width,
            height_mm=height,
            base_url=target_base_url,
            qr_only=not show_desc,
        )

        return StreamingResponse(
            io.BytesIO(png_data),
            media_type='image/png',
            headers={
                'Content-Disposition': f'attachment; filename=storage_label_{storage.short_code}.png'
            },
        )
    except (OSError, ValueError) as exc:
        # The global handler logs it and answers 500 with the catalogue's
        # sentence in the reader's language; a ValueError left to travel on
        # would be taken for a refusal and answered 400.
        raise RuntimeError('Storage label could not be rendered') from exc


async def get_storage_codes(
    location_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.STORAGES_READ),
):
    """How the warehouse holding this location makes its codes, and which
    locations wait for a new sticker."""
    from app.services.storage._codes import warehouse_codes_async

    org_id = require_org(current_user)
    codes = await warehouse_codes_async(db, org_id, location_id)
    if codes is None:
        raise NotFoundException('storage', get_current_lang())
    return codes
