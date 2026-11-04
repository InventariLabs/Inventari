"""Dashboard breakdown read-models.

Per-storage, per-category, expiry-forecast, and recent-activity
aggregates. Domain-neutral: identical SQL for food, equipment, or
warehouse verticals.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.contracts import (
    ActivityDTO,
    CategoryStatsDTO,
    ExpiryBucketDTO,
    StorageStatsDTO,
)
from app.core.db_utils import in_ids
from app.core.module_ownership import general_rows, hidden_module_tags_async
from app.models import Category, Item, ItemHistory, StorageLocation
from app.models.storage_location import LocationUsage
from app.services.items.expiry import is_expired, is_expiring_soon
from app.services.storage._queries import (
    list_storage_ids_async,
    not_archived_condition,
)

from ._common import (
    get_internal_storage_ids_async,
    get_org_currency_async,
    org_currency_filter,
    org_today_async,
)


async def get_stats_by_storage_async(
    db: AsyncSession, organization_id: UUID
) -> list[StorageStatsDTO]:
    """Item counts and expiry aggregates per storage location.

    A vertical module's places and records stay out unless the organization
    shows module data (:func:`hidden_module_tags_async`), as they stay out of
    the products list. So does an archived place, as it does from every list
    of places, and a container with no records of its own: an aisle at 0 says
    nothing about its racks, and reads as a shelf with room on it.
    """
    hidden = await hidden_module_tags_async(db, organization_id)
    # Real shelves only: the system's consumed / loss / production places are
    # move targets. A used-up product stays there as a row of quantity 0, so
    # counting them put a phantom place at the head of the chart and made the
    # breakdown add up to more than the overview's record count.
    storages_query = select(StorageLocation).where(
        StorageLocation.organization_id == organization_id,
        StorageLocation.usage == LocationUsage.INTERNAL,
        not_archived_condition(),
    )
    if hidden:
        storages_query = storages_query.where(
            or_(
                StorageLocation.context_tag.is_(None),
                StorageLocation.context_tag.notin_(hidden),
            )
        )
    storages_result = await db.execute(
        storages_query.options(joinedload(StorageLocation.storage_type))
        # A stable order, so a page of the breakdown holds still between reads.
        .order_by(StorageLocation.name, StorageLocation.id)
    )
    storages = storages_result.unique().scalars().all()

    if not storages:
        return []

    today = await org_today_async(db, organization_id)

    stats_query = await db.execute(
        select(
            Item.storage_location_id,
            func.count(Item.id).label('total'),
            func.count(case((is_expiring_soon(today), 1))).label('expiring_soon'),
        )
        .where(
            Item.storage_location_id.in_([s.id for s in storages]),
            Item.is_deleted.is_(False),
            general_rows(hidden),
        )
        .group_by(Item.storage_location_id)
    )
    stats_map = {row.storage_location_id: row for row in stats_query.all()}
    containers = {storage.parent_id for storage in storages}

    return [
        StorageStatsDTO(
            location_id=storage.id,
            location_name=storage.name,
            location_type=storage.storage_type.type_code
            if storage.storage_type
            else 'UNKNOWN',
            items_count=stats_map[storage.id].total if storage.id in stats_map else 0,
            expiring_soon=stats_map[storage.id].expiring_soon
            if storage.id in stats_map
            else 0,
        )
        for storage in storages
        if storage.id in stats_map or storage.id not in containers
    ]


async def get_stats_by_category_async(
    db: AsyncSession, organization_id: UUID
) -> list[CategoryStatsDTO]:
    """Item counts and stock value aggregated per category.

    A category a vertical module claims stays out unless the organization
    shows module data, as its records stay out of the products list.
    """
    hidden = await hidden_module_tags_async(db, organization_id)
    storage_ids = await get_internal_storage_ids_async(db, organization_id, hidden)
    if not storage_ids:
        return []

    org_currency = await get_org_currency_async(db, organization_id)

    stats = (
        await db.execute(
            select(
                Category.id,
                Category.name,
                Category.code,
                Category.icon,
                func.count(Item.id).label('items_count'),
                func.sum(Item.quantity * func.coalesce(Item.purchase_price, 0)).label(
                    'total_value'
                ),
                func.count(Item.id)
                .filter(Item.purchase_price.is_(None))
                .label('unpriced_count'),
            )
            .outerjoin(Category, Item.category_id == Category.id)
            .where(
                in_ids(Item.storage_location_id, storage_ids),
                Item.is_deleted.is_(False),
                # One policy, shared with every other value report: ours or
                # unstated. Matching the organization exactly made rows with
                # no currency at all disappear from the total.
                org_currency_filter(Item.currency, org_currency),
                general_rows(hidden),
            )
            .group_by(Category.id, Category.name, Category.code, Category.icon)
            .order_by(Category.name.nulls_last(), Category.id)
        )
    ).all()

    return [
        CategoryStatsDTO(
            category_id=stat[0],
            category_name=stat[1] or 'Uncategorized',
            category_code=stat[2],
            category_icon=stat[3],
            items_count=stat[4],
            total_value=float(stat[5] or 0),
            unpriced_count=int(stat[6] or 0),
        )
        for stat in stats
    ]


async def get_expiry_forecast_async(
    db: AsyncSession, organization_id: UUID
) -> list[ExpiryBucketDTO]:
    """Six time-bucketed expiry counts (Expired through This month)."""
    hidden = await hidden_module_tags_async(db, organization_id)
    storage_ids = await list_storage_ids_async(db, organization_id)
    if not storage_ids:
        return []

    today = await org_today_async(db, organization_id)

    stats = (
        await db.execute(
            select(
                func.count(case((is_expired(today), 1))).label('expired_count'),
                func.count(
                    case(
                        (
                            (Item.effective_expiry_date >= today)
                            & (Item.effective_expiry_date < today + timedelta(days=1)),
                            1,
                        )
                    )
                ).label('today_count'),
                func.count(
                    case(
                        (
                            (Item.effective_expiry_date >= today + timedelta(days=1))
                            & (Item.effective_expiry_date < today + timedelta(days=2)),
                            1,
                        )
                    )
                ).label('tomorrow_count'),
                func.count(
                    case(
                        (
                            (Item.effective_expiry_date >= today + timedelta(days=2))
                            & (Item.effective_expiry_date < today + timedelta(days=7)),
                            1,
                        )
                    )
                ).label('this_week_count'),
                func.count(
                    case(
                        (
                            (Item.effective_expiry_date >= today + timedelta(days=7))
                            & (Item.effective_expiry_date < today + timedelta(days=14)),
                            1,
                        )
                    )
                ).label('next_2_weeks_count'),
                func.count(
                    case(
                        (
                            (Item.effective_expiry_date >= today + timedelta(days=14))
                            & (Item.effective_expiry_date < today + timedelta(days=30)),
                            1,
                        )
                    )
                ).label('this_month_count'),
            ).where(
                in_ids(Item.storage_location_id, storage_ids),
                Item.is_deleted.is_(False),
                Item.effective_expiry_date.isnot(None),
                general_rows(hidden),
            )
        )
    ).first()

    if not stats:
        return []

    return [
        ExpiryBucketDTO(period='Expired', count=stats.expired_count or 0),
        ExpiryBucketDTO(period='Today', count=stats.today_count or 0),
        ExpiryBucketDTO(period='Tomorrow', count=stats.tomorrow_count or 0),
        ExpiryBucketDTO(period='This week', count=stats.this_week_count or 0),
        ExpiryBucketDTO(period='Next 2 weeks', count=stats.next_2_weeks_count or 0),
        ExpiryBucketDTO(period='This month', count=stats.this_month_count or 0),
    ]


async def get_recent_activity_async(
    db: AsyncSession, organization_id: UUID, limit: int = 10
) -> list[ActivityDTO]:
    """Recent ItemHistory entries with item and user names."""
    result = await db.execute(
        select(ItemHistory)
        .options(joinedload(ItemHistory.item), joinedload(ItemHistory.user))
        .where(ItemHistory.organization_id == organization_id)
        .order_by(ItemHistory.created_at.desc())
        .limit(limit)
    )
    history = result.unique().scalars().all()

    return [
        ActivityDTO(
            id=h.id,
            action=h.action,
            item_name=h.item.name if h.item else 'Unknown Product',
            created_at=h.created_at,
            user_name=h.user.full_name if h.user else 'Unknown User',
            details=h.changes,
        )
        for h in history
    ]
