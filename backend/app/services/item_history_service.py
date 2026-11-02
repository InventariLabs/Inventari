from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import in_ids
from app.models.item import Item
from app.models.item_history import ItemHistory


async def list_by_storage_ids_async(
    db: AsyncSession,
    storage_ids: list[UUID],
    *,
    cursor_ts: datetime | None = None,
    limit: int = 50,
    context_tag: str | None = None,
    claimed_tags: set[str] | None = None,
) -> list[ItemHistory]:
    """List history entries for items in *storage_ids* (eager-loaded item+user)."""
    from sqlalchemy.orm import joinedload

    if not storage_ids:
        return []

    query = (
        select(ItemHistory)
        .join(Item, ItemHistory.item_id == Item.id)
        .options(
            joinedload(ItemHistory.item),
            joinedload(ItemHistory.user),
        )
        .where(in_ids(Item.storage_location_id, storage_ids))
    )

    if context_tag:
        from app.models.category import Category

        query = query.outerjoin(Category, Item.category_id == Category.id).where(
            Category.context_tag == context_tag
        )
    elif claimed_tags:
        # The same rule the product list applies, from the same place: an
        # entry about a module's record has no business in a general history
        # either, and the record's category is only half of what says so.
        from app.core.module_ownership import unclaimed_by_a_module

        query = query.where(unclaimed_by_a_module(claimed_tags))

    if cursor_ts is not None:
        query = query.where(ItemHistory.created_at < cursor_ts)

    result = await db.scalars(
        query.order_by(ItemHistory.created_at.desc()).limit(limit)
    )
    return list(result.unique().all())


async def list_for_item_async(
    db: AsyncSession,
    item_id: UUID,
    organization_id: UUID,
    *,
    cursor_ts: datetime | None = None,
    limit: int = 50,
    actions: Sequence[str] | None = None,
) -> list[ItemHistory]:
    """List history entries for a single *item_id* (eager-loaded item+user).

    ``actions`` narrows the query itself, so ``limit`` counts the rows the
    caller asked for — a caller wanting only status changes gets 200 of
    those, not whatever survived a 200-row cut applied before filtering."""
    from sqlalchemy.orm import joinedload

    query = (
        select(ItemHistory)
        .options(
            joinedload(ItemHistory.item),
            joinedload(ItemHistory.user),
        )
        .where(
            ItemHistory.item_id == item_id,
            ItemHistory.organization_id == organization_id,
        )
    )
    if cursor_ts is not None:
        query = query.where(ItemHistory.created_at < cursor_ts)
    if actions:
        query = query.where(ItemHistory.action.in_(actions))

    result = await db.scalars(
        query.order_by(ItemHistory.created_at.desc()).limit(limit)
    )
    return list(result.unique().all())


async def count_by_org_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    since: datetime | None = None,
    action_types: list[str] | None = None,
) -> int:
    """Async: count history records for *organization_id*."""
    query = (
        select(func.count(ItemHistory.id))
        .join(Item, Item.id == ItemHistory.item_id)
        .where(Item.organization_id == organization_id)
    )
    if since is not None:
        query = query.filter(ItemHistory.created_at >= since)
    if action_types:
        query = query.filter(ItemHistory.action.in_(action_types))
    return (await db.scalar(query)) or 0


async def list_by_org_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    item_id: UUID | None = None,
    since: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ItemHistory]:
    """Async: return history records for *organization_id*."""
    query = (
        select(ItemHistory)
        .join(Item, Item.id == ItemHistory.item_id)
        .where(Item.organization_id == organization_id)
    )
    if item_id is not None:
        query = query.filter(ItemHistory.item_id == item_id)
    if since is not None:
        query = query.filter(ItemHistory.created_at >= since)
    result = await db.scalars(
        query.order_by(ItemHistory.created_at.desc()).offset(offset).limit(limit)
    )
    return list(result.all())
