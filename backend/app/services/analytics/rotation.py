"""Inventory rotation analysis read-model.

How long items stay in storage, slow-mover detection, and dead-stock
analysis. Domain-neutral: applies to food freshness, equipment lifecycle,
and warehouse turnover alike.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    CategoryRotationDTO,
    RotationAnalysisDTO,
    RotationItemDTO,
)
from app.core.module_ownership import general_rows, hidden_module_tags_async
from app.models import Category, Item, ItemHistory, StorageLocation
from app.models.item_history import CONSUMPTION_ACTIONS, DISPOSAL_ACTIONS

from ._common import org_today_async, rounded

_MAX_ROWS = 500


async def get_rotation_analysis_async(
    db: AsyncSession, organization_id: UUID
) -> RotationAnalysisDTO:
    """Compute rotation metrics for an organization.

    A vertical module's records stay out unless the organization shows module
    data (:func:`hidden_module_tags_async`): the stock age of a pantry is not
    the age of the family laptop the products list leaves out.
    """
    today = await org_today_async(db, organization_id)
    scope = general_rows(await hidden_module_tags_async(db, organization_id))

    # Rotation by category. Grouped by the category itself, not by its name:
    # two categories may share a name, and a group of names has no code to
    # hand the reader's language.
    rotation_by_cat_rows = (
        await db.execute(
            select(
                func.coalesce(Category.name, 'Uncategorized').label('category_name'),
                Category.code.label('category_code'),
                func.count(Item.id).label('items_count'),
                func.avg(today - Item.added_date).label('avg_days'),
            )
            .outerjoin(Category, Item.category_id == Category.id)
            .where(
                Item.organization_id == organization_id,
                Item.is_deleted.is_(False),
                scope,
                Item.added_date.isnot(None),
            )
            .group_by(Category.id, Category.name, Category.code)
            # The cap is a safety valve, so it has to cut the rows nobody
            # reads rather than an arbitrary five hundred: longest-standing
            # first, name to break ties so two identical requests agree.
            .order_by(
                func.avg(today - Item.added_date).desc(),
                func.coalesce(Category.name, 'Uncategorized'),
                Category.id,
            )
            .limit(_MAX_ROWS)
        )
    ).all()
    rotation_by_category = sorted(
        [
            CategoryRotationDTO(
                category_name=row.category_name,
                category_code=row.category_code,
                average_days=rounded(row.avg_days, 1) if row.avg_days else 0.0,
                item_count=row.items_count,
            )
            for row in rotation_by_cat_rows
        ],
        key=lambda x: x.average_days or 0.0,
        reverse=True,
    )

    # Both statistics are computed in the database. Read as rows they were
    # capped at five hundred, so an organization past that reported the
    # average of the five hundred youngest records as its average -- a
    # figure that is neither the whole nor a sample of it.
    age = today - Item.added_date
    avg_active_raw, median_active_raw, active_count = _stats_of(
        await db.execute(
            select(
                func.avg(age),
                func.percentile_cont(0.5).within_group(age),
                func.count(),
            ).where(
                Item.organization_id == organization_id,
                Item.is_deleted.is_(False),
                scope,
                Item.added_date.isnot(None),
            )
        )
    )
    # The age of standing stock does not depend on anything having left:
    # an intake-only organization — every organization's first days — has a
    # real, computable age. What has no age is an empty shelf set, and None
    # is how the report says so; 0.0 days would read as the best possible
    # age. The consumption figures below keep their 0.0 "no rotation yet".
    avg_active: float | None = avg_active_raw if active_count else None
    median_active: float | None = median_active_raw if active_count else None

    # Days from arrival to consumption or disposal.
    consumed_days = func.extract(
        'day',
        ItemHistory.created_at - func.coalesce(Item.added_date, ItemHistory.created_at),
    )
    avg_consumed, median_consumed, consumed_count = _stats_of(
        await db.execute(
            select(
                func.avg(consumed_days),
                func.percentile_cont(0.5).within_group(consumed_days),
                func.count(),
            )
            .select_from(ItemHistory)
            .join(Item, ItemHistory.item_id == Item.id)
            .where(
                ItemHistory.organization_id == organization_id,
                scope,
                ItemHistory.action.in_(CONSUMPTION_ACTIONS + DISPOSAL_ACTIONS),
                Item.added_date.isnot(None),
                consumed_days > 0,
            )
        )
    )

    # Slow movers (30-90 days in storage)
    slow_movers = (
        await db.execute(
            _stock_detail_stmt(organization_id, today, 30, 90, scope=scope)
        )
    ).all()
    # Dead stock (>90 days)
    dead_stock_rows = (
        await db.execute(
            _stock_detail_stmt(organization_id, today, 90, None, _MAX_ROWS, scope=scope)
        )
    ).all()

    slow_movers_sorted = [_row_to_dto(r, today) for r in slow_movers]
    dead_stock_sorted = [_row_to_dto(r, today) for r in dead_stock_rows]

    slow_movers_value = await db.scalar(
        _value_stmt(organization_id, today, 30, 90, scope)
    )
    dead_stock_value = await db.scalar(
        _value_stmt(organization_id, today, 90, None, scope)
    )
    slow_movers_count = await db.scalar(
        _count_stmt(organization_id, today, 30, 90, scope)
    )
    dead_stock_count = await db.scalar(
        _count_stmt(organization_id, today, 90, None, scope)
    )

    return RotationAnalysisDTO(
        average_stock_age_days=avg_active,
        median_stock_age_days=median_active,
        average_days_to_consume=avg_consumed,
        median_days_to_consume=median_consumed,
        active_items_count=active_count,
        consumed_items_count=consumed_count,
        slow_movers=slow_movers_sorted,
        slow_movers_count=slow_movers_count or 0,
        slow_movers_value=rounded(slow_movers_value),
        dead_stock=dead_stock_sorted,
        dead_stock_count=dead_stock_count or 0,
        dead_stock_value=rounded(dead_stock_value),
        rotation_by_category=rotation_by_category,
    )


def _stock_columns(today: date):
    """Shared column list for slow_movers / dead_stock detail queries."""
    return (
        Item.id,
        Item.name,
        Item.brand,
        (today - Item.added_date).label('days_in_storage'),
        func.coalesce(Category.name, 'Uncategorized').label('category'),
        Category.code.label('category_code'),
        # Price times quantity: the value of what is standing there, not the
        # price of one of it.
        (func.coalesce(Item.purchase_price, 0) * Item.quantity).label('value'),
        Item.quantity,
        func.coalesce(StorageLocation.name, 'Unknown').label('storage_location'),
    )


def _stock_detail_stmt(
    org_id: UUID,
    today: date,
    min_days: int,
    max_days: int | None,
    limit: int = 10,
    *,
    scope: ColumnElement[bool],
):
    """Build a slow-mover or dead-stock detail query by age window."""
    stmt = (
        select(*_stock_columns(today))
        .outerjoin(Category, Item.category_id == Category.id)
        .outerjoin(StorageLocation, Item.storage_location_id == StorageLocation.id)
        .where(
            Item.organization_id == org_id,
            Item.is_deleted.is_(False),
            scope,
            Item.added_date.isnot(None),
            Item.added_date < today - timedelta(days=min_days),
        )
        .order_by((today - Item.added_date).desc(), Item.id)
        .limit(limit)
    )
    if max_days is not None:
        stmt = stmt.where(Item.added_date >= today - timedelta(days=max_days))
    return stmt


def _value_stmt(
    org_id: UUID,
    today: date,
    min_days: int,
    max_days: int | None,
    scope: ColumnElement[bool],
):
    """Value of the records in an age window: price times quantity.

    Off the records, because age belongs to a record on a shelf and the cost
    ledger does not know shelves. It used to sum the unit prices alone, so
    a pallet of a thousand at 1.00 was worth as much dead stock as one unit.
    """
    stmt = select(
        func.sum(func.coalesce(Item.purchase_price, 0) * Item.quantity)
    ).where(
        Item.organization_id == org_id,
        Item.is_deleted.is_(False),
        scope,
        Item.added_date.isnot(None),
        Item.added_date < today - timedelta(days=min_days),
    )
    if max_days is not None:
        stmt = stmt.where(Item.added_date >= today - timedelta(days=max_days))
    return stmt


def _count_stmt(
    org_id: UUID,
    today: date,
    min_days: int,
    max_days: int | None,
    scope: ColumnElement[bool],
):
    stmt = select(func.count(Item.id)).where(
        Item.organization_id == org_id,
        Item.is_deleted.is_(False),
        scope,
        Item.added_date.isnot(None),
        Item.added_date < today - timedelta(days=min_days),
    )
    if max_days is not None:
        stmt = stmt.where(Item.added_date >= today - timedelta(days=max_days))
    return stmt


def _row_to_dto(row, today: date) -> RotationItemDTO:
    days = row.days_in_storage
    return RotationItemDTO(
        item_id=str(row.id),
        name=row.name,
        brand=row.brand,
        days_in_storage=days.days if hasattr(days, 'days') else days,
        category=row.category,
        category_code=row.category_code,
        value=float(row.value or 0),
        quantity=float(row.quantity or 0),
        location=row.storage_location,
    )


def _stats_of(result) -> tuple[float, float, int]:
    """``(average, median, count)`` from a one-row (avg, median, count) select.

    The first two are NULL when nothing matched, which reads as zero here:
    the report has a place for "no rotation yet" and it is 0.0, not a
    missing figure. The count travels with them because it was read off the
    same rows, and was capped at five hundred along with everything else.
    """
    row = result.first()
    if row is None:
        return 0.0, 0.0, 0
    average, median, count = row
    return (
        rounded(average, 1) if average is not None else 0.0,
        rounded(median, 1) if median is not None else 0.0,
        int(count or 0),
    )
