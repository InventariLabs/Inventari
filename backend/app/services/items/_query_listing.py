"""Multi-item listing queries.

Groups functions that return multiple items in a paginated / grouped
manner. Single-item lookups live in ``_query_get.py``, barcode/serial
lookups and counting in ``_query_lookup.py``, and view-specific
specialized queries (expiring, low_stock, archived) in
``_query_special.py``.
"""

from collections.abc import Iterable
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.item import Item
from app.models.storage_location import StorageLocation


async def list_by_org_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    storage_location_id: UUID | None = None,
    template_id: UUID | None = None,
    storage_usage: str | None = None,
    category_id: UUID | None = None,
    context_tag: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Item]:
    """Return non-deleted items for *organization_id* in descending created_at order."""
    query = select(Item).options(
        selectinload(Item.category),
        selectinload(Item.storage_location),
        selectinload(Item.uom),
        selectinload(Item.template),
    )
    if storage_usage is not None:
        query = query.join(
            StorageLocation, Item.storage_location_id == StorageLocation.id
        ).where(StorageLocation.usage == storage_usage)

    query = query.where(
        Item.organization_id == organization_id,
        Item.is_deleted.is_(False),
    )
    if storage_location_id is not None:
        query = query.where(Item.storage_location_id == storage_location_id)
    if template_id is not None:
        query = query.where(Item.template_id == template_id)
    if category_id is not None:
        query = query.where(Item.category_id == category_id)
    if context_tag is not None:
        from app.core.module_ownership import (
            claimed_category_ids_async,
            items_with_context_tag,
        )

        category_ids = await claimed_category_ids_async(
            db, organization_id, context_tag
        )
        query = query.where(items_with_context_tag(context_tag, category_ids))

    result = await db.scalars(
        query.order_by(Item.created_at.desc()).offset(offset).limit(limit)
    )
    return list(result.all())


async def list_expiring_by_template_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    template_ids: set[UUID],
    expiry_after: date,
    expiry_before: date,
) -> dict[UUID, list[Item]]:
    """Load items expiring within a date range, grouped by template_id.

    Used to surface soon-to-expire items for rotation decisions
    (FEFO picking, planner suggestions, recall queries).
    Returns a dict mapping template_id → list of matching items.
    """
    if not template_ids:
        return {}

    result = await db.execute(
        select(Item).where(
            Item.organization_id == organization_id,
            Item.template_id.in_(template_ids),
            Item.quantity > 0,
            Item.effective_expiry_date.isnot(None),
            Item.effective_expiry_date >= expiry_after,
            Item.effective_expiry_date <= expiry_before,
        )
    )
    items = list(result.scalars().all())

    grouped: dict[UUID, list[Item]] = {}
    for item in items:
        if item.template_id is not None:
            grouped.setdefault(item.template_id, []).append(item)
    return grouped


async def list_by_expiry_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    template_ids: Iterable[UUID] | None = None,
    location_id: UUID | None = None,
    storage_usage: str | None = None,
    order: str = 'asc',
    include_nulls_last: bool = True,
    limit: int = 500,
) -> list[Item]:
    """List active items sorted by ``expiry_date`` (FEFO picking order).

    Tier 2 CoreAPI extension used by recipes picking, planner suggestions,
    and any consumer that needs FEFO-sorted item availability.

    Args:
        organization_id: Org scope (mandatory).
        template_ids: Optional filter — restrict to items bound to these templates.
        location_id: Optional filter — restrict to one storage location.
        storage_usage: Optional filter — restrict to storage locations with
            this ``usage`` value (e.g. ``"INTERNAL"`` for cost estimation
            that excludes customer-side stock).
        order: 'asc' (FEFO — earliest expiry first) or 'desc'.
        include_nulls_last: When True, items with NULL expiry sort last regardless
            of order direction. Matches the legacy DB-level ``ORDER BY
            expiry_date ASC NULLS LAST`` behavior used by recipes.
        limit: Safety cap (default 500).

    Returns:
        List of ``Item`` rows with eager-loaded ``uom`` and ``storage_location``
        (the relations recipes picking reads without further queries).
    """
    query = (
        select(Item)
        .options(
            selectinload(Item.uom),
            selectinload(Item.storage_location),
        )
        .where(
            Item.organization_id == organization_id,
            Item.is_deleted.is_(False),
            Item.quantity > 0,
        )
    )
    if template_ids is not None:
        tids = list(template_ids)
        if not tids:
            return []
        query = query.where(Item.template_id.in_(tids))
    if location_id is not None:
        query = query.where(Item.storage_location_id == location_id)
    if storage_usage is not None:
        query = query.join(
            StorageLocation, Item.storage_location_id == StorageLocation.id
        ).where(StorageLocation.usage == storage_usage)

    sort_col = (
        Item.effective_expiry_date.asc()
        if order == 'asc'
        else Item.effective_expiry_date.desc()
    )
    if include_nulls_last and order == 'asc':
        sort_col = Item.effective_expiry_date.asc().nullslast()
    elif include_nulls_last and order == 'desc':
        sort_col = Item.effective_expiry_date.desc().nullslast()

    query = query.order_by(sort_col, Item.quantity.desc()).limit(limit)
    result = await db.scalars(query)
    return list(result.all())


async def list_with_template_async(
    db: AsyncSession,
    organization_id: UUID,
    template_ids: Iterable[UUID],
) -> dict[UUID, list[Item]]:
    """Batch-load active items grouped by template_id (with relations).

    Tier 2 CoreAPI extension used by recipes availability checks and any
    consumer that needs an item-by-template lookup map. Avoids N+1
    queries when callers iterate over a list of templates.

    Returns:
        Dict mapping template_id → list of items. Templates with no
        matching items map to ``[]`` (callers can ``.get(tid, [])``
        safely).
    """
    tids = list(template_ids)
    if not tids:
        return {}

    result = await db.execute(
        select(Item)
        .options(
            selectinload(Item.uom),
            selectinload(Item.storage_location),
        )
        .where(
            Item.organization_id == organization_id,
            Item.template_id.in_(tids),
            Item.is_deleted.is_(False),
            Item.quantity > 0,
        )
        .order_by(Item.effective_expiry_date.asc().nullslast(), Item.quantity.desc())
    )
    items = list(result.scalars().all())

    grouped: dict[UUID, list[Item]] = {tid: [] for tid in tids}
    for item in items:
        if item.template_id is not None:
            grouped.setdefault(item.template_id, []).append(item)
    return grouped


async def distinct_uom_ids_for_template_async(
    db: AsyncSession,
    organization_id: UUID,
    template_id: UUID,
) -> list[UUID | None]:
    """Every distinct unit the items of one product carry, no rows loaded.

    Answers "what unit do this product's shelves actually hold" over the
    WHOLE set — a paginated sample would let a hundred newest rows outvote
    an older one and flip the convertibility verdict both ways. A single
    column, a single query: no relations, no limit.
    """
    result = await db.execute(
        select(Item.uom_id)
        .distinct()
        .where(
            Item.organization_id == organization_id,
            Item.template_id == template_id,
        )
    )
    return list(result.scalars().all())
