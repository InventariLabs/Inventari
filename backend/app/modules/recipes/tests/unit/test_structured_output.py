"""Unit tests: every recipes call site declares its output shape.

Each recipes LLM consumer supplies a hand-written ``json_schema`` that matches
the fields it then parses. :func:`app.modules.recipes._llm_client.call_llm_async`
forwards that schema into the :class:`LlmRequest` handed to the provider. These
tests drive the real ``call_llm_async`` with a fake client and assert the schema
that actually reached the client.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.llm.base import LlmRequest, LlmResponse
from app.modules.recipes._llm_client import call_llm_async
from app.modules.recipes.ingredient_parser_llm import (
    _INGREDIENT_SCHEMA,
    parse_ingredients_llm_with_status_async,
)
from app.modules.recipes.ingredient_parser_translation import (
    _METADATA_TRANSLATION_SCHEMA,
    translate_recipe_metadata_async,
)
from app.modules.recipes.scrapers.jina_llm import (
    _RECIPE_EXTRACTION_SCHEMA,
    scrape_with_jina_llm_async,
)
from app.modules.recipes.template_matcher import (
    _MATCH_SCHEMA,
    match_templates,
)

ORG_ID = uuid4()


def _patch_llm_resolver(monkeypatch: pytest.MonkeyPatch, response: str) -> AsyncMock:
    """Swap the LLM resolver for a fake client that captures the request."""
    mock_client = AsyncMock()
    mock_client.complete = AsyncMock(
        return_value=LlmResponse(content=response, usage={}, raw={})
    )
    monkeypatch.setattr(
        'app.core.public_api.llm.CoreLlmAPI.get_client_for_purpose_async',
        AsyncMock(return_value=mock_client),
    )
    monkeypatch.setattr(
        'app.core.public_api.ai_usage.CoreAIUsageAPI.log_llm_usage_async',
        AsyncMock(),
    )
    # The budget gate sits in front of the resolver; these tests are about
    # the request that reaches the client, so the counter answers "under".
    monkeypatch.setattr(
        'app.core.public_api.ai_usage.CoreAIUsageAPI.check_limit_async',
        AsyncMock(),
    )
    return mock_client


def _captured_schema(mock_client: AsyncMock) -> dict[str, Any] | None:
    request: LlmRequest = mock_client.complete.await_args.args[0]
    return request.json_schema


@pytest.mark.asyncio
class TestStructuredOutput:
    async def test_call_llm_async_forwards_json_schema(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        schema: dict[str, Any] = {
            'type': 'object',
            'properties': {'x': {'type': 'string'}},
        }
        mock_client = _patch_llm_resolver(monkeypatch, '{"x": "y"}')

        await call_llm_async(
            db=AsyncMock(),
            org_id=ORG_ID,
            prompt='parse this',
            usage_ctx=None,
            json_schema=schema,
        )

        assert _captured_schema(mock_client) == schema

    async def test_ingredient_parser_declares_schema(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr('app.i18n.service.get_current_lang', lambda: 'en')
        mock_client = _patch_llm_resolver(
            monkeypatch,
            '{"ingredients": [{"name": "flour", "metric_unit": "g"}]}',
        )

        await parse_ingredients_llm_with_status_async(
            AsyncMock(), ORG_ID, ['500 g flour'], usage_ctx=None
        )

        assert _captured_schema(mock_client) == _INGREDIENT_SCHEMA

    async def test_translation_declares_schema(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr('app.i18n.service.get_current_lang', lambda: 'en')
        mock_client = _patch_llm_resolver(
            monkeypatch, '{"title": "T", "instructions": "I"}'
        )

        await translate_recipe_metadata_async(
            AsyncMock(), ORG_ID, 'Original', 'Mix', usage_ctx=None
        )

        assert _captured_schema(mock_client) == _METADATA_TRANSLATION_SCHEMA

    async def test_jina_declares_schema(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr('app.i18n.service.get_current_lang', lambda: 'en')
        monkeypatch.setattr(
            'app.modules.recipes.scrapers.jina_llm._fetch_via_jina',
            lambda url, jina_api_key=None: '# Test page\nsome markdown',
        )
        mock_client = _patch_llm_resolver(
            monkeypatch,
            '{"title": "T", "ingredients": ["1 egg"], "servings": 2, '
            '"prep_time_minutes": 15}',
        )

        await scrape_with_jina_llm_async(
            AsyncMock(),
            ORG_ID,
            'https://example.com/recipe',
            jina_api_key=None,
            usage_ctx=None,
        )

        assert _captured_schema(mock_client) == _RECIPE_EXTRACTION_SCHEMA

    async def test_template_matcher_declares_schema(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        template = type('_TemplateStub', (), {'id': uuid4(), 'name': 'flour'})()

        async def fake_fetch(
            self: Any, db: Any, org_id: Any, *, limit: int = 200
        ) -> list[Any]:
            return [template]

        monkeypatch.setattr(
            'app.core.public_api.product_templates.CoreProductTemplatesAPI.'
            'list_for_org_with_recipe_usage_async',
            fake_fetch,
        )
        mock_client = _patch_llm_resolver(
            monkeypatch,
            f'{{"matches": [{{"index": 0, "template_id": "{template.id}"}}]}}',
        )

        await match_templates(MagicMock(), ORG_ID, ['flour'], usage_ctx=None)

        assert _captured_schema(mock_client) == _MATCH_SCHEMA
