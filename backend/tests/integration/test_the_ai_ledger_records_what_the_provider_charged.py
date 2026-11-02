"""The AI usage ledger records what the provider actually charged.

Three refusals used to hide real spend from ``ai_usage_logs``:

- a call without a user (connection tests, background jobs) wrote nothing,
  though the column is nullable and the provider charged the tokens —
  the cost stats and the monthly limit never saw the money;
- the row was only flushed into the request's transaction, so an endpoint
  that answered 422 or 503 after the provider replied rolled the row back
  together with the business data — precisely the calls a reader wants to
  see were the ones that vanished;
- every row claimed ``provider='openrouter'``, whether OpenRouter answered
  or a local Ollama did, so cost could not be broken down per provider.

The ledger row is bookkeeping, not part of the business transaction: it is
written and committed in its own session, and it names the provider the
call actually went through.
"""

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm.base import LlmResponse
from app.core.public_api import core_api
from app.models.ai_usage_log import AIUsageLog
from app.services.ai_usage_service import check_ai_limit_async

pytestmark = pytest.mark.integration


def _answer(raw_model: str = 'llama3') -> LlmResponse:
    return LlmResponse(
        content='{"name": "Milk"}',
        usage={'prompt_tokens': 7, 'completion_tokens': 3, 'total_tokens': 10},
        raw={'model': raw_model},
    )


class _OllamaClient:
    """Shape of the real adapters: the ledger reads the provider off it."""

    connection_name = 'Local box'
    model_name = 'llama3'
    connection_provider = 'ollama'


async def _org_row_ids(db: AsyncSession, org_id: UUID) -> set[UUID]:
    return set(
        await db.scalars(
            select(AIUsageLog.id).where(AIUsageLog.organization_id == org_id)
        )
    )


@pytest.mark.asyncio
class TestTheLedgerRecordsWhatTheProviderCharged:
    async def test_a_call_without_a_user_still_leaves_its_row(
        self, real_async_db_session: AsyncSession, async_test_household
    ) -> None:
        # The ledger session sees only committed data — a bookkeeping row
        # cannot reference an organization that exists solely inside
        # this test's uncommitted transaction.
        await real_async_db_session.commit()
        ids_before = await _org_row_ids(real_async_db_session, async_test_household.id)

        await core_api.ai_usage.log_llm_usage_async(
            db=real_async_db_session,
            user_id=None,
            organization_id=async_test_household.id,
            response=_answer(),
            action_type='connection_test',
        )

        ids_after = await _org_row_ids(real_async_db_session, async_test_household.id)
        new_ids = ids_after - ids_before
        assert len(new_ids) == 1
        row = await real_async_db_session.get(AIUsageLog, new_ids.pop())
        assert row is not None
        assert row.user_id is None
        assert row.action_type == 'connection_test'
        assert row.total_tokens == 10

    async def test_the_row_survives_the_callers_rollback(
        self, real_async_db_session: AsyncSession, async_test_household
    ) -> None:
        """The endpoint died after the provider answered — the charge stays."""
        # The ledger session sees only committed data — a bookkeeping row
        # cannot reference an organization that exists solely inside
        # this test's uncommitted transaction.
        await real_async_db_session.commit()
        # Rollback expires every instance in the session — read the id into
        # a plain UUID before it, or the refresh after it needs sync IO.
        org_id: UUID = async_test_household.id
        ids_before = await _org_row_ids(real_async_db_session, org_id)

        await core_api.ai_usage.log_llm_usage_async(
            db=real_async_db_session,
            user_id=None,
            organization_id=org_id,
            response=_answer(),
            action_type='connection_test',
        )
        await real_async_db_session.rollback()

        ids_after = await _org_row_ids(real_async_db_session, org_id)
        assert len(ids_after - ids_before) == 1

    async def test_the_row_names_the_provider_that_answered(
        self, real_async_db_session: AsyncSession, async_test_household
    ) -> None:
        # The ledger session sees only committed data — a bookkeeping row
        # cannot reference an organization that exists solely inside
        # this test's uncommitted transaction.
        await real_async_db_session.commit()
        ids_before = await _org_row_ids(real_async_db_session, async_test_household.id)

        await core_api.ai_usage.log_llm_usage_async(
            db=real_async_db_session,
            user_id=None,
            organization_id=async_test_household.id,
            response=_answer(),
            action_type='connection_test',
            client=_OllamaClient(),
        )

        ids_after = await _org_row_ids(real_async_db_session, async_test_household.id)
        new_ids = ids_after - ids_before
        assert len(new_ids) == 1
        row = await real_async_db_session.get(AIUsageLog, new_ids.pop())
        assert row is not None
        assert row.provider == 'ollama'

    async def test_userless_calls_count_toward_the_monthly_limit(
        self, real_async_db_session: AsyncSession, async_test_household
    ) -> None:
        """The limit reads the same table — what it cannot see, it cannot cap."""
        async_test_household.settings = {'limits': {'ai_requests_monthly': 1}}
        await real_async_db_session.commit()

        await core_api.ai_usage.log_llm_usage_async(
            db=real_async_db_session,
            user_id=None,
            organization_id=async_test_household.id,
            response=_answer(),
            action_type='connection_test',
        )

        with pytest.raises(ValueError, match='limit'):
            await check_ai_limit_async(
                real_async_db_session, async_test_household.id, 'connection_test'
            )
