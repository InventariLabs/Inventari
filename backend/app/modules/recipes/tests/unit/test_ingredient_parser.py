"""Unit tests for ingredient_parser — no DB, no network required."""

import json
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.recipes.ingredient_parser_basic import (
    parse_ingredients_basic,
)
from app.modules.recipes.ingredient_parser_llm import (
    parse_ingredients_llm_async,
    parse_ingredients_llm_with_status_async,
)


def _make_mock_llm(monkeypatch: pytest.MonkeyPatch, response: Any) -> AsyncMock:
    mock = AsyncMock(return_value=response)
    monkeypatch.setattr(
        'app.modules.recipes.ingredient_parser_llm.call_llm_async', mock
    )
    return mock


class TestParseIngredientsBasic:
    def test_number_unit_name(self) -> None:
        [r] = parse_ingredients_basic(['500 g flour'])
        assert r.quantity == Decimal('500')
        assert r.unit_symbol == 'g'
        assert r.name == 'flour'

    def test_number_no_unit(self) -> None:
        [r] = parse_ingredients_basic(['3 eggs'])
        assert r.quantity == Decimal('3')
        assert r.unit_symbol is None
        assert r.name == 'eggs'

    def test_unicode_fraction_half(self) -> None:
        [r] = parse_ingredients_basic(['½ kg butter'])
        assert r.quantity == Decimal('0.5')
        assert r.unit_symbol == 'kg'
        assert r.name == 'butter'

    def test_unicode_fraction_quarter(self) -> None:
        [r] = parse_ingredients_basic(['¼ l cream'])
        assert r.quantity == Decimal('0.25')
        assert r.unit_symbol == 'l'

    def test_dash_note_stripped(self) -> None:
        [r] = parse_ingredients_basic(['500 g beef — preferably ribeye'])
        assert r.name == 'beef'
        assert r.quantity == Decimal('500')

    def test_dash_hyphen_stripped(self) -> None:
        [r] = parse_ingredients_basic(['3 eggs - large'])
        assert r.name == 'eggs'

    def test_no_number_defaults_to_one(self) -> None:
        [r] = parse_ingredients_basic(['salt'])
        assert r.quantity == Decimal('1')
        assert r.name == 'salt'

    def test_unrecognized_unit_captured_as_original(self) -> None:
        # "łyżka" is not in _VALID_UNITS — quantity parsed, unit stays None,
        # but the unrecognized token is preserved in original_unit_text.
        [r] = parse_ingredients_basic(['1 łyżka soli'])
        assert r.quantity == Decimal('1')
        assert r.unit_symbol is None
        assert r.original_unit_text == 'łyżka'
        assert 'soli' in r.name


