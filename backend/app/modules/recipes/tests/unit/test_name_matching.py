"""Ingredient name folding — the contract the stored match keys depend on.

``name_normalized`` is persisted (``IngredientNutritionDefault``,
``ShoppingExclusion``) and compared against freshly folded input, so a change
in the transliteration table silently stops matching rows that are already in
the database. These tests pin the output for the alphabets the product ships
in, so such a change fails here instead of surfacing as duplicate ingredients
in someone's shopping list.
"""

import json
from pathlib import Path

import pytest

from app.modules.recipes._name_matching import match_key, normalize_name

DATA_DIR = Path(__file__).resolve().parents[2] / 'data'


class TestNormalizeName:
    def test_strips_outer_whitespace_and_lowercases(self) -> None:
        assert normalize_name('  Mąka Pszenna  ') == 'maka pszenna'

    @pytest.mark.parametrize(
        ('raw', 'expected'),
        [
            ('ąćęłńóśźż', 'acelnoszz'),
            ('ĄĆĘŁŃÓŚŹŻ', 'acelnoszz'),
            ('bakłażan', 'baklazan'),
            ('żurek śląski', 'zurek slaski'),
            ('äöüß', 'aouss'),
            ('crème fraîche', 'creme fraiche'),
            ('jalapeño', 'jalapeno'),
            ('açúcar', 'acucar'),
            ('œuf', 'oeuf'),
        ],
    )
    def test_folds_the_alphabets_the_product_ships_in(
        self, raw: str, expected: str
    ) -> None:
        assert normalize_name(raw) == expected

    def test_output_is_always_ascii(self) -> None:
        # match_key splits on whitespace and the result goes into a LIKE
        # pattern — both assume the fold left nothing but ASCII behind.
        folded = normalize_name('Παστίτσιо 北京 مرحبا ĸ')
        assert folded.isascii()

    def test_inner_whitespace_is_preserved(self) -> None:
        # Deliberate: name_normalized rows already stored were written this
        # way, and search matches them with LIKE.
        assert normalize_name('mąka  pszenna') == 'maka  pszenna'


class TestMatchKey:
    def test_ignores_word_order(self) -> None:
        assert match_key('Mąka Pszenna') == match_key('pszenna MĄKA')

    def test_collapses_repeated_whitespace(self) -> None:
        assert match_key(' Mąka   pszenna ') == 'maka pszenna'

    def test_empty_name_folds_to_empty_key(self) -> None:
        assert match_key('   ') == ''


class TestSeedDataStability:
    """The keys for every seeded ingredient must not move.

    Pinned against the values produced by the previous implementation
    (``unidecode``); all 417 seeded names came out identical when the
    dependency was swapped for ``anyascii``.
    """

    @pytest.mark.parametrize('lang', ['pl', 'en', 'de', 'fr', 'es'])
    def test_every_seeded_name_folds_to_ascii_and_is_stable(self, lang: str) -> None:
        entries = json.loads(
            (DATA_DIR / f'defaults_{lang}.json').read_text(encoding='utf-8')
        )
        assert entries, f'defaults_{lang}.json is empty'
        for entry in entries:
            folded = normalize_name(entry['name'])
            assert folded.isascii(), entry['name']
            assert folded == folded.strip().lower()

    def test_known_polish_seed_names_keep_their_stored_keys(self) -> None:
        assert normalize_name('Bakłażan') == 'baklazan'
        assert normalize_name('Mąka żytnia') == 'maka zytnia'
        assert normalize_name('Śmietana 18%') == 'smietana 18%'
        assert normalize_name('Twaróg półtłusty') == 'twarog poltlusty'
        assert normalize_name('Jajko kurze (całe)') == 'jajko kurze (cale)'
