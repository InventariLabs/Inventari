"""Unit tests for ``ingredient_parser_translation``.

The fallback branches of ``translate_recipe_metadata_async`` are pure enough
to test without a DB; the LLM call is monkeypatched, so no registry or
network is involved. JSON extraction itself belongs to Core and is covered by
``tests/unit/test_ai_json_parsing.py``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.recipes.ingredient_parser_translation import (
    translate_recipe_metadata_async,
)


@pytest.mark.unit
class TestTranslateRecipeMetadataAsync:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_llm = AsyncMock(
            return_value='{"title": "Translated", "instructions": "Step 1"}'
        )
        monkeypatch.setattr('app.modules.recipes._llm_client.call_llm_async', mock_llm)
        monkeypatch.setattr('app.i18n.service.get_current_lang', lambda: 'en')

        title, instructions = await translate_recipe_metadata_async(
            MagicMock(), uuid4(), 'Original', 'Mix'
        )

        assert title == 'Translated'
        assert instructions == 'Step 1'

    async def test_null_instructions_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_llm = AsyncMock(
            return_value='{"title": "Translated", "instructions": null}'
        )
        monkeypatch.setattr('app.modules.recipes._llm_client.call_llm_async', mock_llm)
        monkeypatch.setattr('app.i18n.service.get_current_lang', lambda: 'en')

        title, instructions = await translate_recipe_metadata_async(
            MagicMock(), uuid4(), 'Original', 'Mix'
        )

        assert title == 'Translated'
        assert instructions is None

    async def test_missing_title_falls_back_to_original(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_llm = AsyncMock(return_value='{"instructions": "Step 1"}')
        monkeypatch.setattr('app.modules.recipes._llm_client.call_llm_async', mock_llm)
        monkeypatch.setattr('app.i18n.service.get_current_lang', lambda: 'en')

        title, _ = await translate_recipe_metadata_async(
            MagicMock(), uuid4(), 'Original', 'Mix'
        )

        assert title == 'Original'

    async def test_fence_after_a_preamble(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_llm = AsyncMock(
            return_value=(
                'Here is the translation:\n'
                '```json\n{"title": "Translated", "instructions": "Step 1"}\n```'
            )
        )
        monkeypatch.setattr('app.modules.recipes._llm_client.call_llm_async', mock_llm)
        monkeypatch.setattr('app.i18n.service.get_current_lang', lambda: 'en')

        title, instructions = await translate_recipe_metadata_async(
            MagicMock(), uuid4(), 'Original', 'Mix'
        )

        assert title == 'Translated'
        assert instructions == 'Step 1'

    async def test_raw_newlines_in_instructions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Markdown instructions arrive with literal newlines inside the string."""
        mock_llm = AsyncMock(
            return_value='{"title": "Translated", "instructions": "## Prep\n1. Mix\n2. Bake"}'
        )
        monkeypatch.setattr('app.modules.recipes._llm_client.call_llm_async', mock_llm)
        monkeypatch.setattr('app.i18n.service.get_current_lang', lambda: 'en')

        title, instructions = await translate_recipe_metadata_async(
            MagicMock(), uuid4(), 'Original', 'Mix'
        )

        assert title == 'Translated'
        assert instructions == '## Prep\n1. Mix\n2. Bake'

    async def test_prose_instead_of_json_keeps_originals(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_llm = AsyncMock(return_value='I cannot translate this text.')
        monkeypatch.setattr('app.modules.recipes._llm_client.call_llm_async', mock_llm)
        monkeypatch.setattr('app.i18n.service.get_current_lang', lambda: 'en')

        title, instructions = await translate_recipe_metadata_async(
            MagicMock(), uuid4(), 'Original', 'Mix'
        )

        assert title == 'Original'
        assert instructions == 'Mix'

    async def test_llm_error_keeps_originals(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_llm = AsyncMock(side_effect=RuntimeError('provider down'))
        monkeypatch.setattr('app.modules.recipes._llm_client.call_llm_async', mock_llm)
        monkeypatch.setattr('app.i18n.service.get_current_lang', lambda: 'en')

        title, instructions = await translate_recipe_metadata_async(
            MagicMock(), uuid4(), 'Original', 'Mix'
        )

        assert title == 'Original'
        assert instructions == 'Mix'

    async def test_invalid_json_keeps_originals(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_llm = AsyncMock(return_value='not json at all')
        monkeypatch.setattr('app.modules.recipes._llm_client.call_llm_async', mock_llm)
        monkeypatch.setattr('app.i18n.service.get_current_lang', lambda: 'en')

        title, instructions = await translate_recipe_metadata_async(
            MagicMock(), uuid4(), 'Original', 'Mix'
        )

        assert title == 'Original'
        assert instructions == 'Mix'

    async def test_target_language_uses_current_lang(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_llm = AsyncMock(return_value='{"title": "T", "instructions": "I"}')
        monkeypatch.setattr('app.modules.recipes._llm_client.call_llm_async', mock_llm)
        monkeypatch.setattr('app.i18n.service.get_current_lang', lambda: 'pl')

        await translate_recipe_metadata_async(MagicMock(), uuid4(), 'Original', 'Mix')

        prompt = mock_llm.call_args.args[2]
        assert 'Polish' in prompt

    async def test_unknown_lang_falls_back_to_english(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_llm = AsyncMock(return_value='{"title": "T", "instructions": "I"}')
        monkeypatch.setattr('app.modules.recipes._llm_client.call_llm_async', mock_llm)
        monkeypatch.setattr('app.i18n.service.get_current_lang', lambda: 'xx')

        await translate_recipe_metadata_async(MagicMock(), uuid4(), 'Original', 'Mix')

        prompt = mock_llm.call_args.args[2]
        assert 'English' in prompt
