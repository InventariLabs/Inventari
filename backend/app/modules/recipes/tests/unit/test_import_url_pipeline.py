"""Unit tests for ``recipes._import_url_pipeline``.

The scraping, LLM parsing, translation and template-matching stages are all
mocked, so these tests exercise the pipeline's own branching (URL validation,
AI-limit checks, translation decisions, UoM resolution and the two output
shapes) without a DB session or any network access.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.public_api import core_api
from app.modules.recipes._import_url_pipeline import (
    _check_ai_limit,
    _find_uom,
    _parse_import_url,
    _preview_import_url,
)
from app.modules.recipes.ingredient_parser_basic import ParsedIngredient
from app.modules.recipes.ingredient_parser_llm import IngredientParseOutcome
from app.modules.recipes.scrapers.base import ScrapedRecipe


def _parsed(**overrides: Any) -> ParsedIngredient:
    defaults: dict[str, Any] = {
        'name': 'flour',
        'group_name': 'flour',
        'quantity': Decimal('500'),
        'unit_symbol': 'g',
        'original_text': '500 g flour',
        'original_quantity': None,
        'original_unit_text': None,
        'unit_display': None,
    }
    defaults.update(overrides)
    return ParsedIngredient(**defaults)


def _scraped(**overrides: Any) -> ScrapedRecipe:
    defaults: dict[str, Any] = {
        'title': 'Imported Recipe',
        'ingredients': ['500 g flour'],
        'instructions': 'Mix.',
        'servings': 2,
        'image_url': 'https://img.example/1.jpg',
        'prep_time_minutes': 15,
        'translated': True,
        'source_language': None,
    }
    defaults.update(overrides)
    return ScrapedRecipe(**defaults)


@pytest.mark.unit
class TestFindUom:
    async def test_none_symbol_returns_none(self) -> None:
        assert await _find_uom(MagicMock(), uuid.uuid4(), None) is None

    async def test_symbol_lookup(self) -> None:
        mock_core = MagicMock()
        uom = MagicMock()
        mock_core.uoms.get_by_symbol_async = AsyncMock(return_value=uom)
        org_id = uuid.uuid4()
        with patch('app.modules.recipes._import_url_pipeline.core_api', mock_core):
            result = await _find_uom(MagicMock(), org_id, 'g')
        assert result is uom
        mock_core.uoms.get_by_symbol_async.assert_awaited_once()


@pytest.mark.unit
class TestCheckAiLimit:
    """The recipes gate is the core counter's, not a second local count."""

    async def test_the_check_delegates_to_the_core_gate(self) -> None:
        mock_core = MagicMock()
        mock_core.ai_usage.enforce_limit_async = AsyncMock()
        db = MagicMock()
        org_id = uuid.uuid4()
        with patch('app.modules.recipes._import_url_pipeline.core_api', mock_core):
            await _check_ai_limit(db, org_id)
        mock_core.ai_usage.enforce_limit_async.assert_awaited_once_with(
            db, org_id, 'recipe_import'
        )

    async def test_the_refusal_propagates(self) -> None:
        refusal = HTTPException(
            status_code=429, detail={'code': 'AI_USAGE_LIMIT_EXCEEDED'}
        )
        mock_core = MagicMock()
        mock_core.ai_usage.enforce_limit_async = AsyncMock(side_effect=refusal)
        with patch('app.modules.recipes._import_url_pipeline.core_api', mock_core):
            with pytest.raises(HTTPException) as exc_info:
                await _check_ai_limit(MagicMock(), uuid.uuid4())
        assert exc_info.value.status_code == 429


