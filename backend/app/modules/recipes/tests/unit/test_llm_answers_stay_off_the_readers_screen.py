"""What a model or an HTTP library said never becomes the reader's sentence.

``recipe_scrape_failed`` used to carry ``{error}``: whatever the scraper
raised — a provider's answer, ``httpx``'s message, the "unexpected type"
guard — was glued onto the Polish sentence, so a Polish reader got English
internals. The malformed-answer guards now raise ``LlmContractError``, the
class that says its text is for the log.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.llm.errors import LlmContractError
from app.i18n.service import get_error_message, set_current_lang
from app.modules.recipes._import_url_pipeline import _parse_import_url
from app.modules.recipes.ingredient_parser_llm import _parse_ingredients_payload
from app.modules.recipes.scrapers.jina_llm import scrape_with_jina_llm_async


@pytest.fixture
def polish() -> Iterator[None]:
    set_current_lang('pl')
    yield
    set_current_lang('en')


@pytest.mark.unit
class TestScrapeFailureSentence:
    async def test_polish_sentence_carries_no_exception_text(
        self, polish: None
    ) -> None:
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
                side_effect=RuntimeError('boom-internal'),
            ),
        ):
            with pytest.raises(ValueError) as excinfo:
                await _parse_import_url(
                    'https://example.com/r', MagicMock(), uuid4(), uuid4()
                )
        assert str(excinfo.value) == get_error_message('recipe_scrape_failed', 'pl')
        assert 'boom-internal' not in str(excinfo.value)
        assert str(excinfo.value) == 'Nie udało się pobrać przepisu z adresu URL'


@pytest.mark.unit
class TestMalformedAnswersAreNotReaderFacing:
    async def test_scraper_answer_of_the_wrong_type(self) -> None:
        with (
            patch(
                'app.modules.recipes.scrapers.jina_llm._fetch_via_jina',
                return_value='# page',
            ),
            patch(
                'app.modules.recipes.scrapers.jina_llm.call_llm_async',
                new_callable=AsyncMock,
                return_value='["not", "a", "dict"]',
            ),
        ):
            with pytest.raises(LlmContractError, match='unexpected type list'):
                await scrape_with_jina_llm_async(
                    MagicMock(),
                    uuid4(),
                    'https://example.com/recipe',
                    jina_api_key=None,
                    usage_ctx=None,
                )

    def test_ingredient_parser_answer_of_the_wrong_type(self) -> None:
        with pytest.raises(LlmContractError, match='Expected JSON array'):
            _parse_ingredients_payload('just prose')
