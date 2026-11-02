from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core.contracts import GlobalAIUsageStatsDTO, OrgAIUsageStatsDTO, UserContextDTO
from app.core.exceptions import TooManyRequestsException
from app.i18n import Language
from app.i18n.service import get_current_lang, get_error_message

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.ai_usage_service import AIUsageLimitExceededError


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
        from app.core.logging import get_logger
        from app.services.ai_usage_service import AIUsageLimitExceededError

        try:
            await self.check_limit_async(db, organization_id, action_type)
        except AIUsageLimitExceededError as exc:
            raise _limit_refusal(exc, get_current_lang()) from exc
        except Exception as exc:  # noqa: BLE001 — best-effort limit check, see the docstring
            get_logger(__name__).warning(
                'AI limit check failed (non-blocking): %s', exc
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
        usage = getattr(response, 'usage', None)
        if not (db and organization_id and usage):
            return
        user_uuid = UUID(user_id) if isinstance(user_id, str) else user_id
        org_uuid = (
            UUID(organization_id)
            if isinstance(organization_id, str)
            else organization_id
        )
        if org_uuid is None:
            return
        try:
            raw = getattr(response, 'raw', None)
            raw_model = raw.get('model', '') if isinstance(raw, dict) else ''
            usage_dict: dict[str, Any] = dict(usage)
            details = usage_dict.get('prompt_tokens_details')
            prompt_tokens = int(usage_dict.get('prompt_tokens', 0) or 0)
            completion_tokens = int(usage_dict.get('completion_tokens', 0) or 0)
            cached_tokens = (
                int(details.get('cached_tokens', 0) or 0)
                if isinstance(details, dict)
                else 0
            )
            provider = getattr(client, 'connection_provider', None) or 'unknown'
            from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

            # The session's ``bind`` attribute is the engine an async
            # sessionmaker needs; ``get_bind`` hands back the sync facade,
            # which is not the same thing and would fail later, mid-write.
            # A session bound to a connection (or unbound) cannot give the
            # ledger its own transaction — saying so beats guessing with a
            # cast and losing the row after a one-line log entry.
            bind = getattr(db, 'bind', None)
            if not isinstance(bind, AsyncEngine):
                raise RuntimeError(
                    'the request session is not engine-bound, so the usage '
                    'ledger cannot open its own session on the same engine'
                )
            ledger_factory = async_sessionmaker(bind=bind, expire_on_commit=False)
            async with ledger_factory() as ledger_db:
                provider_cost = usage_dict.get('total_cost') or usage_dict.get('cost')
                if provider_cost:
                    actual_cost = float(provider_cost)
                    cost_is_estimated = False
                else:
                    (
                        actual_cost,
                        cost_is_estimated,
                    ) = await self.estimate_cost_async(
                        ledger_db,
                        raw_model,
                        prompt_tokens,
                        completion_tokens,
                        cached_tokens,
                    )

                await self.log_usage_async(
                    db=ledger_db,
                    user_id=user_uuid,
                    organization_id=org_uuid,
                    model_name=raw_model,
                    provider=provider,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=int(usage_dict.get('total_tokens', 0) or 0),
                    estimated_cost_usd=actual_cost,
                    cost_is_estimated=cost_is_estimated,
                    action_type=action_type,
                )
                await ledger_db.commit()
        except Exception as log_err:  # noqa: BLE001 — best-effort logging
            from app.core.logging import get_logger

            log = get_logger(__name__)
            log.error('[AI-LOG] Failed to log usage: %s', log_err)

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


def _limit_refusal(
    exc: AIUsageLimitExceededError, lang: Language
) -> TooManyRequestsException:
    """The 429: the cause, the numbers, and the period they count over.

    The numbers travel as fields, not only inside the sentence, so a screen can
    label them without parsing prose; the sentence itself is the catalogue's
    and arrives in the reader's language.
    """
    return TooManyRequestsException(
        'AI_USAGE_LIMIT_EXCEEDED',
        exc.sentence(lang),
        details={
            'lang': lang,
            'limit_key': exc.limit_key,
            'used': exc.used,
            'limit': exc.limit,
            'period_start': exc.period_start.date().isoformat(),
            'period_end': exc.period_end.date().isoformat(),
        },
    )
