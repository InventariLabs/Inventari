"""Integration tests: recipes module uses the AI Connections registry.

Guards against regressions where recipes falls back to legacy
``_call_llm_sync``: every LLM call goes through the registry.
"""

from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.mark.integration
class TestRecipesUsesRegistry:
    """The recipes module MUST resolve its client through ``call_llm_async``."""

    @pytest.mark.asyncio
    async def test_template_matcher_uses_call_llm_async(self) -> None:
        """``match_templates`` calls ``call_llm_async`` exactly once."""
        import json as _json
        from unittest.mock import MagicMock

        from app.modules.recipes.template_matcher import match_templates

        templates = [type('_TemplateStub', (), {'id': uuid4(), 'name': 'flour'})()]

        async def fake_fetch(
            self: Any, db: Any, org_id: Any, *, limit: int = 200
        ) -> list[Any]:
            return templates

        llm_response = _json.dumps(
            {'matches': [{'index': 0, 'template_id': str(templates[0].id)}]}
        )

        with (
            patch(
                'app.core.public_api.product_templates.CoreProductTemplatesAPI.'
                'list_for_org_with_recipe_usage_async',
                new=fake_fetch,
            ),
            patch(
                'app.modules.recipes.template_matcher.call_llm_async',
                new_callable=AsyncMock,
                return_value=llm_response,
            ) as mock_llm,
        ):
            results = await match_templates(
                MagicMock(), uuid4(), ['flour'], usage_ctx=None
            )

        mock_llm.assert_awaited_once()
        assert results[0].template_id == templates[0].id

    @pytest.mark.asyncio
    async def test_parse_ingredients_async_uses_call_llm_async(self) -> None:
        """``parse_ingredients_llm_async`` calls ``call_llm_async``."""
        from decimal import Decimal

        from app.modules.recipes.ingredient_parser_llm import (
            parse_ingredients_llm_async,
        )

        llm_response = (
            '[{"name": "Milk", "group_name": "milk", '
            '"metric_quantity": 1, "metric_unit": "l", '
            '"quantity": 1, "unit_text": "l"}]'
        )

        with patch(
            'app.modules.recipes.ingredient_parser_llm.call_llm_async',
            new_callable=AsyncMock,
            return_value=llm_response,
        ) as mock_llm:
            result = await parse_ingredients_llm_async(
                AsyncMock(),
                uuid4(),
                ['1 l milk'],
                usage_ctx=None,
                conversion_table='',
            )

        mock_llm.assert_awaited_once()
        assert len(result) == 1
        assert result[0].name == 'Milk'
        assert result[0].quantity == Decimal('1')

    @pytest.mark.asyncio
    async def test_jina_scraper_async_uses_call_llm_async(self) -> None:
        """``scrape_with_jina_llm_async`` calls ``call_llm_async``."""
        from unittest.mock import MagicMock

        from app.modules.recipes.scrapers.jina_llm import (
            scrape_with_jina_llm_async,
        )

        llm_response = (
            '{"title": "Test Recipe", "ingredients": ["1 egg"], '
            '"servings": 2, "prep_time_minutes": 15}'
        )

        mock_db = MagicMock()

        with (
            patch(
                'app.modules.recipes.scrapers.jina_llm._fetch_via_jina',
                return_value='# Test page\nsome markdown',
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.call_llm_async',
                new_callable=AsyncMock,
                return_value=llm_response,
            ) as mock_llm,
        ):
            result = await scrape_with_jina_llm_async(
                mock_db,
                uuid4(),
                'https://example.com/recipe',
                jina_api_key=None,
                usage_ctx=None,
            )

        mock_llm.assert_awaited_once()
        assert result.title == 'Test Recipe'
        assert result.ingredients == ['1 egg']

    @pytest.mark.asyncio
    async def test_no_binding_raises_typed_error(self) -> None:
        """``call_llm_async`` raises the typed ``LlmPurposeUnboundError`` when
        no AI is bound, and the scraper passes it through unwrapped — the
        configuration gap travels under its own name, not an extraction
        failure prefix, so the router can answer "set it up in Settings"."""
        from unittest.mock import MagicMock

        from app.core.llm.errors import LlmPurposeUnboundError
        from app.modules.recipes.scrapers.jina_llm import (
            scrape_with_jina_llm_async,
        )

        with (
            patch(
                'app.modules.recipes.scrapers.jina_llm._fetch_via_jina',
                return_value='# Test page',
            ),
            patch(
                'app.core.public_api.llm.CoreLlmAPI.get_client_for_purpose_async',
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                'app.core.public_api.ai_usage.CoreAIUsageAPI.check_limit_async',
                new_callable=AsyncMock,
            ),
        ):
            with pytest.raises(LlmPurposeUnboundError) as excinfo:
                await scrape_with_jina_llm_async(
                    MagicMock(),
                    uuid4(),
                    'https://example.com/recipe',
                    jina_api_key=None,
                    usage_ctx=None,
                )
        assert excinfo.value.purpose_key == 'recipes.text_parse'

    @pytest.mark.asyncio
    async def test_call_llm_async_pins_moderate_temperature_for_parsing(self) -> None:
        """Recipe parsing pins temperature=0.4 + max_tokens=8000 + no reasoning.

        Higher than vision (0.2) because recipe text is ambiguous ("szklanka"
        = 200 or 250 ml, brand names get misspelled), but still well below the
        provider default of 1.0 which would let the model "creatively" alter
        ingredient names and quantities. These params are hardcoded per-call
        so the connection form does not surface them. Reasoning is disabled
        because chain-of-thought tokens count towards the max_tokens budget
        and can starve the JSON content on reasoning models (MiniMax-M3).
        """
        from app.core.llm.base import LlmResponse
        from app.modules.recipes._llm_client import call_llm_async

        mock_client = AsyncMock()
        mock_client.complete = AsyncMock(
            return_value=LlmResponse(content='{}', usage={}, raw={})
        )

        with (
            patch(
                'app.core.public_api.llm.CoreLlmAPI.get_client_for_purpose_async',
                new_callable=AsyncMock,
                return_value=mock_client,
            ),
            patch(
                'app.core.public_api.ai_usage.CoreAIUsageAPI.log_llm_usage_async',
                new_callable=AsyncMock,
            ),
            patch(
                'app.core.public_api.ai_usage.CoreAIUsageAPI.check_limit_async',
                new_callable=AsyncMock,
            ),
        ):
            await call_llm_async(
                db=AsyncMock(),
                org_id=uuid4(),
                prompt='parse this',
                usage_ctx=None,
            )

        request = mock_client.complete.await_args.args[0]
        assert request.temperature == 0.4
        assert request.max_tokens == 8000
        assert request.disable_reasoning is True
