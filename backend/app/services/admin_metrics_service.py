# architecture: core_service_direct_db
# This service lives in app/services/ (Core), not a module, so the architecture
# linter (which scans app/modules/) does not gate it. Direct DB access here is
# the canonical Core pattern (like other services in this package). Reads only.

"""Admin metrics service — superadmin analytics read-models.

These queries live in Core so that a hosting (cloud) module can consume
them through ``core_api.admin`` without importing ``app.models.*``.

All functions are READ-ONLY (no flush, no commit). The router/session
that calls them owns the transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    AdminOrgMemberDTO,
    AdminOrgMetricsDTO,
    GlobalAdminStatsDTO,
)
from app.models.ai_usage_log import AIUsageLog
from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User


async def list_org_metrics_async(db: AsyncSession) -> list[AdminOrgMetricsDTO]:
    """List all organizations with SaaS metrics (member/item/storage/value/activity/waste).

    Batched — 7 set-based queries instead of orgs × (6 + members)
    round-trips. Each aggregate is grouped by organization_id in SQL and
    joined in memory.
    """
    from sqlalchemy import and_

    organizations = (await db.scalars(select(Organization))).all()
    thirty_days_ago = datetime.now(UTC) - timedelta(days=30)

    # Members + their 30-day action counts in one pass (LEFT JOIN keeps
    # users with zero activity; count() over NULL is 0).
    member_rows = (
        await db.execute(
            select(
                User.id,
                User.organization_id,
                User.email,
                User.full_name,
                User.role,
                User.is_active,
                User.is_blocked,
                func.count(ItemHistory.id).label('actions_30d'),
            )
            .outerjoin(
                ItemHistory,
                and_(
                    ItemHistory.user_id == User.id,
                    ItemHistory.created_at >= thirty_days_ago,
                ),
            )
            .group_by(User.id)
            .order_by(User.id)
        )
    ).all()

    members_by_org: dict[UUID, list[AdminOrgMemberDTO]] = {}
    for row in member_rows:
        members_by_org.setdefault(row.organization_id, []).append(
            AdminOrgMemberDTO(
                id=row.id,
                email=row.email,
                full_name=row.full_name,
                role=row.role,
                actions_30d=row.actions_30d or 0,
                is_active=row.is_active,
                is_blocked=row.is_blocked,
            )
        )

    async def _counts_by_org(
        org_col: Any, id_col: Any, *extra_conditions: Any
    ) -> dict[UUID, int]:
        stmt = (
            select(org_col, func.count(id_col))
            .where(*extra_conditions)
            .group_by(org_col)
        )
        return {row[0]: row[1] for row in (await db.execute(stmt)).all()}

    item_counts = await _counts_by_org(
        Item.organization_id,
        Item.id,
        Item.is_deleted == False,  # noqa: E712
    )
    storage_counts = await _counts_by_org(
        StorageLocation.organization_id, StorageLocation.id
    )
    waste_counts = await _counts_by_org(
        Item.organization_id,
        Item.id,
        Item.is_deleted == True,  # noqa: E712
        # The two reasons that mean the goods were thrown away rather than
        # used up. Both are written by the delete dialog today.
        Item.deletion_reason.in_(['EXPIRED', 'DISPOSED']),
    )

    # Total inventory value: sum per org where item currency matches the
    # organization's currency (original per-org semantics).
    value_rows = (
        await db.execute(
            select(
                Item.organization_id,
                # Times the quantity: a price alone is not a value, and this
                # summed one row of a thousand units the same as one unit.
                func.sum(Item.quantity * func.coalesce(Item.purchase_price, 0)).label(
                    'total_value'
                ),
            )
            .join(Organization, Organization.id == Item.organization_id)
            .where(
                Item.is_deleted == False,  # noqa: E712
                Item.currency == Organization.currency,
            )
            .group_by(Item.organization_id)
        )
    ).all()
    values_by_org = {row.organization_id: float(row.total_value) for row in value_rows}

    # 30-day activity per org (history rows joined through Item).
    activity_rows = (
        await db.execute(
            select(Item.organization_id, func.count(ItemHistory.id))
            .select_from(ItemHistory)
            .join(Item, Item.id == ItemHistory.item_id)
            .where(ItemHistory.created_at >= thirty_days_ago)
            .group_by(Item.organization_id)
        )
    ).all()
    activity_by_org = {row[0]: row[1] for row in activity_rows}

    results: list[AdminOrgMetricsDTO] = []
    for organization in organizations:
        members = members_by_org.get(organization.id, [])
        results.append(
            AdminOrgMetricsDTO(
                id=organization.id,
                short_id=organization.short_id,
                name=organization.name,
                created_at=organization.created_at,
                member_count=len(members),
                item_count=item_counts.get(organization.id, 0),
                location_count=storage_counts.get(organization.id, 0),
                total_value=values_by_org.get(organization.id, 0.0),
                currency=(organization.settings or {}).get('currency', 'USD'),
                activity_30d=activity_by_org.get(organization.id, 0),
                waste_count=waste_counts.get(organization.id, 0),
                members=members,
                allowed_modules=organization.allowed_modules or [],
            )
        )

    return sorted(results, key=lambda item: item.activity_30d, reverse=True)


async def get_global_admin_stats_async(db: AsyncSession) -> GlobalAdminStatsDTO:
    """Global system stats for SaaS owner: totals + engagement trends."""
    now = datetime.now(UTC)
    one_day_ago = now - timedelta(days=1)
    seven_days_ago = now - timedelta(days=7)

    dau = (
        await db.scalar(
            select(func.count(func.distinct(ItemHistory.user_id))).where(
                ItemHistory.created_at >= one_day_ago,
            )
        )
        or 0
    )
    wau = (
        await db.scalar(
            select(func.count(func.distinct(ItemHistory.user_id))).where(
                ItemHistory.created_at >= seven_days_ago,
            )
        )
        or 0
    )
    total_scans_30d = (
        await db.scalar(
            select(func.count(ItemHistory.id)).where(
                ItemHistory.created_at >= (now - timedelta(days=30)),
            )
        )
        or 0
    )
    total_llm_cost_usd = float(
        (await db.scalar(select(func.sum(AIUsageLog.estimated_cost_usd)))) or 0
    )

    return GlobalAdminStatsDTO(
        total_organizations=(await db.scalar(select(func.count(Organization.id)))) or 0,
        total_users=(await db.scalar(select(func.count(User.id)))) or 0,
        active_items=(
            await db.scalar(select(func.count(Item.id)).where(Item.is_deleted == False))  # noqa: E712
        )
        or 0,
        dau=dau,
        wau=wau,
        total_llm_cost_usd=total_llm_cost_usd,
        total_scans_30d=total_scans_30d,
    )
