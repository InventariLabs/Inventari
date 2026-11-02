# architecture: core_service_direct_db
# This service lives in app/services/ (Core), not a module, so the architecture
# linter (which scans app/modules/) does not gate it. Direct DB access here is
# the canonical Core pattern (like other services in this package). Writes are
# flush-only — the caller (via get_async_db) owns the commit, matching the
# CoreAPI contract documented in app/core/public_api/__init__.py.

from calendar import monthrange
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError
from app.core.logging import get_logger
from app.models.ai_usage_log import AIUsageLog
from app.models.organization import Organization
from app.services.system_settings_service import (
    get_default_org_limits_async,
)

logger = get_logger(__name__)


async def log_ai_usage_async(
    db: AsyncSession,
    user_id: UUID | None,
    organization_id: UUID,
    model_name: str,
    provider: str,
    action_type: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    estimated_cost_usd: float = 0.0,
    cost_is_estimated: bool = False,
) -> AIUsageLog:
    """Write an AI usage log entry. Flushes but does NOT commit.

    The caller's transaction (typically the ``get_async_db`` dependency, which
    commits on successful request completion) owns the commit. The row is
    written in a savepoint, so a caller that treats logging as best-effort can
    catch the error and go on with its own work.

    *user_id* may be ``None`` — the column is nullable and a call the
    organization pays for is booked even when nobody was logged in
    (connection tests, background jobs). The LLM ledger path
    (``core_api.ai_usage.log_llm_usage_async``) goes further and commits its
    own session, because that row must survive a request that ends in an
    error response after the provider charged for it.
    """
    log_entry = AIUsageLog(
        user_id=user_id,
        organization_id=organization_id,
        model_name=model_name,
        provider=provider,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=estimated_cost_usd,
        cost_is_estimated=cost_is_estimated,
        action_type=action_type,
    )
    # A savepoint: a row that cannot be written takes back only itself, so a
    # caller that logs best-effort keeps the rest of its transaction.
    async with db.begin_nested():
        db.add(log_entry)
        await db.flush()
    await db.refresh(log_entry)
    return log_entry


def _current_month_range() -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    _, last_day = monthrange(now.year, now.month)
    start = datetime(now.year, now.month, 1)
    end = datetime(now.year, now.month, last_day, 23, 59, 59)
    return start, end


class AIUsageLimitExceededError(ServiceRejectionError):
    """The organization has spent the ceiling this call would draw on.

    A ``ValueError`` as the service contract promises (AGENTS.md §Backend.3),
    and one that carries what the counter measured: which ceiling fired
    (``limit_key``), how much of it is used, and the period the count was taken
    over. The sentence alone used to be all a caller got, and an API can only
    hand a reader back what it was given — "quota exceeded" with no numbers in
    it sends whoever hit the ceiling looking for the reason in the wrong place.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        limit_key: str,
        used: int,
        limit: int,
        period_start: datetime,
        period_end: datetime,
    ) -> None:
        key = (
            'ai_usage_limit_exceeded_scans'
            if limit_key == 'ai_scans_monthly'
            else 'ai_usage_limit_exceeded_requests'
        )
        super().__init__(
            key,
            used=used,
            limit=limit,
            period=' – '.join(
                (period_start.date().isoformat(), period_end.date().isoformat())
            ),
        )
        # Preserve the constructor's existing explicit-message form for callers.
        if message is not None:
            self.args = (message,)
        self.limit_key = limit_key
        self.used = used
        self.limit = limit
        self.period_start = period_start
        self.period_end = period_end


async def get_org_limits_async(
    db: AsyncSession, organization_id: UUID
) -> dict[str, Any]:
    """Async: return effective AI limits for *organization_id*."""
    org = (await db.scalars(select(Organization).filter_by(id=organization_id))).first()
    defaults = await get_default_org_limits_async(db)

    if org and org.settings and isinstance(org.settings, dict):
        org_limits = org.settings.get('limits', {})
        if org_limits is not None:
            return {key: org_limits.get(key, defaults.get(key)) for key in defaults}
    return defaults


async def check_ai_limit_async(
    db: AsyncSession, organization_id: UUID, action_type: str
) -> None:
    """Async: raise AIUsageLimitExceededError if the org has exceeded its limits.

    The refusal names the ceiling that fired and reports the count it measured
    over the current month — the numbers a caller needs to say *what* ran out.
    """
    limits = await get_org_limits_async(db, organization_id)
    start, end = _current_month_range()

    requests_limit = limits.get('ai_requests_monthly')
    if requests_limit is not None:
        current_requests = (
            await db.scalar(
                select(func.count(AIUsageLog.id)).where(
                    AIUsageLog.organization_id == organization_id,
                    AIUsageLog.created_at >= start,
                    AIUsageLog.created_at <= end,
                )
            )
        ) or 0
        if current_requests >= requests_limit:
            raise AIUsageLimitExceededError(
                limit_key='ai_requests_monthly',
                used=current_requests,
                limit=requests_limit,
                period_start=start,
                period_end=end,
            )

    if action_type == 'extract_label':
        scans_limit = limits.get('ai_scans_monthly')
        if scans_limit is not None:
            current_scans = (
                await db.scalar(
                    select(func.count(AIUsageLog.id)).where(
                        AIUsageLog.organization_id == organization_id,
                        AIUsageLog.action_type == 'extract_label',
                        AIUsageLog.created_at >= start,
                        AIUsageLog.created_at <= end,
                    )
                )
            ) or 0
            if current_scans >= scans_limit:
                raise AIUsageLimitExceededError(
                    limit_key='ai_scans_monthly',
                    used=current_scans,
                    limit=scans_limit,
                    period_start=start,
                    period_end=end,
                )


async def count_usage_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    since: datetime,
    action_type: str | None = None,
) -> int:
    """Count AI usage records for an organization since a given timestamp.

    Used by modules to check monthly usage against limits.
    """
    stmt = select(func.count(AIUsageLog.id)).where(
        AIUsageLog.organization_id == organization_id,
        AIUsageLog.created_at >= since,
    )
    if action_type is not None:
        stmt = stmt.where(AIUsageLog.action_type == action_type)

    result = await db.scalar(stmt)
    return result or 0
