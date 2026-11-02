"""Unit tests for scrapers/jina_llm.py — no network required."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.recipes.scrapers.jina_llm import scrape_with_jina_llm_async


@pytest.mark.asyncio
class TestScrapeWithJinaAsync:
    """Tests for the async, registry-backed jina scraper."""

    async def test_uses_llm_when_configured(self) -> None:
        llm_response = (
            '{"title": "Test Recipe", "ingredients": ["1 egg"], '
            '"servings": 2, "prep_time_minutes": 15}'
        )
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
                MagicMock(),
                uuid4(),
                'https://example.com/recipe',
                jina_api_key=None,
                usage_ctx=None,
            )
            mock_llm.assert_awaited_once()
            assert result.title == 'Test Recipe'
            assert result.ingredients == ['1 egg']
            assert result.servings == 2
            assert result.prep_time_minutes == 15

    async def test_fenced_reply_with_commentary_and_raw_newlines(self) -> None:
        """The scraped page is long, so the model likes to editorialise."""
        llm_response = (
            'I found the recipe. Here it is:\n'
            '```json\n'
            '{"title": "Test Recipe", "ingredients": ["1 egg"], '
            '"instructions": "Beat the egg.\nFry it."}\n'
            '```'
        )
        with (
            patch(
                'app.modules.recipes.scrapers.jina_llm._fetch_via_jina',
                return_value='# Test page\nsome markdown',
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.call_llm_async',
                new_callable=AsyncMock,
                return_value=llm_response,
            ),
        ):
            result = await scrape_with_jina_llm_async(
                MagicMock(),
                uuid4(),
                'https://example.com/recipe',
                jina_api_key=None,
                usage_ctx=None,
            )
            assert result.title == 'Test Recipe'
            assert result.ingredients == ['1 egg']
            assert result.instructions == 'Beat the egg.\nFry it.'

    async def test_raises_when_llm_returns_no_ingredients(self) -> None:
        llm_response = '{"title": "Empty page", "ingredients": []}'
        with (
            patch(
                'app.modules.recipes.scrapers.jina_llm._fetch_via_jina',
                return_value='# Empty',
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.call_llm_async',
                new_callable=AsyncMock,
                return_value=llm_response,
            ),
        ):
            with pytest.raises(ValueError, match='no ingredients'):
                await scrape_with_jina_llm_async(
                    MagicMock(),
                    uuid4(),
                    'https://example.com/recipe',
                    jina_api_key=None,
                    usage_ctx=None,
                )

    async def test_raises_when_llm_returns_invalid_json(self) -> None:
        with (
            patch(
                'app.modules.recipes.scrapers.jina_llm._fetch_via_jina',
                return_value='# Some page',
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.call_llm_async',
                new_callable=AsyncMock,
                return_value='not json at all',
            ),
        ):
            with pytest.raises(ValueError, match='could not be extracted'):
                await scrape_with_jina_llm_async(
                    MagicMock(),
                    uuid4(),
                    'https://example.com/recipe',
                    jina_api_key=None,
                    usage_ctx=None,
                )

    async def test_raises_when_no_binding(self) -> None:
        """The configuration gap travels under its own name — typed, with the
        purpose key as data — not wrapped in an extraction-failure prefix."""
        from app.core.llm.errors import LlmPurposeUnboundError

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
        assert not isinstance(excinfo.value, ValueError)

    async def test_a_provider_refusal_travels_under_its_own_name(self) -> None:
        """A key the provider refuses is a configuration answer, not an
        extraction failure — wrapping it would bury it under a scraping
        prefix and leak the provider body into the message."""
        from app.core.llm.errors import LlmProviderRefusalError

        with (
            patch(
                'app.modules.recipes.scrapers.jina_llm._fetch_via_jina',
                return_value='# Test page',
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.call_llm_async',
                new_callable=AsyncMock,
                side_effect=LlmProviderRefusalError(
                    'OpenAI-compatible provider returned 401: {"error": "invalid api key"}',
                    status_code=401,
                    connection_name='Recipe Reader',
                    model_name='gpt-4o-mini',
                ),
            ),
        ):
            with pytest.raises(LlmProviderRefusalError) as excinfo:
                await scrape_with_jina_llm_async(
                    MagicMock(),
                    uuid4(),
                    'https://example.com/recipe',
                    jina_api_key=None,
                    usage_ctx=None,
                )
        assert excinfo.value.status_code == 401
        assert not isinstance(excinfo.value, ValueError)


def _navigation(chars: int) -> str:
    """A site menu the way the reader renders one: nested list items, each
    a link and nothing else, with blank lines between groups."""
    lines: list[str] = []
    n = 0
    while sum(len(line) + 1 for line in lines) < chars:
        lines.append(
            f'*    [Category {n}](https://www.example-recipes.com/category/{n})'
        )
        lines.append(f'    *   [Sub {n}](https://www.example-recipes.com/sub/{n})')
        lines.append('')
        n += 1
    return '\n'.join(lines)


_RECIPE = (
    '# Fluffy pancakes\n\n'
    '### Ingredients\n\n'
    '*    2 cups wheat flour\n'
    '*    [salt](https://www.example-recipes.com/glossary/salt)\n'
    '*    [pepper](https://www.example-recipes.com/glossary/pepper)\n'
    '*    [nutmeg](https://www.example-recipes.com/glossary/nutmeg)\n'
    '*    3 eggs\n\n'
    '### Method\n\n'
    'Whisk everything and fry.\n'
)


@pytest.mark.asyncio
class TestWhatThePageSendsTheModel:
    """The prompt is bounded, so what fills the bound decides whether the
    recipe is in it at all."""

    async def _prompt_for(self, page: str) -> str:
        with (
            patch(
                'app.modules.recipes.scrapers.jina_llm._fetch_via_jina',
                return_value=page,
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.call_llm_async',
                new_callable=AsyncMock,
                return_value='{"title": "Fluffy pancakes", "ingredients": ["3 eggs"]}',
            ) as mock_llm,
        ):
            await scrape_with_jina_llm_async(
                MagicMock(), uuid4(), 'https://example.com/recipe'
            )
        assert mock_llm.await_args is not None
        return str(mock_llm.await_args.args[2])

    async def test_a_recipe_below_a_long_menu_still_reaches_the_model(self) -> None:
        page = (
            'Title: Fluffy pancakes\n\nMarkdown Content:\n'
            + _navigation(30_000)
            + '\n\n'
            + _RECIPE
        )
        assert page.index('# Fluffy pancakes') > 24_000

        prompt = await self._prompt_for(page)

        assert '2 cups wheat flour' in prompt
        assert '3 eggs' in prompt
        assert 'Category 0' not in prompt

    async def test_a_few_linked_ingredients_are_not_taken_for_a_menu(self) -> None:
        prompt = await self._prompt_for(_RECIPE)

        assert '[salt](https://www.example-recipes.com/glossary/salt)' in prompt
        assert '[nutmeg](https://www.example-recipes.com/glossary/nutmeg)' in prompt