@pytest.mark.asyncio
class TestParseIngredientsLLMAsync:
    """Tests for the async, registry-backed parser."""

    async def test_successful_llm_parse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_json = json.dumps(
            [
                {
                    'name': 'flour',
                    'group_name': 'flour',
                    'quantity': 500,
                    'unit': 'g',
                    'original': '500 g flour',
                },
                {
                    'name': 'eggs',
                    'group_name': 'eggs',
                    'quantity': 3,
                    'unit': 'pcs',
                    'original': '3 eggs',
                },
            ]
        )
        _make_mock_llm(monkeypatch, mock_json)
        result = await parse_ingredients_llm_async(
            AsyncMock(),
            uuid4(),
            ['500 g flour', '3 eggs'],
            usage_ctx=None,
        )
        assert len(result) == 2
        assert result[0].name == 'flour'
        assert result[0].quantity == Decimal('500')
        assert result[0].unit_symbol == 'g'
        assert result[1].name == 'eggs'
        assert result[1].unit_symbol == 'pcs'

    async def test_group_name_extracted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_json = json.dumps(
            [
                {
                    'name': 'papryka słodka mielona',
                    'group_name': 'papryka',
                    'quantity': 5,
                    'unit': 'g',
                    'original': '1 łyżeczka słodkiej papryki',
                },
                {
                    'name': 'olej do smażenia',
                    'group_name': 'olej',
                    'quantity': 30,
                    'unit': 'ml',
                    'original': '2 łyżki oleju do smażenia',
                },
            ]
        )
        _make_mock_llm(monkeypatch, mock_json)
        result = await parse_ingredients_llm_async(
            AsyncMock(),
            uuid4(),
            ['1 łyżeczka słodkiej papryki', '2 łyżki oleju do smażenia'],
            usage_ctx=None,
        )
        assert result[0].group_name == 'papryka'
        assert result[0].quantity == Decimal('5')
        assert result[0].unit_symbol == 'g'
        assert result[1].group_name == 'olej'
        assert result[1].quantity == Decimal('30')
        assert result[1].unit_symbol == 'ml'

    async def test_culinary_unit_converted_to_metric(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_json = json.dumps(
            [
                {
                    'name': 'woda',
                    'group_name': 'woda',
                    'quantity': 375,
                    'unit': 'ml',
                    'original': '1,5 szklanki wody - 375 ml',
                },
            ]
        )
        _make_mock_llm(monkeypatch, mock_json)
        result = await parse_ingredients_llm_async(
            AsyncMock(),
            uuid4(),
            ['1,5 szklanki wody - 375 ml'],
            usage_ctx=None,
        )
        assert result[0].quantity == Decimal('375')
        assert result[0].unit_symbol == 'ml'
        assert result[0].original_text == '1,5 szklanki wody - 375 ml'

    async def test_llm_error_falls_back_to_basic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock = AsyncMock(side_effect=RuntimeError('API error'))
        monkeypatch.setattr(
            'app.modules.recipes.ingredient_parser_llm.call_llm_async', mock
        )
        result = await parse_ingredients_llm_async(
            AsyncMock(),
            uuid4(),
            ['500 g flour'],
        )
        # Falls back to basic parser — still produces a result
        assert len(result) == 1
        assert result[0].quantity == Decimal('500')

    async def test_llm_invalid_json_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_mock_llm(monkeypatch, 'not json at all')
        result = await parse_ingredients_llm_async(
            AsyncMock(),
            uuid4(),
            ['500 g flour'],
        )
        assert len(result) == 1  # basic fallback

    async def test_llm_wrapped_in_dict_unwrapped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_json = json.dumps(
            {
                'ingredients': [
                    {
                        'name': 'flour',
                        'group_name': 'flour',
                        'quantity': 500,
                        'unit': 'g',
                        'original': '500 g flour',
                    }
                ]
            }
        )
        _make_mock_llm(monkeypatch, mock_json)
        result = await parse_ingredients_llm_async(
            AsyncMock(),
            uuid4(),
            ['500 g flour'],
        )
        assert result[0].name == 'flour'

    async def test_llm_markdown_fence_stripped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_json = (
            '```json\n'
            '[{"name": "flour", "group_name": "flour", "quantity": 500, "unit": "g", "original": "500 g flour"}]\n'
            '```'
        )
        _make_mock_llm(monkeypatch, mock_json)
        result = await parse_ingredients_llm_async(
            AsyncMock(),
            uuid4(),
            ['500 g flour'],
        )
        assert result[0].name == 'flour'

    async def test_llm_fence_after_a_preamble(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_json = (
            'Sure, here are the parsed ingredients:\n'
            '```json\n'
            '[{"name": "flour", "group_name": "flour", "quantity": 500, "unit": "g", "original": "500 g flour"}]\n'
            '```\n'
            'Let me know if you need anything else.'
        )
        _make_mock_llm(monkeypatch, mock_json)
        result = await parse_ingredients_llm_async(
            AsyncMock(),
            uuid4(),
            ['500 g flour'],
        )
        assert result[0].name == 'flour'

    async def test_llm_response_cut_off_keeps_the_complete_entries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A truncated list used to fall back to the basic parser wholesale."""
        mock_json = (
            '[{"name": "flour", "group_name": "flour", "quantity": 500, '
            '"unit": "g", "original": "500 g flour"}, {"name": "eg'
        )
        _make_mock_llm(monkeypatch, mock_json)
        result = await parse_ingredients_llm_async(
            AsyncMock(),
            uuid4(),
            ['500 g flour', '3 eggs'],
        )
        assert len(result) == 1
        assert result[0].name == 'flour'
        assert result[0].quantity == Decimal('500')

    async def test_llm_invalid_unit_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_json = json.dumps(
            [
                {
                    'name': 'sugar',
                    'group_name': 'sugar',
                    'quantity': 2,
                    'unit': 'bushels',
                    'original': '2 bushels sugar',
                },
            ]
        )
        _make_mock_llm(monkeypatch, mock_json)
        result = await parse_ingredients_llm_async(
            AsyncMock(),
            uuid4(),
            ['2 bushels sugar'],
        )
        # 'bushels' is not in _VALID_UNITS — robustness check for LLM non-compliance
        assert result[0].unit_symbol is None
        assert result[0].name == 'sugar'

    async def test_empty_lines_input(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = await parse_ingredients_llm_async(
            AsyncMock(),
            uuid4(),
            [],
            usage_ctx=None,
        )
        assert result == []

    async def test_unit_display_kept_for_culinary_units(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_json = json.dumps(
            [
                {
                    'name': 'black pepper',
                    'group_name': 'pepper',
                    'quantity': 1,
                    'unit_text': 'szczypta',
                    'unit_display': 'pinch',
                    'metric_quantity': 0.5,
                    'metric_unit': 'g',
                    'original': 'pieprz czarny - 1 szczypta',
                },
            ]
        )
        _make_mock_llm(monkeypatch, mock_json)
        result = await parse_ingredients_llm_async(
            AsyncMock(),
            uuid4(),
            ['pieprz czarny - 1 szczypta'],
            usage_ctx=None,
        )
        assert result[0].original_unit_text == 'szczypta'
        assert result[0].unit_display == 'pinch'
        assert result[0].original_quantity == Decimal('1')
        assert result[0].quantity == Decimal('0.5')
        assert result[0].unit_symbol == 'g'

    async def test_unit_display_nulled_for_metric_units(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_json = json.dumps(
            [
                {
                    'name': 'parsley root',
                    'group_name': 'parsley root',
                    'quantity': 150,
                    'unit_text': 'g',
                    'unit_display': 'g',
                    'metric_quantity': 150,
                    'metric_unit': 'g',
                    'original': 'korzeń pietruszki - 150 g',
                },
            ]
        )
        _make_mock_llm(monkeypatch, mock_json)
        result = await parse_ingredients_llm_async(
            AsyncMock(),
            uuid4(),
            ['korzeń pietruszki - 150 g'],
            usage_ctx=None,
        )
        assert result[0].original_unit_text is None
        assert result[0].unit_display is None
        assert result[0].original_quantity is None


@pytest.mark.asyncio
class TestParseIngredientsWithStatus:
    """parse_ingredients_llm_with_status_async reports fallback usage so the
    import preview can warn the user about the degraded (untranslated) parse."""

    async def test_success_reports_no_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_json = json.dumps(
            [
                {
                    'name': 'flour',
                    'group_name': 'flour',
                    'quantity': 500,
                    'unit': 'g',
                    'original': '500 g flour',
                },
            ]
        )
        _make_mock_llm(monkeypatch, mock_json)
        outcome = await parse_ingredients_llm_with_status_async(
            AsyncMock(), uuid4(), ['500 g flour'], usage_ctx=None
        )
        assert outcome.used_fallback is False
        assert outcome.fallback_reason is None
        assert outcome.items[0].name == 'flour'

    async def test_llm_error_reports_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock = AsyncMock(side_effect=RuntimeError('provider down'))
        monkeypatch.setattr(
            'app.modules.recipes.ingredient_parser_llm.call_llm_async', mock
        )
        outcome = await parse_ingredients_llm_with_status_async(
            AsyncMock(), uuid4(), ['500 g flour'], usage_ctx=None
        )
        assert outcome.used_fallback is True
        assert outcome.fallback_reason == 'provider down'
        assert outcome.items[0].quantity == Decimal('500')

    async def test_empty_llm_result_reports_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_mock_llm(monkeypatch, '[]')
        outcome = await parse_ingredients_llm_with_status_async(
            AsyncMock(), uuid4(), ['500 g flour'], usage_ctx=None
        )
        assert outcome.used_fallback is True
        assert outcome.fallback_reason == 'empty_result'
        assert outcome.items[0].name == 'flour'

    async def test_empty_input_no_fallback(self) -> None:
        outcome = await parse_ingredients_llm_with_status_async(
            AsyncMock(), uuid4(), [], usage_ctx=None
        )
        assert outcome.used_fallback is False
        assert outcome.items == []
