"""The AI usage report accounts for every row it counted.

Two ways the report did not add up:

- the per-user breakdown joined ``users`` with an INNER JOIN, so calls with
  no user (connection tests, background jobs, rows whose user was deleted)
  fell out of ``by_user`` while remaining in ``total_requests``;
- the provider column had no reader at all, so local (zero-cost) and hosted
  spend sat in one pile and the split could only be read with psql.

``by_user`` now carries an explicit *unassigned* row (``id`` and ``email``
are null), so ``sum(by_user.requests)`` equals ``total_requests``, and both
reports carry ``by_provider``.

The provider values are the ones the ledger stored, reported verbatim.
``'unknown'`` is what the LLM ledger writes when the caller named no client;
``None`` is a row the ledger never stamped. Rows written before the ledger
recorded the real provider all carry ``'openrouter'``, local model or not --
the true provider was never stored, no backfill can recover it, and the
bucket therefore means "recorded as OpenRouter", not "verified".
"""

from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_usage_log import AIUsageLog
from app.models.organization import Organization
from app.models.user import User
from app.services.ai_usage_stats_service import (
    get_global_ai_stats_async,
    get_org_ai_stats_async,
)

pytestmark = pytest.mark.integration


def _row(
    organization_id: UUID,
    *,
    provider: str | None,
    user_id: UUID | None = None,
    tokens: int = 10,
    cost: float = 0.01,
) -> AIUsageLog:
    return AIUsageLog(
        organization_id=organization_id,
        user_id=user_id,
        model_name='gpt-4o',
        provider=provider,
        total_tokens=tokens,
        estimated_cost_usd=cost,
        cost_is_estimated=False,
        action_type='chat',
    )


@pytest.mark.asyncio
class TestTheAIUsageReportAccountsForEveryRow:
    async def test_the_org_breakdown_adds_up_when_a_call_has_no_user(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db = real_async_db_session
        db.add_all(
            [
                _row(
                    async_test_household.id,
                    provider='openrouter',
                    user_id=async_test_user.id,
                ),
                _row(async_test_household.id, provider='ollama', user_id=None),
            ]
        )
        await db.flush()

        stats = await get_org_ai_stats_async(db, async_test_household.id)

        assert stats.total_requests == 2
        assert sum(row.requests for row in stats.by_user) == stats.total_requests
        unassigned = [row for row in stats.by_user if row.id is None]
        assert len(unassigned) == 1
        assert unassigned[0].email is None
        assert unassigned[0].requests == 1
        assert unassigned[0].tokens == 10

    async def test_the_org_report_splits_cost_by_provider(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db = real_async_db_session
        db.add_all(
            [
                _row(
                    async_test_household.id,
                    provider='openrouter',
                    user_id=async_test_user.id,
                    cost=0.02,
                ),
                _row(
                    async_test_household.id, provider='ollama', user_id=None, cost=0.0
                ),
                _row(async_test_household.id, provider='unknown', user_id=None),
                _row(
                    async_test_household.id,
                    provider=None,
                    user_id=async_test_user.id,
                ),
            ]
        )
        await db.flush()

        stats = await get_org_ai_stats_async(db, async_test_household.id)

        by_provider = {row.provider: row for row in stats.by_provider}
        assert set(by_provider) == {'openrouter', 'ollama', 'unknown', None}
        assert sum(row.requests for row in stats.by_provider) == stats.total_requests
        assert sum(row.cost_usd for row in stats.by_provider) == pytest.approx(
            stats.total_cost_usd
        )
        assert by_provider[None].requests == 1
        assert by_provider['ollama'].cost_usd == 0.0

    async def test_the_global_report_splits_cost_by_provider(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db = real_async_db_session
        db.add_all(
            [
                _row(
                    async_test_household.id,
                    provider='openrouter',
                    user_id=async_test_user.id,
                    cost=0.02,
                ),
                _row(
                    async_test_household.id, provider='google', user_id=None, cost=0.0
                ),
            ]
        )
        await db.flush()

        stats = await get_global_ai_stats_async(db)

        by_provider = {row.provider: row for row in stats.by_provider}
        assert set(by_provider) == {'openrouter', 'google'}
        assert sum(row.requests for row in stats.by_provider) == stats.total_requests
        assert by_provider['openrouter'].cost_usd == pytest.approx(0.02)
        assert by_provider['google'].cost_usd == 0.0
