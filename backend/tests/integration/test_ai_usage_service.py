"""
Integration tests for ai_usage_service.

Tests cover:
- log_ai_usage: creating AIUsageLog records
- get_org_limits: returning org AI limits (org-specific or defaults)
- check_ai_limit: enforcing monthly request/scan limits
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_usage_log import AIUsageLog
from app.services.ai_usage_service import (
    AIUsageLimitExceededError,
    check_ai_limit_async,
    get_org_limits_async,
    log_ai_usage_async,
)
from app.services.system_settings_service import set_setting_async


@pytest.mark.integration
@pytest.mark.asyncio
class TestLogAiUsage:
    """Tests for log_ai_usage function."""

    async def test_creates_log_entry(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        result = await log_ai_usage_async(
            db=real_async_db_session,
            user_id=async_test_user.id,
            organization_id=async_test_household.id,
            model_name='gpt-4o',
            provider='openrouter',
            action_type='chat',
        )

        assert result is not None
        assert result.id is not None
        assert result.user_id == async_test_user.id
        assert result.organization_id == async_test_household.id
        assert result.model_name == 'gpt-4o'
        assert result.provider == 'openrouter'
        assert result.action_type == 'chat'

    async def test_persists_to_database(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        result = await log_ai_usage_async(
            db=real_async_db_session,
            user_id=async_test_user.id,
            organization_id=async_test_household.id,
            model_name='gemini-2.0-flash',
            provider='google',
            action_type='extract_label',
            prompt_tokens=150,
            completion_tokens=50,
            total_tokens=200,
            estimated_cost_usd=0.003,
            cost_is_estimated=True,
        )

        db_entry = (
            await real_async_db_session.scalars(
                select(AIUsageLog).where(AIUsageLog.id == result.id)
            )
        ).first()

        assert db_entry is not None
        assert db_entry.prompt_tokens == 150
        assert db_entry.completion_tokens == 50
        assert db_entry.total_tokens == 200
        assert db_entry.estimated_cost_usd == 0.003
        assert db_entry.cost_is_estimated is True

    async def test_default_token_values(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        result = await log_ai_usage_async(
            db=real_async_db_session,
            user_id=async_test_user.id,
            organization_id=async_test_household.id,
            model_name='test-model',
            provider='test',
            action_type='chat',
        )

        assert result.prompt_tokens == 0
        assert result.completion_tokens == 0
        assert result.total_tokens == 0
        assert result.estimated_cost_usd == 0.0
        assert result.cost_is_estimated is False

    async def test_multiple_entries_for_same_org(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        r1 = await log_ai_usage_async(
            db=real_async_db_session,
            user_id=async_test_user.id,
            organization_id=async_test_household.id,
            model_name='model-a',
            provider='p',
            action_type='chat',
        )
        r2 = await log_ai_usage_async(
            db=real_async_db_session,
            user_id=async_test_user.id,
            organization_id=async_test_household.id,
            model_name='model-b',
            provider='p',
            action_type='extract_label',
        )

        assert r1.id != r2.id

        count = (
            await real_async_db_session.scalars(
                select(AIUsageLog).where(
                    AIUsageLog.organization_id == async_test_household.id
                )
            )
        ).first()
        assert count is not None

    async def test_sets_created_at_automatically(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        before = datetime.now(UTC)

        result = await log_ai_usage_async(
            db=real_async_db_session,
            user_id=async_test_user.id,
            organization_id=async_test_household.id,
            model_name='test-model',
            provider='test',
            action_type='chat',
        )

        assert result.created_at is not None
        assert result.created_at >= before


@pytest.mark.integration
@pytest.mark.asyncio
class TestGetOrgLimits:
    """Tests for get_org_limits function."""

    async def test_returns_defaults_when_no_org_settings(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        result = await get_org_limits_async(
            real_async_db_session, async_test_household.id
        )

        assert isinstance(result, dict)
        assert 'ai_scans_monthly' in result
        assert 'ai_requests_monthly' in result

    async def test_returns_defaults_when_org_settings_empty(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        async_test_household.settings = {}
        await real_async_db_session.commit()

        result = await get_org_limits_async(
            real_async_db_session, async_test_household.id
        )

        assert isinstance(result, dict)
        assert 'ai_scans_monthly' in result

    async def test_merges_org_settings_with_defaults(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        async_test_household.settings = {'limits': {'ai_requests_monthly': 500}}
        await real_async_db_session.commit()

        result = await get_org_limits_async(
            real_async_db_session, async_test_household.id
        )

        assert result['ai_requests_monthly'] == 500
        assert 'ai_scans_monthly' in result

    async def test_org_specific_limit_overrides_default(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        async_test_household.settings = {
            'limits': {
                'ai_requests_monthly': 100,
                'ai_scans_monthly': 50,
            }
        }
        await real_async_db_session.commit()

        result = await get_org_limits_async(
            real_async_db_session, async_test_household.id
        )

        assert result['ai_requests_monthly'] == 100
        assert result['ai_scans_monthly'] == 50

    async def test_nonexistent_org_returns_defaults(
        self, real_async_db_session: AsyncSession
    ):
        fake_id = uuid.uuid4()

        result = await get_org_limits_async(real_async_db_session, fake_id)

        assert isinstance(result, dict)
        assert 'ai_scans_monthly' in result


@pytest.mark.integration
@pytest.mark.asyncio
class TestCheckAiLimit:
    """Tests for check_ai_limit function."""

    async def test_passes_when_no_limits_set(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        await check_ai_limit_async(
            real_async_db_session, async_test_household.id, 'chat'
        )

    async def test_passes_when_under_request_limit(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        await set_setting_async(
            real_async_db_session,
            'default_org_limits',
            {
                'ai_requests_monthly': 100,
                'ai_scans_monthly': None,
                'max_products': None,
                'max_members': None,
            },
        )

        await log_ai_usage_async(
            db=real_async_db_session,
            user_id=async_test_user.id,
            organization_id=async_test_household.id,
            model_name='test-model',
            provider='test',
            action_type='chat',
        )

        await check_ai_limit_async(
            real_async_db_session, async_test_household.id, 'chat'
        )

    async def test_raises_when_request_limit_exceeded(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        await set_setting_async(
            real_async_db_session,
            'default_org_limits',
            {
                'ai_requests_monthly': 2,
                'ai_scans_monthly': None,
                'max_products': None,
                'max_members': None,
            },
        )

        for _ in range(3):
            await log_ai_usage_async(
                db=real_async_db_session,
                user_id=async_test_user.id,
                organization_id=async_test_household.id,
                model_name='test-model',
                provider='test',
                action_type='chat',
            )

        with pytest.raises(ValueError, match='AI requests allowed'):
            await check_ai_limit_async(
                real_async_db_session, async_test_household.id, 'chat'
            )

    async def test_limit_exception_speaks_the_request_language(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        from app.i18n.service import get_current_lang, set_current_lang

        async_test_household.settings = {'limits': {'ai_requests_monthly': 1}}
        await real_async_db_session.flush()
        await log_ai_usage_async(
            db=real_async_db_session,
            user_id=None,
            organization_id=async_test_household.id,
            model_name='test-model',
            provider='test',
            action_type='chat',
        )
        previous = get_current_lang()
        set_current_lang('pl')
        try:
            with pytest.raises(
                AIUsageLimitExceededError,
                match='Organizacja wykorzystała 1 z 1 zapytań AI',
            ):
                await check_ai_limit_async(
                    real_async_db_session, async_test_household.id, 'chat'
                )
        finally:
            set_current_lang(previous)

    async def test_raises_when_scan_limit_exceeded(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        await set_setting_async(
            real_async_db_session,
            'default_org_limits',
            {
                'ai_requests_monthly': None,
                'ai_scans_monthly': 1,
                'max_products': None,
                'max_members': None,
            },
        )

        for _ in range(2):
            await log_ai_usage_async(
                db=real_async_db_session,
                user_id=async_test_user.id,
                organization_id=async_test_household.id,
                model_name='test-model',
                provider='test',
                action_type='extract_label',
            )

        with pytest.raises(ValueError, match='label scans allowed') as exc_info:
            await check_ai_limit_async(
                real_async_db_session, async_test_household.id, 'extract_label'
            )

        # The sentence says which ceiling; the attributes say what it counted,
        # so an API can hand the reader both without parsing the prose.
        assert exc_info.value.limit_key == 'ai_scans_monthly'
        assert exc_info.value.used == 2
        assert exc_info.value.limit == 1

    async def test_scan_limit_only_for_extract_label_action(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        await set_setting_async(
            real_async_db_session,
            'default_org_limits',
            {
                'ai_requests_monthly': None,
                'ai_scans_monthly': 1,
                'max_products': None,
                'max_members': None,
            },
        )

        for _ in range(2):
            await log_ai_usage_async(
                db=real_async_db_session,
                user_id=async_test_user.id,
                organization_id=async_test_household.id,
                model_name='test-model',
                provider='test',
                action_type='extract_label',
            )

        await check_ai_limit_async(
            real_async_db_session, async_test_household.id, 'chat'
        )

    async def test_the_refusal_carries_the_numbers_it_measured(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        """The message said "quota exceeded"; the caller needs the arithmetic."""
        async_test_household.settings = {'limits': {'ai_requests_monthly': 2}}
        await real_async_db_session.commit()

        for _ in range(3):
            await log_ai_usage_async(
                db=real_async_db_session,
                user_id=async_test_user.id,
                organization_id=async_test_household.id,
                model_name='test-model',
                provider='test',
                action_type='connection_test',
            )

        with pytest.raises(AIUsageLimitExceededError) as exc_info:
            await check_ai_limit_async(
                real_async_db_session, async_test_household.id, 'connection_test'
            )

        exc = exc_info.value
        assert exc.limit_key == 'ai_requests_monthly'
        assert exc.used == 3
        assert exc.limit == 2
        assert 'used 3 of 2 AI requests' in str(exc)

        now = datetime.now(UTC)
        assert exc.period_start.day == 1
        assert exc.period_start.month == now.month
        assert exc.period_end.month == now.month
        assert exc.period_end >= exc.period_start

    async def test_org_specific_limits_override_defaults(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        await set_setting_async(
            real_async_db_session,
            'default_org_limits',
            {
                'ai_requests_monthly': 1000,
                'ai_scans_monthly': None,
                'max_products': None,
                'max_members': None,
            },
        )

        async_test_household.settings = {'limits': {'ai_requests_monthly': 1}}
        await real_async_db_session.commit()

        for _ in range(2):
            await log_ai_usage_async(
                db=real_async_db_session,
                user_id=async_test_user.id,
                organization_id=async_test_household.id,
                model_name='test-model',
                provider='test',
                action_type='chat',
            )

        with pytest.raises(ValueError, match='AI requests allowed'):
            await check_ai_limit_async(
                real_async_db_session, async_test_household.id, 'chat'
            )
