"""Every demo organization has a monthly AI ceiling, set by the rebuild.

The demo serves AI from one key in the server's environment, and every visitor
works in an organization of their own, so nothing a visitor does in Settings
can bound what that key spends. ``ai_requests_monthly`` defaults to no limit,
and a limit set by hand would not survive the night: the rebuild drops the
schema. So the rebuild writes the ceiling into the instance-wide default
limits, which a visitor cannot reach, and every organization it seeds — the
operator's and each sandbox — answers to it.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli.commands_demo import cap_demo_ai_requests_async
from app.models.ai_usage_log import AIUsageLog
from app.services.ai_usage_service import (
    AIUsageLimitExceededError,
    check_ai_limit_async,
)
from app.services.system_settings_service import get_default_org_limits_async

pytestmark = pytest.mark.integration


async def _spend(db: AsyncSession, org_id, calls: int) -> None:
    for _ in range(calls):
        db.add(
            AIUsageLog(
                organization_id=org_id,
                model_name='deepseek-flash',
                provider='deepseek',
                action_type='recipe_parse',
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            )
        )
    await db.flush()


@pytest.mark.asyncio
class TestTheRebuildSetsTheCeiling:
    async def test_the_call_that_crosses_it_is_refused_by_the_app(
        self, real_async_db_session: AsyncSession, async_test_household
    ) -> None:
        db = real_async_db_session
        await cap_demo_ai_requests_async(db, 3)

        await _spend(db, async_test_household.id, 2)
        await check_ai_limit_async(db, async_test_household.id, 'recipe_parse')

        await _spend(db, async_test_household.id, 1)
        with pytest.raises(AIUsageLimitExceededError) as refused:
            await check_ai_limit_async(db, async_test_household.id, 'recipe_parse')
        assert refused.value.limit_key == 'ai_requests_monthly'
        assert (refused.value.used, refused.value.limit) == (3, 3)

    async def test_the_other_default_limits_are_left_as_they_were(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        before = await get_default_org_limits_async(db)

        await cap_demo_ai_requests_async(db, 3)

        after = await get_default_org_limits_async(db)
        assert after == {**before, 'ai_requests_monthly': 3}
