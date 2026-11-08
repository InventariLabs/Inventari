# architecture: core_service_direct_db
# This service lives in app/services/ (Core), not a module, so the architecture
# linter (which scans app/modules/) does not gate it. Direct DB access here is
# the canonical Core pattern (like other services in this package). Writes are
# flush-only — the caller (via get_async_db) owns the commit, matching the
# CoreAPI contract documented in app/core/public_api/__init__.py.

from calendar import monthrange
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError, TooManyRequestsException
from app.core.logging import get_logger
from app.i18n import Language
from app.i18n.service import get_current_lang
from app.models.ai_usage_log import AIUsageLog
from app.models.organization import Organization
from app.services.system_settings_service import (
    estimate_cost_async,
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


def limit_refusal(
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


async def enforce_ai_limit_async(
    db: AsyncSession,
    organization_id: UUID,
    action_type: str,
    *,
    check: Callable[[AsyncSession, UUID, str], Awaitable[None]] | None = None,
) -> None:
    """Gate a billable AI call: over the ceiling it refuses, an outage it ignores.

    The refusal is a 429 whose body carries what the counter measured — how
    much is used of what limit, which ceiling that was, and the period it
    applies to. ``AI usage quota exceeded`` was true and useless: it named no
    cause, no number and no period, so the reader could neither act on it nor
    report it.

    Best-effort by design: a quota service that is itself down must not take
    the feature with it, or an organization cannot scan anything because a
    counter could not be read.

    ``check`` is the counter to ask; the public facade hands in its own
    ``check_limit_async`` so that stays the one place a caller substitutes it.
    """
    try:
        await (check or check_ai_limit_async)(db, organization_id, action_type)
    except AIUsageLimitExceededError as exc:
        raise limit_refusal(exc, get_current_lang()) from exc
    except Exception as exc:  # noqa: BLE001 — best-effort limit check, see the docstring
        logger.warning('AI limit check failed (non-blocking): %s', exc)


async def log_llm_usage_async(
    db: Any,
    user_id: UUID | str | None,
    organization_id: UUID | str | None,
    response: Any,
    action_type: str,
    client: Any | None = None,
    *,
    estimate_cost: Callable[..., Awaitable[tuple[float, bool]]] | None = None,
    log_usage: Callable[..., Awaitable[object]] | None = None,
) -> None:
    """Best-effort LLM usage logging shared by vision/recipes.

    Never crashes the main flow. *response* is an ``LlmResponse``
    (duck-typed to keep the service free of core/llm imports at module
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

    ``estimate_cost`` and ``log_usage`` are the two writers to use; the
    public facade hands in its own methods, so they stay substitutable there.
    """
    estimate = estimate_cost or estimate_cost_async
    write_ledger = log_usage or log_ai_usage_async
    usage = getattr(response, 'usage', None)
    if not (db and organization_id and usage):
        return
    user_uuid = UUID(user_id) if isinstance(user_id, str) else user_id
    org_uuid = (
        UUID(organization_id) if isinstance(organization_id, str) else organization_id
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
                actual_cost, cost_is_estimated = await estimate(
                    ledger_db,
                    raw_model,
                    prompt_tokens,
                    completion_tokens,
                    cached_tokens,
                )

            await write_ledger(
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
        logger.error('[AI-LOG] Failed to log usage: %s', log_err)
