# architecture: core_service_direct_db
# This service lives in app/services/ (Core), not a module, so the architecture
# linter (which scans app/modules/) does not gate it. Direct DB access here is
# the canonical Core pattern. Reads only.

"""AI usage stats service — global and per-org AI usage analytics.

These queries live in Core so that a hosting (cloud) module can consume
them through ``core_api.ai_usage`` without importing
``app.models.*`` or ``app.services.*`` directly.

All functions are READ-ONLY.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    AIUsageDailyStatDTO,
    AIUsageModelStatDTO,
    AIUsageProviderStatDTO,
    AIUsageTopOrgDTO,
    GlobalAIUsageStatsDTO,
    OrgAIUsageActionStatDTO,
    OrgAIUsageMonthUsageDTO,
    OrgAIUsageStatsDTO,
    OrgAIUsageUserStatDTO,
)
from app.models.ai_usage_log import AIUsageLog
from app.models.organization import Organization
from app.models.user import User
from app.services.ai_usage_service import (
    _current_month_range,
    get_org_limits_async,
)


async def get_global_ai_stats_async(
    db: AsyncSession, days: int = 30
) -> GlobalAIUsageStatsDTO:
    """Global AI usage stats for superadmin dashboard."""
    since = datetime.now(UTC) - timedelta(days=days)

    total_requests = (
        await db.scalar(
            select(func.count(AIUsageLog.id)).where(
                AIUsageLog.created_at >= since,
            )
        )
        or 0
    )
    total_tokens = (
        await db.scalar(
            select(func.sum(AIUsageLog.total_tokens)).where(
                AIUsageLog.created_at >= since,
            )
        )
        or 0
    )
    total_cost = (
        await db.scalar(
            select(func.sum(AIUsageLog.estimated_cost_usd)).where(
                AIUsageLog.created_at >= since,
            )
        )
        or 0.0
    )
    estimated_cost = (
        await db.scalar(
            select(func.sum(AIUsageLog.estimated_cost_usd)).where(
                AIUsageLog.created_at >= since,
                AIUsageLog.cost_is_estimated == True,
            )
        )
        or 0.0
    )

    top_orgs_result = await db.execute(
        select(
            Organization.id,
            Organization.name,
            func.count(AIUsageLog.id).label('requests'),
            func.sum(AIUsageLog.total_tokens).label('tokens'),
            func.sum(AIUsageLog.estimated_cost_usd).label('cost'),
        )
        .select_from(AIUsageLog)
        .join(Organization, AIUsageLog.organization_id == Organization.id)
        .where(AIUsageLog.created_at >= since)
        .group_by(Organization.id, Organization.name)
        .order_by(func.sum(AIUsageLog.estimated_cost_usd).desc())
        .limit(10)
    )
    top_orgs = top_orgs_result.all()

    by_model_result = await db.execute(
        select(
            AIUsageLog.model_name,
            func.count(AIUsageLog.id).label('requests'),
            func.sum(AIUsageLog.total_tokens).label('tokens'),
            func.sum(AIUsageLog.estimated_cost_usd).label('cost'),
        )
        .where(AIUsageLog.created_at >= since)
        .group_by(AIUsageLog.model_name)
        .order_by(func.sum(AIUsageLog.estimated_cost_usd).desc())
    )
    by_model = by_model_result.all()

    # The provider column is reported verbatim, NULL included: a row the
    # ledger never stamped is a bucket of its own, not a silent omission.
    # 'openrouter' rows written before the ledger recorded the real provider
    # cannot be told apart from true OpenRouter calls — no backfill can
    # recover what was never stored — so the bucket reads "recorded as
    # OpenRouter", which the DTO says.
    by_provider_result = await db.execute(
        select(
            AIUsageLog.provider,
            func.count(AIUsageLog.id).label('requests'),
            func.sum(AIUsageLog.total_tokens).label('tokens'),
            func.sum(AIUsageLog.estimated_cost_usd).label('cost'),
        )
        .where(AIUsageLog.created_at >= since)
        .group_by(AIUsageLog.provider)
        .order_by(func.sum(AIUsageLog.estimated_cost_usd).desc())
    )
    by_provider = by_provider_result.all()

    daily_result = await db.execute(
        select(
            func.date_trunc('day', AIUsageLog.created_at).label('day'),
            func.count(AIUsageLog.id).label('requests'),
            func.sum(AIUsageLog.estimated_cost_usd).label('cost'),
        )
        .where(AIUsageLog.created_at >= since)
        .group_by(literal_column('day'))
        .order_by(literal_column('day'))
    )
    daily = daily_result.all()

    return GlobalAIUsageStatsDTO(
        period_days=days,
        total_requests=total_requests,
        total_tokens=int(total_tokens),
        total_cost_usd=float(total_cost),
        estimated_cost_ratio=float(estimated_cost / total_cost) if total_cost else 0.0,
        top_orgs=[
            AIUsageTopOrgDTO(
                id=r.id,
                name=r.name,
                requests=r.requests,
                tokens=int(r.tokens or 0),
                cost_usd=float(r.cost or 0),
            )
            for r in top_orgs
        ],
        by_model=[
            AIUsageModelStatDTO(
                model=r.model_name,
                requests=r.requests,
                tokens=int(r.tokens or 0),
                cost_usd=float(r.cost or 0),
            )
            for r in by_model
        ],
        by_provider=[
            AIUsageProviderStatDTO(
                provider=r.provider,
                requests=r.requests,
                tokens=int(r.tokens or 0),
                cost_usd=float(r.cost or 0),
            )
            for r in by_provider
        ],
        daily=[
            AIUsageDailyStatDTO(
                date=r.day.strftime('%Y-%m-%d'),
                requests=r.requests,
                cost_usd=float(r.cost or 0),
            )
            for r in daily
        ],
    )


async def get_org_ai_stats_async(
    db: AsyncSession, organization_id: UUID, days: int = 30
) -> OrgAIUsageStatsDTO:
    """Per-organization AI usage with current month usage vs limits."""
    since = datetime.now(UTC) - timedelta(days=days)
    start, end = _current_month_range()
    limits = await get_org_limits_async(db, organization_id)

    total_requests = (
        await db.scalar(
            select(func.count(AIUsageLog.id)).where(
                AIUsageLog.organization_id == organization_id,
                AIUsageLog.created_at >= since,
            )
        )
        or 0
    )
    total_cost = (
        await db.scalar(
            select(func.sum(AIUsageLog.estimated_cost_usd)).where(
                AIUsageLog.organization_id == organization_id,
                AIUsageLog.created_at >= since,
            )
        )
        or 0.0
    )

    month_requests = (
        await db.scalar(
            select(func.count(AIUsageLog.id)).where(
                AIUsageLog.organization_id == organization_id,
                AIUsageLog.created_at >= start,
                AIUsageLog.created_at <= end,
            )
        )
        or 0
    )
    month_scans = (
        await db.scalar(
            select(func.count(AIUsageLog.id)).where(
                AIUsageLog.organization_id == organization_id,
                AIUsageLog.action_type == 'extract_label',
                AIUsageLog.created_at >= start,
                AIUsageLog.created_at <= end,
            )
        )
        or 0
    )

    # LEFT OUTER JOIN on purpose: rows with no user — connection tests,
    # background jobs, and rows whose user was deleted (the FK is
    # ON DELETE SET NULL) — must land in an explicit unassigned row, or a
    # reader summing by_user silently loses what the organization paid for.
    by_user_result = await db.execute(
        select(
            User.id,
            User.email,
            User.full_name,
            func.count(AIUsageLog.id).label('requests'),
            func.sum(AIUsageLog.total_tokens).label('tokens'),
            func.sum(AIUsageLog.estimated_cost_usd).label('cost'),
        )
        .select_from(AIUsageLog)
        .outerjoin(User, AIUsageLog.user_id == User.id)
        .where(
            AIUsageLog.organization_id == organization_id,
            AIUsageLog.created_at >= since,
        )
        .group_by(User.id, User.email, User.full_name)
        .order_by(func.sum(AIUsageLog.estimated_cost_usd).desc())
    )
    by_user = by_user_result.all()

    by_provider_result = await db.execute(
        select(
            AIUsageLog.provider,
            func.count(AIUsageLog.id).label('requests'),
            func.sum(AIUsageLog.total_tokens).label('tokens'),
            func.sum(AIUsageLog.estimated_cost_usd).label('cost'),
        )
        .where(
            AIUsageLog.organization_id == organization_id,
            AIUsageLog.created_at >= since,
        )
        .group_by(AIUsageLog.provider)
        .order_by(func.sum(AIUsageLog.estimated_cost_usd).desc())
    )
    by_provider = by_provider_result.all()

    by_action_result = await db.execute(
        select(
            AIUsageLog.action_type,
            func.count(AIUsageLog.id).label('requests'),
            func.sum(AIUsageLog.estimated_cost_usd).label('cost'),
        )
        .where(
            AIUsageLog.organization_id == organization_id,
            AIUsageLog.created_at >= since,
        )
        .group_by(AIUsageLog.action_type)
    )
    by_action = by_action_result.all()

    daily_result = await db.execute(
        select(
            func.date_trunc('day', AIUsageLog.created_at).label('day'),
            func.count(AIUsageLog.id).label('requests'),
            func.sum(AIUsageLog.estimated_cost_usd).label('cost'),
        )
        .where(
            AIUsageLog.organization_id == organization_id,
            AIUsageLog.created_at >= since,
        )
        .group_by(literal_column('day'))
        .order_by(literal_column('day'))
    )
    daily = daily_result.all()

    return OrgAIUsageStatsDTO(
        period_days=days,
        total_requests=total_requests,
        total_cost_usd=float(total_cost),
        month_usage=OrgAIUsageMonthUsageDTO(
            ai_requests_monthly=month_requests,
            ai_scans_monthly=month_scans,
        ),
        limits=limits,
        by_user=[
            OrgAIUsageUserStatDTO(
                id=r.id,
                email=r.email,
                display_name=r.full_name,
                requests=r.requests,
                tokens=int(r.tokens or 0),
                cost_usd=float(r.cost or 0),
            )
            for r in by_user
        ],
        by_provider=[
            AIUsageProviderStatDTO(
                provider=r.provider,
                requests=r.requests,
                tokens=int(r.tokens or 0),
                cost_usd=float(r.cost or 0),
            )
            for r in by_provider
        ],
        by_action=[
            OrgAIUsageActionStatDTO(
                action=r.action_type,
                requests=r.requests,
                cost_usd=float(r.cost or 0),
            )
            for r in by_action
        ],
        daily=[
            AIUsageDailyStatDTO(
                date=r.day.strftime('%Y-%m-%d'),
                requests=r.requests,
                cost_usd=float(r.cost or 0),
            )
            for r in daily
        ],
    )
