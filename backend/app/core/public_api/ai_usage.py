from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core.contracts import GlobalAIUsageStatsDTO, OrgAIUsageStatsDTO, UserContextDTO
from app.i18n.service import get_current_lang, get_error_message

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class CoreAIUsageAPI:
    """Public Core API for AI usage rate-limiting, cost estimation, and logging."""

    async def check_limit_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        action_type: str,
    ) -> None:
        """Async: raise AIUsageLimitExceededError if the org has exceeded its limits."""
        from app.services.ai_usage_service import check_ai_limit_async

        await check_ai_limit_async(db, organization_id, action_type)

    async def enforce_limit_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        action_type: str,
    ) -> None:
        """Gate a billable AI call: over the ceiling it refuses, an outage it ignores.

        The refusal is a 429 whose body carries what the counter measured —
        how much is used of what limit, which ceiling that was, and the period
        it applies to. ``AI usage quota exceeded`` was true and useless: it
        named no cause, no number and no period, so the reader could neither
        act on it nor report it.

        Best-effort by design: a quota service that is itself down must not
        take the feature with it, or an organization cannot scan anything
        because a counter could not be read.
        """
        from app.services.ai_usage_service import enforce_ai_limit_async

        await enforce_ai_limit_async(
            db, organization_id, action_type, check=self.check_limit_async
        )

    async def estimate_cost_async(
        self,
        db: AsyncSession,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        cache_read_tokens: int = 0,
    ) -> tuple[float, bool]:
        """Async: return (estimated_cost_usd, is_estimated) for the given model and token counts.
        cache_read_tokens: number of input tokens served from cache (cached pricing applies).
        """
        from app.services.system_settings_service import estimate_cost_async

        return await estimate_cost_async(
            db, model_name, prompt_tokens, completion_tokens, cache_read_tokens
        )

    async def log_usage_async(
        self,
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
    ) -> None:
        """Async: log AI usage record to the database."""
        from app.services.ai_usage_service import log_ai_usage_async

        await log_ai_usage_async(
            db=db,
            user_id=user_id,
            organization_id=organization_id,
            model_name=model_name,
            provider=provider,
            action_type=action_type,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost_usd,
            cost_is_estimated=cost_is_estimated,
        )

    async def log_llm_usage_async(
        self,
        db: AsyncSession,
        user_id: UUID | str | None,
        organization_id: UUID | str | None,
        response: Any,
        action_type: str,
        client: Any | None = None,
    ) -> None:
        """Best-effort LLM usage logging shared by vision/recipes.

        Never crashes the main flow. *response* is an ``LlmResponse``
        (duck-typed to keep the facade free of core/llm imports at module
        scope). *client* is the adapter that made the call — the ledger
        reads from it the provider who actually answered.

        The row is a bookkeeping record, not part of the business
        transaction, so it is written and committed in its own session
        bound to the same engine: a request that ends in an error response
        after the provider answered (422 for an unusable answer, 503 for a
        failed read-back) still leaves behind the tokens it was charged
        for. A call the provider never answered still writes nothing.
        A call without a user (connection tests, background jobs) is still
        a call the organization pays for — the column is nullable on
        purpose, and withholding the row would blind both the cost stats
        and the monthly limit to real spend.

        The ledger session sees only data committed before the call: a
        flow that creates the organization or user inside its own
        uncommitted transaction and then logs usage would trip the foreign
        key, and the best-effort wrapper would swallow it into a log line.
        Commit first, then log.
        """
        from app.services.ai_usage_service import log_llm_usage_async

        await log_llm_usage_async(
            db,
            user_id,
            organization_id,
            response,
            action_type,
            client,
            estimate_cost=self.estimate_cost_async,
            log_usage=self.log_usage_async,
        )

    async def count_usage_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        since: datetime,
        action_type: str | None = None,
    ) -> int:
        """Count AI usage records for an organization since a given timestamp.

        Used by modules to check monthly usage against limits.
        """
        from app.services.ai_usage_service import count_usage_async

        return await count_usage_async(
            db, organization_id, since=since, action_type=action_type
        )

    async def get_global_stats_async(
        self,
        db: AsyncSession,
        *,
        user: UserContextDTO,
        days: int = 30,
    ) -> GlobalAIUsageStatsDTO:
        """Global AI usage stats: requests, cost, top orgs, by model, daily chart.

        Requires superuser privileges (cross-tenant surface).
        """
        if not user.is_superuser:
            raise PermissionError(
                get_error_message('superuser_required', get_current_lang())
            )
        from app.services.ai_usage_stats_service import get_global_ai_stats_async

        return await get_global_ai_stats_async(db, days=days)

    async def get_org_stats_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        days: int = 30,
    ) -> OrgAIUsageStatsDTO:
        """Per-org AI usage breakdown with current month usage vs limits."""
        from app.services.ai_usage_stats_service import get_org_ai_stats_async

        return await get_org_ai_stats_async(db, organization_id, days=days)
