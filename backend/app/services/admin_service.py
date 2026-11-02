"""
Admin analytics service.

Provides system-level statistics for the superadmin / admin dashboard.
All read-only — backed by CoreAPI for safe data access.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger(__name__)


class AdminService:
    """Aggregator for system-wide admin stats."""

    async def get_system_summary(self, db: AsyncSession) -> dict:
        """Return top-level system metrics: user count, org count, 24h actions, AI usage."""
        from app.models.ai_usage_log import AIUsageLog
        from app.models.item_history import ItemHistory
        from app.models.organization import Organization
        from app.models.user import User

        now = datetime.now(UTC)
        last_24h = now - timedelta(hours=24)

        total_users = await db.scalar(select(func.count(User.id)))
        total_organizations = await db.scalar(select(func.count(Organization.id)))
        actions_24h = await db.scalar(
            select(func.count(ItemHistory.id)).where(ItemHistory.created_at >= last_24h)
        )

        ai_stats = (
            await db.execute(
                select(
                    func.count(AIUsageLog.id).label('calls'),
                    func.sum(AIUsageLog.total_tokens).label('tokens'),
                    func.sum(AIUsageLog.estimated_cost_usd).label('cost'),
                )
            )
        ).one_or_none()

        return {
            'counts': {
                'users': total_users or 0,
                'organizations': total_organizations or 0,
                'actions_24h': actions_24h or 0,
            },
            'ai_usage': {
                'total_calls': (ai_stats.calls or 0) if ai_stats else 0,
                'total_tokens': (ai_stats.tokens or 0) if ai_stats else 0,
                'total_cost_usd': float((ai_stats.cost or 0) if ai_stats else 0),
            },
        }

    async def get_ai_usage_stats(self, db: AsyncSession, days: int = 7) -> dict:
        """Return AI usage broken down by organization, user, and model."""
        from app.models.ai_usage_log import AIUsageLog
        from app.models.organization import Organization
        from app.models.user import User

        since_date = datetime.now(UTC) - timedelta(days=days)

        usage_by_organization = (
            await db.execute(
                select(
                    Organization.name,
                    func.count(AIUsageLog.id).label('calls'),
                    func.sum(AIUsageLog.total_tokens).label('tokens'),
                    func.sum(AIUsageLog.estimated_cost_usd).label('cost'),
                )
                .outerjoin(Organization, AIUsageLog.organization_id == Organization.id)
                .where(AIUsageLog.created_at >= since_date)
                .group_by(Organization.id, Organization.name)
                .order_by(func.sum(AIUsageLog.total_tokens).desc())
                .limit(100)
            )
        ).all()

        usage_by_user = (
            await db.execute(
                select(
                    User.email,
                    func.count(AIUsageLog.id).label('calls'),
                    func.sum(AIUsageLog.total_tokens).label('tokens'),
                    func.sum(AIUsageLog.estimated_cost_usd).label('cost'),
                )
                .outerjoin(User, AIUsageLog.user_id == User.id)
                .where(AIUsageLog.created_at >= since_date)
                .group_by(User.id, User.email)
                .order_by(func.sum(AIUsageLog.total_tokens).desc())
                .limit(100)
            )
        ).all()

        usage_by_model = (
            await db.execute(
                select(
                    AIUsageLog.model_name,
                    func.count(AIUsageLog.id).label('calls'),
                    func.sum(AIUsageLog.total_tokens).label('tokens'),
                    func.sum(AIUsageLog.estimated_cost_usd).label('cost'),
                )
                .where(AIUsageLog.created_at >= since_date)
                .group_by(AIUsageLog.model_name)
                .order_by(func.sum(AIUsageLog.total_tokens).desc())
                .limit(100)
            )
        ).all()

        return {
            'period_days': days,
            'by_organization': [
                {
                    'name': r[0] or 'Unknown Organization',
                    'calls': r[1],
                    'tokens': r[2],
                    'cost': float(r[3] or 0),
                }
                for r in usage_by_organization
            ],
            'by_user': [
                {
                    'email': r[0] or 'Unknown User',
                    'calls': r[1],
                    'tokens': r[2],
                    'cost': float(r[3] or 0),
                }
                for r in usage_by_user
            ],
            'by_model': [
                {'model': r[0], 'calls': r[1], 'tokens': r[2], 'cost': float(r[3] or 0)}
                for r in usage_by_model
            ],
        }

    async def get_activity_stats(self, db: AsyncSession, days: int = 7) -> dict:
        """Return activity timeline (daily action counts)."""
        from app.models.item_history import ItemHistory

        since_date = (datetime.now(UTC) - timedelta(days=days)).date()

        daily_actions = (
            await db.execute(
                select(
                    func.date(ItemHistory.created_at).label('date'),
                    func.count(ItemHistory.id).label('count'),
                )
                .where(ItemHistory.created_at >= since_date)
                .group_by(func.date(ItemHistory.created_at))
                .order_by('date')
                .limit(100)
            )
        ).all()

        return {'timeline': [{'date': str(r[0]), 'count': r[1]} for r in daily_actions]}


admin_service = AdminService()
