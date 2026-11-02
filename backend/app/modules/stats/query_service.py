"""Facade for stats query functions.

Dashboard, consumption, cost, rotation, reconciliation, and forecast
read-models now delegate to ``core_api.queries`` (Tier 1 neutral
aggregates). The remaining module-local queries (smart alerts, purchase
patterns, shopping suggestions) are home-domain business logic that does
not pass the 3-Vertical Test and correctly stays in the module.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api

from ._analytics_queries import get_shopping_suggestions
from .schemas import PreviousMeasurement, ReconciliationResponse


async def get_consumption_stats(
    db: AsyncSession, organization_id: UUID, days: int = 30
) -> Any:
    """Usage and disposal aggregates (delegates to core_api.queries)."""
    return await core_api.queries.get_consumption_stats_async(
        db, organization_id, days=days
    )


async def get_cost_analysis(
    db: AsyncSession, organization_id: UUID, period: str = 'month'
) -> Any:
    """Cost analysis: spent, wasted, trends (delegates to core_api.queries)."""
    return await core_api.queries.get_cost_summary_async(
        db, organization_id, period=period
    )


async def get_rotation_analysis_async(db: AsyncSession, organization_id: UUID) -> Any:
    """Inventory rotation metrics (delegates to core_api.queries)."""
    return await core_api.queries.get_rotation_analysis_async(db, organization_id)


async def get_overview_stats(db: AsyncSession, organization_id: UUID) -> Any:
    """High-level inventory health snapshot (delegates to core_api.queries)."""
    return await core_api.queries.get_overview_async(db, organization_id)


async def get_low_stock_products(
    db: AsyncSession,
    organization_id: UUID,
    exclude_module_contexts: bool = False,
    *,
    offset: int = 0,
    limit: int = 100,
) -> tuple[Any, int]:
    """A page of the short products behind the overview's low-stock number.

    The total is the number itself, counted by the same rule.
    """
    rows = await core_api.queries.get_low_stock_products_async(
        db,
        organization_id,
        limit=limit,
        exclude_module_contexts=exclude_module_contexts,
        offset=offset,
    )
    total = await core_api.queries.count_low_stock_products_async(
        db, organization_id, exclude_module_contexts=exclude_module_contexts
    )
    return rows, total


async def get_stats_by_storage(db: AsyncSession, organization_id: UUID) -> Any:
    """Per-storage item counts and expiry aggregates."""
    return await core_api.queries.get_stats_by_storage_async(db, organization_id)


async def get_stats_by_category(db: AsyncSession, organization_id: UUID) -> Any:
    """Per-category item counts and stock value."""
    return await core_api.queries.get_stats_by_category_async(db, organization_id)


async def get_expiry_forecast(db: AsyncSession, organization_id: UUID) -> Any:
    """Six time-bucketed expiry counts."""
    return await core_api.queries.get_expiry_forecast_async(db, organization_id)


async def get_recent_activity(
    db: AsyncSession, organization_id: UUID, limit: int = 10
) -> Any:
    """Recent ItemHistory entries."""
    return await core_api.queries.get_recent_activity_async(
        db, organization_id, limit=limit
    )


async def get_reconciliation(db: AsyncSession, organization_id: UUID) -> Any:
    """The stock reconciliation pairs (delegates to core_api.queries).

    The screen reads the previous scheduled pass beside the fresh one — the
    pair a reader watches is the one that either stands or grows, and the
    fresh figures alone cannot say which. The core job stores one record
    per pass; this seam hands it out with the report.
    """
    report = await core_api.queries.get_reconciliation_async(db, organization_id)
    previous = await core_api.queries.get_reconciliation_previous_async(
        db, organization_id
    )
    response = ReconciliationResponse.model_validate(report.model_dump())
    if previous is not None:
        response.previous = PreviousMeasurement.model_validate(
            previous, from_attributes=True
        )
    return response


async def get_expense_forecast(
    db: AsyncSession, organization_id: UUID, period: str = 'month'
) -> Any:
    """Predicted spending from historical trends (delegates to core_api.queries)."""
    return await core_api.queries.get_expense_forecast_async(
        db, organization_id, period=period
    )


__all__ = [
    'get_consumption_stats',
    'get_cost_analysis',
    'get_expense_forecast',
    'get_expiry_forecast',
    'get_overview_stats',
    'get_recent_activity',
    'get_reconciliation',
    'get_rotation_analysis_async',
    'get_shopping_suggestions',
    'get_stats_by_category',
    'get_stats_by_storage',
]
