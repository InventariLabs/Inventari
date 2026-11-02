"""Tests for import_parquet helper functions.

Covers pure data-transformation utilities without requiring DB or file I/O.
"""

import sys

import pytest

from app.modules.nutrition import import_parquet
from app.modules.nutrition.import_parquet import (
    catalogue_barcode,
    clean_string,
    extract_nested_text,
    extract_nutrient_levels,
    extract_nutriments,
)


class TestCleanString:
    def test_removes_null_bytes(self) -> None:
        assert clean_string('hello\x00world') == 'helloworld'

    def test_strips_surrounding_whitespace(self) -> None:
        assert clean_string('  abc  ') == 'abc'

    def test_returns_none_for_none(self) -> None:
        assert clean_string(None) is None

    def test_returns_none_for_whitespace_only(self) -> None:
        assert clean_string('   ') is None

    def test_converts_non_string(self) -> None:
        assert clean_string(42) == '42'


class TestCatalogueBarcode:
    """The catalogue files a row under the same key the rest of the app uses.

    Open Food Facts ships UPC-A and EAN-8 alongside EAN-13. Padding only the
    12-digit ones here is how a scanned EAN-8 stopped finding the product
    this importer had already stored under its 13-digit form.
    """

    def test_upc_a_is_padded_to_ean13(self) -> None:
        assert catalogue_barcode('012345678901') == '0012345678901'

    def test_ean8_is_padded_to_ean13(self) -> None:
        assert catalogue_barcode('96385074') == '0000096385074'

    def test_ean13_passes_through(self) -> None:
        assert catalogue_barcode('5901234123457') == '5901234123457'

    def test_returns_none_for_a_row_without_a_code(self) -> None:
        assert catalogue_barcode('') is None
        assert catalogue_barcode(None) is None


class TestExtractNestedText:
    def test_returns_none_for_empty(self) -> None:
        assert extract_nested_text(None) is None
        assert extract_nested_text('') is None
        assert extract_nested_text([]) is None

    def test_extracts_preferred_language(self) -> None:
        val = [
            {'lang': 'en', 'text': 'English name'},
            {'lang': 'pl', 'text': 'Polish name'},
        ]
        # Default preferred: ['pl', 'en', 'main'] → 'pl' found first
        result = extract_nested_text(val)
        assert result == 'Polish name'

    def test_falls_back_to_en(self) -> None:
        val = [
            {'lang': 'en', 'text': 'English name'},
            {'lang': 'de', 'text': 'German name'},
        ]
        result = extract_nested_text(val)
        assert result == 'English name'

    def test_plain_string_returned_as_is(self) -> None:
        assert extract_nested_text('Plain text') == 'Plain text'

    def test_list_of_strings_joined(self) -> None:
        result = extract_nested_text(['Oats', 'Sugar', 'Salt'])
        assert result == 'Oats, Sugar, Salt'

    def test_json_string_parsed(self) -> None:
        import json

        val = json.dumps([{'lang': 'en', 'text': 'Test'}])
        result = extract_nested_text(val)
        assert result == 'Test'


class TestExtractNutriments:
    def test_empty_list_returns_empty_dict(self) -> None:
        assert extract_nutriments([]) == {}

    def test_none_returns_empty_dict(self) -> None:
        assert extract_nutriments(None) == {}

    def test_extracts_known_nutrients(self) -> None:
        nutriments = [
            {'name': 'energy-kcal', '100g': '350'},
            {'name': 'proteins', '100g': '8.5'},
            {'name': 'fat', '100g': '3.2'},
        ]
        result = extract_nutriments(nutriments)
        assert result['energy_kcal'] == 350.0
        assert result['proteins'] == 8.5
        assert result['fat'] == 3.2

    def test_skips_unknown_nutrient_names(self) -> None:
        nutriments = [
            {'name': 'unknown_stuff', '100g': '99'},
            {'name': 'energy-kcal', '100g': '200'},
        ]
        result = extract_nutriments(nutriments)
        assert 'unknown_stuff' not in result
        assert result['energy_kcal'] == 200.0

    def test_skips_entries_with_missing_100g(self) -> None:
        nutriments = [
            {'name': 'proteins'},  # no '100g' key
        ]
        result = extract_nutriments(nutriments)
        assert result == {}

    def test_maps_saturated_fat_key(self) -> None:
        nutriments = [{'name': 'saturated-fat', '100g': '1.5'}]
        result = extract_nutriments(nutriments)
        assert result['saturated_fat'] == 1.5


class TestExtractNutrientLevels:
    def test_parses_standard_tags(self) -> None:
        tags = [
            'en:sugars-in-high-quantity',
            'en:fat-in-moderate-quantity',
            'en:salt-in-low-quantity',
        ]
        result = extract_nutrient_levels(tags)
        assert result['sugars'] == 'high'
        assert result['fat'] == 'moderate'
        assert result['salt'] == 'low'

    def test_returns_empty_for_non_list(self) -> None:
        assert extract_nutrient_levels(None) == {}
        assert extract_nutrient_levels('invalid') == {}

    def test_skips_malformed_tags(self) -> None:
        tags = ['en:no-separator-here', 'en:valid-in-high-quantity']
        result = extract_nutrient_levels(tags)
        assert 'valid' in result
        # malformed tag produces no entry
        assert len(result) == 1


class TestMainExitStatus:
    """What ``make off-import`` sees: the process exit code."""

    def test_exits_nonzero_when_the_import_did_not_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, 'argv', ['import_parquet', '/absent.parquet'])
        monkeypatch.setattr(import_parquet, 'import_off_parquet', lambda *a: False)
        with pytest.raises(SystemExit) as exit_info:
            import_parquet.main()
        assert exit_info.value.code == 1

    def test_returns_normally_when_it_ran(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, 'argv', ['import_parquet', '/f.parquet', '500'])
        calls: list[tuple[str, int]] = []

        def fake_import(path: str, size: int) -> bool:
            calls.append((path, size))
            return True

        monkeypatch.setattr(import_parquet, 'import_off_parquet', fake_import)
        import_parquet.main()
        assert calls == [('/f.parquet', 500)]
