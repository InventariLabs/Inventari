"""
Integration tests for SystemSettingsService.

Tests core system configuration functions:
- System setting CRUD operations (get, set, list)
- Reads see writes made outside the service (another worker)
- Model pricing management
- Organization limits management
- Cost estimation for LLM usage
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.system_settings_service import (
    estimate_cost_async,
    get_all_settings_async,
    get_default_org_limits_async,
    get_model_pricing_async,
    get_setting_async,
    set_setting_async,
)


@pytest.mark.integration
@pytest.mark.asyncio
class TestSystemSettingsService:
    """Test suite for SystemSettingsService."""

    async def test_get_setting_not_found_returns_default(
        self, real_async_db_session: AsyncSession
    ):
        """Test get_setting returns default when key doesn't exist."""
        db = real_async_db_session
        result = await get_setting_async(db, 'nonexistent_key', default='default_value')
        assert result == 'default_value'

    async def test_get_setting_not_found_no_default(
        self, real_async_db_session: AsyncSession
    ):
        """Test get_setting returns None when key doesn't exist and no default."""
        db = real_async_db_session
        result = await get_setting_async(db, 'nonexistent_key_xyz')
        assert result is None

    async def test_set_setting_creates_new_setting(
        self, real_async_db_session: AsyncSession
    ):
        """Test set_setting creates a new setting."""
        db = real_async_db_session
        value = {'test_key': 'test_value'}

        await set_setting_async(db, 'new_setting_test', value)

        result = await get_setting_async(db, 'new_setting_test')
        assert result == value

    async def test_set_setting_updates_existing_setting(
        self, real_async_db_session: AsyncSession
    ):
        """Test set_setting updates existing setting."""
        db = real_async_db_session

        await set_setting_async(db, 'setting_to_update_test', {'old': 'value'})
        await set_setting_async(db, 'setting_to_update_test', {'new': 'value'})

        result = await get_setting_async(db, 'setting_to_update_test')
        assert result == {'new': 'value'}

    async def test_get_setting_sees_write_made_by_another_worker(
        self, real_async_db_session: AsyncSession
    ):
        """A write that bypasses this process (another worker) is read at once."""
        db = real_async_db_session
        await set_setting_async(db, 'cross_worker_test', {'limit': 1})
        assert await get_setting_async(db, 'cross_worker_test') == {'limit': 1}

        await db.execute(
            text('UPDATE system_settings SET value = CAST(:v AS jsonb) WHERE key = :k'),
            {'v': '{"limit": 2}', 'k': 'cross_worker_test'},
        )

        assert await get_setting_async(db, 'cross_worker_test') == {'limit': 2}

    async def test_get_all_settings_returns_list(
        self, real_async_db_session: AsyncSession
    ):
        """Test get_all_settings returns a list."""
        db = real_async_db_session
        result = await get_all_settings_async(db)
        assert isinstance(result, list)

    async def test_get_all_settings_includes_set_values(
        self, real_async_db_session: AsyncSession
    ):
        """Test get_all_settings includes values we set."""
        db = real_async_db_session

        await set_setting_async(db, 'list_test_1', 'value1')
        await set_setting_async(db, 'list_test_2', 'value2')

        result = await get_all_settings_async(db)
        keys = [s['key'] for s in result]
        assert 'list_test_1' in keys or 'list_test_2' in keys

    async def test_get_model_pricing_returns_dict(
        self, real_async_db_session: AsyncSession
    ):
        """Test get_model_pricing returns a dictionary."""
        db = real_async_db_session
        result = await get_model_pricing_async(db)
        assert isinstance(result, dict)
        assert len(result) > 0

    async def test_get_model_pricing_all_models_have_required_fields(
        self, real_async_db_session: AsyncSession
    ):
        """Test all models in pricing have required fields."""
        db = real_async_db_session
        pricing = await get_model_pricing_async(db)

        for _, prices in pricing.items():
            assert 'input_per_1k' in prices
            assert 'output_per_1k' in prices
            assert isinstance(prices['input_per_1k'], (int, float))
            assert isinstance(prices['output_per_1k'], (int, float))

    async def test_get_default_org_limits_returns_dict(
        self, real_async_db_session: AsyncSession
    ):
        """Test get_default_org_limits returns a dictionary."""
        db = real_async_db_session
        result = await get_default_org_limits_async(db)
        assert isinstance(result, dict)

    async def test_estimate_cost_free_model(self, real_async_db_session: AsyncSession):
        """Test estimate_cost with free model."""
        db = real_async_db_session
        model = 'google/gemini-2.0-flash-exp:free'
        prompt_tokens = 1000
        completion_tokens = 500

        cost, is_estimated = await estimate_cost_async(
            db, model, prompt_tokens, completion_tokens
        )

        assert cost == 0.0
        assert is_estimated is True

    async def test_estimate_cost_paid_model(self, real_async_db_session: AsyncSession):
        """Test estimate_cost with paid model."""
        db = real_async_db_session
        model = 'openai/gpt-4o'
        prompt_tokens = 1000
        completion_tokens = 500

        cost, is_estimated = await estimate_cost_async(
            db, model, prompt_tokens, completion_tokens
        )

        # gpt-4o: input = 0.0025/1k tokens, output = 0.01/1k tokens
        # Expected: (1000 * 0.0025 / 1000) + (500 * 0.01 / 1000)
        # = 0.0025 + 0.005 = 0.0075
        assert cost == 0.0075
        assert is_estimated is True

    async def test_estimate_cost_unknown_model_returns_zero(
        self, real_async_db_session: AsyncSession
    ):
        """Test estimate_cost returns 0 for unknown model."""
        db = real_async_db_session
        cost, is_estimated = await estimate_cost_async(db, 'unknown/model', 1000, 500)
        assert cost == 0.0
        assert is_estimated is True

    async def test_estimate_cost_zero_tokens(self, real_async_db_session: AsyncSession):
        """Test estimate_cost with zero tokens."""
        db = real_async_db_session
        cost, is_estimated = await estimate_cost_async(
            db, 'openai/gpt-4o', prompt_tokens=0, completion_tokens=0
        )
        assert cost == 0.0
        assert is_estimated is True

    async def test_estimate_cost_multiple_models(
        self, real_async_db_session: AsyncSession
    ):
        """Test estimate_cost consistency across different models."""
        db = real_async_db_session
        prompt_tokens = 1000
        completion_tokens = 1000
        models = [
            'google/gemini-2.0-flash-001',
            'google/gemini-1.5-pro',
            'openai/gpt-4o',
            'openai/gpt-4o-mini',
        ]

        costs = {}
        for model in models:
            cost, is_estimated = await estimate_cost_async(
                db, model, prompt_tokens, completion_tokens
            )
            costs[model] = cost
            assert cost >= 0.0
            assert is_estimated is True

        # Different models should have different costs
        # gpt-4o should be more expensive than gpt-4o-mini
        assert costs['openai/gpt-4o'] > costs['openai/gpt-4o-mini']

    async def test_setting_with_json_value(self, real_async_db_session: AsyncSession):
        """Test setting stores and retrieves JSON values correctly."""
        db = real_async_db_session
        json_value = {
            'nested': {'key': 'value'},
            'list': [1, 2, 3],
            'number': 42,
        }

        await set_setting_async(db, 'json_setting_test', json_value)

        result = await get_setting_async(db, 'json_setting_test')
        assert result == json_value

    async def test_setting_with_string_value(self, real_async_db_session: AsyncSession):
        """Test setting stores and retrieves string values."""
        db = real_async_db_session
        string_value = 'test string value'

        await set_setting_async(db, 'string_setting_test', string_value)

        result = await get_setting_async(db, 'string_setting_test')
        assert result == string_value

    async def test_setting_with_number_value(self, real_async_db_session: AsyncSession):
        """Test setting stores and retrieves numeric values."""
        db = real_async_db_session
        number_value = 42

        await set_setting_async(db, 'number_setting_test', number_value)

        result = await get_setting_async(db, 'number_setting_test')
        assert result == number_value

    async def test_setting_with_boolean_value(
        self, real_async_db_session: AsyncSession
    ):
        """Test setting stores and retrieves boolean values."""
        db = real_async_db_session

        await set_setting_async(db, 'bool_setting_test', True)

        result = await get_setting_async(db, 'bool_setting_test')
        assert result is True

    async def test_setting_with_null_value(self, real_async_db_session: AsyncSession):
        """Test setting stores None value."""
        db = real_async_db_session

        await set_setting_async(db, 'null_setting_test', None)

        result = await get_setting_async(db, 'null_setting_test')
        assert result is None

    async def test_estimate_cost_large_token_count(
        self, real_async_db_session: AsyncSession
    ):
        """Test estimate_cost with large token counts."""
        db = real_async_db_session
        model = 'google/gemini-2.0-flash-001'
        prompt_tokens = 1000000  # 1M tokens
        completion_tokens = 500000  # 500K tokens

        cost, is_estimated = await estimate_cost_async(
            db, model, prompt_tokens, completion_tokens
        )

        # Should scale proportionally
        cost_small, _ = await estimate_cost_async(db, model, 1000, 500)
        # Allow for floating point precision
        assert abs(cost - (cost_small * 1000.0)) < 0.0001
        assert is_estimated is True

    async def test_get_setting_with_special_characters_in_key(
        self, real_async_db_session: AsyncSession
    ):
        """Test setting with special characters in key."""
        db = real_async_db_session
        key = 'setting:with:colons:and-dashes'
        value = 'test_value'

        await set_setting_async(db, key, value)

        result = await get_setting_async(db, key)
        assert result == value

    async def test_pricing_coverage_includes_gemini_models(
        self, real_async_db_session: AsyncSession
    ):
        """Test that pricing includes Gemini models."""
        db = real_async_db_session
        pricing = await get_model_pricing_async(db)
        assert any('gemini' in model for model in pricing.keys())

    async def test_pricing_coverage_includes_openai_models(
        self, real_async_db_session: AsyncSession
    ):
        """Test that pricing includes OpenAI models."""
        db = real_async_db_session
        pricing = await get_model_pricing_async(db)
        assert any('gpt' in model for model in pricing.keys())

    async def test_default_limits_structure(self, real_async_db_session: AsyncSession):
        """Test default org limits have expected fields."""
        db = real_async_db_session
        limits = await get_default_org_limits_async(db)

        expected_fields = [
            'ai_scans_monthly',
            'ai_requests_monthly',
            'max_products',
            'max_members',
        ]
        for field in expected_fields:
            assert field in limits

    async def test_estimate_cost_with_cache_read_tokens(
        self, real_async_db_session: AsyncSession
    ):
        """Test estimate_cost applies cache hit pricing when cache_read_tokens > 0."""
        db = real_async_db_session
        model = 'xiaomi/mimo-v2.5'
        prompt_tokens = 1000
        completion_tokens = 500

        cost_no_cache, _ = await estimate_cost_async(
            db, model, prompt_tokens, completion_tokens
        )

        cost_all_cached, _ = await estimate_cost_async(
            db,
            model,
            prompt_tokens,
            completion_tokens,
            cache_read_tokens=prompt_tokens,
        )

        # cache hit price (0.0028/1k) < cache miss price (0.14/1k)
        # so all-cached cost should be lower
        assert cost_all_cached < cost_no_cache

    async def test_estimate_cost_cache_read_tokens_partial(
        self, real_async_db_session: AsyncSession
    ):
        """Test estimate_cost with partial cache hit."""
        db = real_async_db_session
        model = 'xiaomi/mimo-v2.5'
        prompt_tokens = 1000
        completion_tokens = 500
        cache_read = 300

        cost_full, _ = await estimate_cost_async(
            db, model, prompt_tokens, completion_tokens
        )
        cost_partial, _ = await estimate_cost_async(
            db, model, prompt_tokens, completion_tokens, cache_read_tokens=cache_read
        )

        # partial cache should be between full cache and no cache
        assert cost_partial < cost_full
        assert cost_partial > 0.0

    async def test_estimate_cost_cache_read_tokens_ignored_for_models_without_it(
        self, real_async_db_session: AsyncSession
    ):
        """Test cache_read_tokens is ignored when model has no cache pricing."""
        db = real_async_db_session
        model = 'openai/gpt-4o'
        prompt_tokens = 1000
        completion_tokens = 500

        cost_no_cache, _ = await estimate_cost_async(
            db, model, prompt_tokens, completion_tokens
        )
        cost_with_cache, _ = await estimate_cost_async(
            db, model, prompt_tokens, completion_tokens, cache_read_tokens=500
        )

        # gpt-4o has no input_per_1k_cache_hit, so cache_read_tokens should be ignored
        assert cost_no_cache == cost_with_cache