@pytest.mark.unit
class TestTheRefusalReachesTheCaller:
    """An over-limit import must refuse, not fall through to the scraper.

    The gate this pins used to be wrapped in ``except Exception`` — and an
    ``HTTPException`` is an ``Exception``, so the 429 raised by the counter
    was logged as "non-blocking" and the import continued. Restore that
    wrapper and this test fails on the 429 that never comes.
    """

    async def test_a_refused_import_never_reaches_the_scraper(self) -> None:
        refusal = HTTPException(
            status_code=429, detail={'code': 'AI_USAGE_LIMIT_EXCEEDED'}
        )
        with (
            patch(
                'app.modules.recipes._import_url_pipeline._check_ai_limit',
                new_callable=AsyncMock,
                side_effect=refusal,
            ),
            patch(
                'app.modules.recipes._import_url_pipeline._scrape_recipe',
                new_callable=AsyncMock,
            ) as scraper,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await _parse_import_url(
                    'https://example.com/recipe',
                    MagicMock(),
                    uuid.uuid4(),
                    uuid.uuid4(),
                )

        assert exc_info.value.status_code == 429
        scraper.assert_not_awaited()

    async def test_a_counter_outage_does_not_block_the_import(self) -> None:
        """The best-effort half belongs to the core gate, not to this module.

        Pinned here because it is the half a future "make the gate strict"
        change would break: a counter that cannot be read refuses nothing.
        """
        with patch.object(
            core_api.ai_usage,
            'check_limit_async',
            new=AsyncMock(side_effect=RuntimeError('counter is down')),
        ):
            await _check_ai_limit(AsyncMock(), uuid.uuid4())


@pytest.mark.unit
class TestParseImportUrl:
    async def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError, match='Invalid URL'):
            await _parse_import_url('ftp://x', MagicMock(), uuid.uuid4(), uuid.uuid4())

    async def test_scrape_failure_raises(self) -> None:
        with (
            patch(
                'app.modules.recipes._import_url_pipeline._check_ai_limit',
                new_callable=AsyncMock,
            ),
            patch(
                'app.core.module_settings.resolve_jina_api_key_async',
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.scrape_with_jina_llm_async',
                new_callable=AsyncMock,
                side_effect=RuntimeError('boom'),
            ),
        ):
            with pytest.raises(ValueError, match='Failed to scrape'):
                await _parse_import_url(
                    'https://example.com/r', MagicMock(), uuid.uuid4(), uuid.uuid4()
                )

    async def test_purpose_unbound_passes_through_unwrapped(self) -> None:
        """An unbound AI purpose is a configuration gap the reader is told to
        fix in Settings — burying it under 'Failed to scrape recipe from URL'
        glues a second prefix onto an answer that already has one."""
        from app.core.llm.errors import LlmPurposeUnboundError

        with (
            patch(
                'app.modules.recipes._import_url_pipeline._check_ai_limit',
                new_callable=AsyncMock,
            ),
            patch(
                'app.core.module_settings.resolve_jina_api_key_async',
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.scrape_with_jina_llm_async',
                new_callable=AsyncMock,
                side_effect=LlmPurposeUnboundError('recipes.text_parse'),
            ),
        ):
            with pytest.raises(LlmPurposeUnboundError):
                await _parse_import_url(
                    'https://example.com/r', MagicMock(), uuid.uuid4(), uuid.uuid4()
                )

    async def test_provider_refusal_passes_through_unwrapped(self) -> None:
        """A provider that refused the key or the budget is a configuration
        answer the reader can act on — 'Failed to scrape recipe from URL'
        would hide it under a scraping prefix and leak the provider body."""
        from app.core.llm.errors import LlmProviderRefusalError

        with (
            patch(
                'app.modules.recipes._import_url_pipeline._check_ai_limit',
                new_callable=AsyncMock,
            ),
            patch(
                'app.core.module_settings.resolve_jina_api_key_async',
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.scrape_with_jina_llm_async',
                new_callable=AsyncMock,
                side_effect=LlmProviderRefusalError(
                    'OpenAI-compatible provider returned 401',
                    status_code=401,
                    connection_name='Recipe Reader',
                    model_name='gpt-4o-mini',
                ),
            ),
        ):
            with pytest.raises(LlmProviderRefusalError):
                await _parse_import_url(
                    'https://example.com/r', MagicMock(), uuid.uuid4(), uuid.uuid4()
                )

    async def test_the_quota_refusal_passes_through_unwrapped(self) -> None:
        """A 429 raised by the per-call gate inside the scraper must stay a
        429. The pre-check can pass and the counter can refuse the next call
        under concurrent traffic; 'Failed to scrape recipe from URL' would
        demote that refusal to a 400 and lose the numbers it carries."""
        refusal = HTTPException(
            status_code=429, detail={'code': 'AI_USAGE_LIMIT_EXCEEDED'}
        )

        with (
            patch(
                'app.modules.recipes._import_url_pipeline._check_ai_limit',
                new_callable=AsyncMock,
            ),
            patch(
                'app.core.module_settings.resolve_jina_api_key_async',
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.scrape_with_jina_llm_async',
                new_callable=AsyncMock,
                side_effect=refusal,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await _parse_import_url(
                    'https://example.com/r', MagicMock(), uuid.uuid4(), uuid.uuid4()
                )

        assert exc_info.value.status_code == 429

    async def test_happy_path(self) -> None:
        parsed = _parsed()
        scraped = _scraped()
        uom = MagicMock()
        uom.id = uuid.uuid4()
        match = MagicMock()
        match.ingredient_index = 0
        match.template_id = uuid.uuid4()

        with (
            patch(
                'app.modules.recipes._import_url_pipeline._check_ai_limit',
                new_callable=AsyncMock,
            ),
            patch(
                'app.core.module_settings.resolve_jina_api_key_async',
                new_callable=AsyncMock,
                return_value='jina-key',
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.scrape_with_jina_llm_async',
                new_callable=AsyncMock,
                return_value=scraped,
            ),
            patch(
                'app.modules.recipes.ingredient_parser_llm.parse_ingredients_llm_async',
                new_callable=AsyncMock,
                return_value=[parsed],
            ),
            patch(
                'app.modules.recipes.template_matcher.match_templates',
                new_callable=AsyncMock,
                return_value=[match],
            ),
            patch(
                'app.modules.recipes.unit_conversion_service.list_conversions',
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                'app.modules.recipes.unit_conversion_service.render_conversion_table',
                return_value='TABLE',
            ),
            patch(
                'app.modules.recipes._import_url_pipeline._find_uom',
                new_callable=AsyncMock,
                return_value=uom,
            ),
        ):
            result = await _parse_import_url(
                'https://example.com/r', MagicMock(), uuid.uuid4(), uuid.uuid4()
            )

        assert result.name == 'Imported Recipe'
        assert result.instructions == 'Mix.'
        assert result.servings == 2
        assert result.source_url == 'https://example.com/r'
        assert len(result.ingredients) == 1
        assert result.ingredients[0].name == 'flour'
        assert result.ingredients[0].uom_id == uom.id
        assert result.ingredients[0].template_id == match.template_id

    async def test_no_uom_or_template(self) -> None:
        parsed = _parsed(unit_symbol=None, group_name=None)
        scraped = _scraped()
        match = MagicMock()
        match.ingredient_index = 0
        match.template_id = None

        with (
            patch(
                'app.modules.recipes._import_url_pipeline._check_ai_limit',
                new_callable=AsyncMock,
            ),
            patch(
                'app.core.module_settings.resolve_jina_api_key_async',
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.scrape_with_jina_llm_async',
                new_callable=AsyncMock,
                return_value=scraped,
            ),
            patch(
                'app.modules.recipes.ingredient_parser_llm.parse_ingredients_llm_async',
                new_callable=AsyncMock,
                return_value=[parsed],
            ),
            patch(
                'app.modules.recipes.template_matcher.match_templates',
                new_callable=AsyncMock,
                return_value=[match],
            ),
            patch(
                'app.modules.recipes.unit_conversion_service.list_conversions',
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                'app.modules.recipes.unit_conversion_service.render_conversion_table',
                return_value='TABLE',
            ),
            patch(
                'app.modules.recipes._import_url_pipeline._find_uom',
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await _parse_import_url(
                'https://example.com/r', MagicMock(), uuid.uuid4(), uuid.uuid4()
            )

        assert result.ingredients[0].uom_id is None
        assert result.ingredients[0].template_id is None

    async def test_empty_parsed_list(self) -> None:
        scraped = _scraped()
        with (
            patch(
                'app.modules.recipes._import_url_pipeline._check_ai_limit',
                new_callable=AsyncMock,
            ),
            patch(
                'app.core.module_settings.resolve_jina_api_key_async',
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.scrape_with_jina_llm_async',
                new_callable=AsyncMock,
                return_value=scraped,
            ),
            patch(
                'app.modules.recipes.ingredient_parser_llm.parse_ingredients_llm_async',
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                'app.modules.recipes.unit_conversion_service.list_conversions',
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                'app.modules.recipes.unit_conversion_service.render_conversion_table',
                return_value='TABLE',
            ),
        ):
            result = await _parse_import_url(
                'https://example.com/r', MagicMock(), uuid.uuid4(), uuid.uuid4()
            )

        assert result.ingredients == []

    async def test_translation_needed(self) -> None:
        parsed = _parsed()
        scraped = _scraped(
            translated=False, source_language='fr', instructions='Mélanger'
        )
        match = MagicMock()
        match.ingredient_index = 0
        match.template_id = None

        with (
            patch(
                'app.modules.recipes._import_url_pipeline._check_ai_limit',
                new_callable=AsyncMock,
            ),
            patch(
                'app.core.module_settings.resolve_jina_api_key_async',
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.scrape_with_jina_llm_async',
                new_callable=AsyncMock,
                return_value=scraped,
            ),
            patch(
                'app.i18n.service.get_current_lang',
                return_value='en',
            ),
            patch(
                'app.modules.recipes.ingredient_parser_translation.translate_recipe_metadata_async',
                new_callable=AsyncMock,
                return_value=('Translated Title', 'Mix well'),
            ) as mock_translate,
            patch(
                'app.modules.recipes.ingredient_parser_llm.parse_ingredients_llm_async',
                new_callable=AsyncMock,
                return_value=[parsed],
            ),
            patch(
                'app.modules.recipes.template_matcher.match_templates',
                new_callable=AsyncMock,
                return_value=[match],
            ),
            patch(
                'app.modules.recipes.unit_conversion_service.list_conversions',
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                'app.modules.recipes.unit_conversion_service.render_conversion_table',
                return_value='TABLE',
            ),
            patch(
                'app.modules.recipes._import_url_pipeline._find_uom',
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await _parse_import_url(
                'https://example.com/r', MagicMock(), uuid.uuid4(), uuid.uuid4()
            )

        assert result.name == 'Translated Title'
        assert result.instructions == 'Mix well'
        mock_translate.assert_awaited_once()

    async def test_translation_skipped_when_same_lang(self) -> None:
        parsed = _parsed()
        scraped = _scraped(translated=False, source_language='en')
        match = MagicMock()
        match.ingredient_index = 0
        match.template_id = None

        with (
            patch(
                'app.modules.recipes._import_url_pipeline._check_ai_limit',
                new_callable=AsyncMock,
            ),
            patch(
                'app.core.module_settings.resolve_jina_api_key_async',
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.scrape_with_jina_llm_async',
                new_callable=AsyncMock,
                return_value=scraped,
            ),
            patch(
                'app.i18n.service.get_current_lang',
                return_value='en',
            ),
            patch(
                'app.modules.recipes.ingredient_parser_translation.translate_recipe_metadata_async',
                new_callable=AsyncMock,
            ) as mock_translate,
            patch(
                'app.modules.recipes.ingredient_parser_llm.parse_ingredients_llm_async',
                new_callable=AsyncMock,
                return_value=[parsed],
            ),
            patch(
                'app.modules.recipes.template_matcher.match_templates',
                new_callable=AsyncMock,
                return_value=[match],
            ),
            patch(
                'app.modules.recipes.unit_conversion_service.list_conversions',
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                'app.modules.recipes.unit_conversion_service.render_conversion_table',
                return_value='TABLE',
            ),
            patch(
                'app.modules.recipes._import_url_pipeline._find_uom',
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await _parse_import_url(
                'https://example.com/r', MagicMock(), uuid.uuid4(), uuid.uuid4()
            )

        assert result.name == 'Imported Recipe'
        mock_translate.assert_not_awaited()


@pytest.mark.unit
class TestPreviewImportUrl:
    async def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError, match='Invalid URL'):
            await _preview_import_url(
                'ftp://x', MagicMock(), uuid.uuid4(), uuid.uuid4()
            )

    async def test_scrape_failure_raises(self) -> None:
        with (
            patch(
                'app.modules.recipes._import_url_pipeline._check_ai_limit',
                new_callable=AsyncMock,
            ),
            patch(
                'app.core.module_settings.resolve_jina_api_key_async',
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.scrape_with_jina_llm_async',
                new_callable=AsyncMock,
                side_effect=RuntimeError('boom'),
            ),
        ):
            with pytest.raises(ValueError, match='Failed to scrape'):
                await _preview_import_url(
                    'https://example.com/r', MagicMock(), uuid.uuid4(), uuid.uuid4()
                )

    async def test_purpose_unbound_passes_through_unwrapped(self) -> None:
        """Same contract as the persist path: the configuration gap travels to
        the router under its own name, not under a scrape-failure prefix."""
        from app.core.llm.errors import LlmPurposeUnboundError

        with (
            patch(
                'app.modules.recipes._import_url_pipeline._check_ai_limit',
                new_callable=AsyncMock,
            ),
            patch(
                'app.core.module_settings.resolve_jina_api_key_async',
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.scrape_with_jina_llm_async',
                new_callable=AsyncMock,
                side_effect=LlmPurposeUnboundError('recipes.text_parse'),
            ),
        ):
            with pytest.raises(LlmPurposeUnboundError):
                await _preview_import_url(
                    'https://example.com/r', MagicMock(), uuid.uuid4(), uuid.uuid4()
                )

    async def test_happy_path(self) -> None:
        parsed = _parsed()
        scraped = _scraped()
        outcome = IngredientParseOutcome(items=[parsed])
        uom = MagicMock()
        uom.id = uuid.uuid4()
        match = MagicMock()
        match.ingredient_index = 0
        match.template_id = uuid.uuid4()
        template = MagicMock()
        template.id = match.template_id
        template.name = 'Flour'

        mock_core = MagicMock()
        mock_core.product_templates.list_for_org_with_recipe_usage_async = AsyncMock(
            return_value=[template]
        )

        with (
            patch(
                'app.modules.recipes._import_url_pipeline._check_ai_limit',
                new_callable=AsyncMock,
            ),
            patch(
                'app.core.module_settings.resolve_jina_api_key_async',
                new_callable=AsyncMock,
                return_value='jina-key',
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.scrape_with_jina_llm_async',
                new_callable=AsyncMock,
                return_value=scraped,
            ),
            patch(
                'app.modules.recipes.ingredient_parser_llm.parse_ingredients_llm_with_status_async',
                new_callable=AsyncMock,
                return_value=outcome,
            ),
            patch(
                'app.modules.recipes.template_matcher.match_templates',
                new_callable=AsyncMock,
                return_value=[match],
            ),
            patch(
                'app.modules.recipes.unit_conversion_service.list_conversions',
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                'app.modules.recipes.unit_conversion_service.render_conversion_table',
                return_value='TABLE',
            ),
            patch(
                'app.modules.recipes._import_url_pipeline._find_uom',
                new_callable=AsyncMock,
                return_value=uom,
            ),
            patch('app.core.public_api.core_api', mock_core),
        ):
            result = await _preview_import_url(
                'https://example.com/r', MagicMock(), uuid.uuid4(), uuid.uuid4()
            )

        assert result['name'] == 'Imported Recipe'
        assert result['parse_warning'] is None
        assert result['ingredients'][0]['name'] == 'flour'
        assert result['ingredients'][0]['uom_id'] == str(uom.id)
        assert result['ingredients'][0]['template_id'] == str(match.template_id)
        assert result['ingredients'][0]['template_name'] == 'Flour'

    async def test_fallback_warning(self) -> None:
        parsed = _parsed()
        scraped = _scraped()
        outcome = IngredientParseOutcome(
            items=[parsed], used_fallback=True, fallback_reason='empty_result'
        )
        match = MagicMock()
        match.ingredient_index = 0
        match.template_id = None
        mock_core = MagicMock()
        mock_core.product_templates.list_for_org_with_recipe_usage_async = AsyncMock(
            return_value=[]
        )

        with (
            patch(
                'app.modules.recipes._import_url_pipeline._check_ai_limit',
                new_callable=AsyncMock,
            ),
            patch(
                'app.core.module_settings.resolve_jina_api_key_async',
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.scrape_with_jina_llm_async',
                new_callable=AsyncMock,
                return_value=scraped,
            ),
            patch(
                'app.modules.recipes.ingredient_parser_llm.parse_ingredients_llm_with_status_async',
                new_callable=AsyncMock,
                return_value=outcome,
            ),
            patch(
                'app.modules.recipes.template_matcher.match_templates',
                new_callable=AsyncMock,
                return_value=[match],
            ),
            patch(
                'app.modules.recipes.unit_conversion_service.list_conversions',
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                'app.modules.recipes.unit_conversion_service.render_conversion_table',
                return_value='TABLE',
            ),
            patch(
                'app.modules.recipes._import_url_pipeline._find_uom',
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch('app.core.public_api.core_api', mock_core),
        ):
            result = await _preview_import_url(
                'https://example.com/r', MagicMock(), uuid.uuid4(), uuid.uuid4()
            )

        assert result['parse_warning'] == 'llm_fallback'

    async def test_empty_parsed_list(self) -> None:
        scraped = _scraped()
        outcome = IngredientParseOutcome(items=[])
        with (
            patch(
                'app.modules.recipes._import_url_pipeline._check_ai_limit',
                new_callable=AsyncMock,
            ),
            patch(
                'app.core.module_settings.resolve_jina_api_key_async',
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.scrape_with_jina_llm_async',
                new_callable=AsyncMock,
                return_value=scraped,
            ),
            patch(
                'app.modules.recipes.ingredient_parser_llm.parse_ingredients_llm_with_status_async',
                new_callable=AsyncMock,
                return_value=outcome,
            ),
            patch(
                'app.modules.recipes.unit_conversion_service.list_conversions',
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                'app.modules.recipes.unit_conversion_service.render_conversion_table',
                return_value='TABLE',
            ),
        ):
            result = await _preview_import_url(
                'https://example.com/r', MagicMock(), uuid.uuid4(), uuid.uuid4()
            )

        assert result['ingredients'] == []

    async def test_translation_needed(self) -> None:
        parsed = _parsed()
        scraped = _scraped(translated=False, source_language='fr')
        outcome = IngredientParseOutcome(items=[parsed])
        match = MagicMock()
        match.ingredient_index = 0
        match.template_id = None
        mock_core = MagicMock()
        mock_core.product_templates.list_for_org_with_recipe_usage_async = AsyncMock(
            return_value=[]
        )

        with (
            patch(
                'app.modules.recipes._import_url_pipeline._check_ai_limit',
                new_callable=AsyncMock,
            ),
            patch(
                'app.core.module_settings.resolve_jina_api_key_async',
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.scrape_with_jina_llm_async',
                new_callable=AsyncMock,
                return_value=scraped,
            ),
            patch(
                'app.i18n.service.get_current_lang',
                return_value='en',
            ),
            patch(
                'app.modules.recipes.ingredient_parser_translation.translate_recipe_metadata_async',
                new_callable=AsyncMock,
                return_value=('Translated Title', 'Mix well'),
            ) as mock_translate,
            patch(
                'app.modules.recipes.ingredient_parser_llm.parse_ingredients_llm_with_status_async',
                new_callable=AsyncMock,
                return_value=outcome,
            ),
            patch(
                'app.modules.recipes.template_matcher.match_templates',
                new_callable=AsyncMock,
                return_value=[match],
            ),
            patch(
                'app.modules.recipes.unit_conversion_service.list_conversions',
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                'app.modules.recipes.unit_conversion_service.render_conversion_table',
                return_value='TABLE',
            ),
            patch(
                'app.modules.recipes._import_url_pipeline._find_uom',
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch('app.core.public_api.core_api', mock_core),
        ):
            result = await _preview_import_url(
                'https://example.com/r', MagicMock(), uuid.uuid4(), uuid.uuid4()
            )

        assert result['name'] == 'Translated Title'
        assert result['instructions'] == 'Mix well'
        mock_translate.assert_awaited_once()

    async def test_translation_skipped_when_same_lang(self) -> None:
        parsed = _parsed()
        scraped = _scraped(translated=False, source_language='en')
        outcome = IngredientParseOutcome(items=[parsed])
        match = MagicMock()
        match.ingredient_index = 0
        match.template_id = None
        mock_core = MagicMock()
        mock_core.product_templates.list_for_org_with_recipe_usage_async = AsyncMock(
            return_value=[]
        )

        with (
            patch(
                'app.modules.recipes._import_url_pipeline._check_ai_limit',
                new_callable=AsyncMock,
            ),
            patch(
                'app.core.module_settings.resolve_jina_api_key_async',
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.scrape_with_jina_llm_async',
                new_callable=AsyncMock,
                return_value=scraped,
            ),
            patch(
                'app.i18n.service.get_current_lang',
                return_value='en',
            ),
            patch(
                'app.modules.recipes.ingredient_parser_translation.translate_recipe_metadata_async',
                new_callable=AsyncMock,
            ) as mock_translate,
            patch(
                'app.modules.recipes.ingredient_parser_llm.parse_ingredients_llm_with_status_async',
                new_callable=AsyncMock,
                return_value=outcome,
            ),
            patch(
                'app.modules.recipes.template_matcher.match_templates',
                new_callable=AsyncMock,
                return_value=[match],
            ),
            patch(
                'app.modules.recipes.unit_conversion_service.list_conversions',
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                'app.modules.recipes.unit_conversion_service.render_conversion_table',
                return_value='TABLE',
            ),
            patch(
                'app.modules.recipes._import_url_pipeline._find_uom',
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch('app.core.public_api.core_api', mock_core),
        ):
            result = await _preview_import_url(
                'https://example.com/r', MagicMock(), uuid.uuid4(), uuid.uuid4()
            )

        assert result['name'] == 'Imported Recipe'
        mock_translate.assert_not_awaited()
