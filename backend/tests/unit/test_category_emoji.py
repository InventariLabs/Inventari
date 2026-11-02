"""Unit tests for ``app.services.category_emoji``."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.category_emoji import (
    KEYWORD_EMOJI_MAP,
    LAST_RESORT_EMOJI,
    VERTICAL_DEFAULT_EMOJI,
    resolve_category_emoji,
)

# ── Layer 1: user override wins ─────────────────────────────────────────


class TestUserOverrideWins:
    def test_explicit_emoji_beats_keyword_match(self):
        # "Eggs" would match 'egg' → 🥚 via Layer 2, but explicit emoji wins.
        result = resolve_category_emoji(emoji='🐔', name='Eggs')
        assert result == '🐔'

    def test_explicit_emoji_beats_vertical_default(self):
        result = resolve_category_emoji(
            emoji='🎨', name='Generic', context_tag='equipment'
        )
        assert result == '🎨'

    def test_explicit_emoji_beats_last_resort(self):
        result = resolve_category_emoji(emoji='⭐', name='', code='')
        assert result == '⭐'

    def test_whitespace_only_emoji_treated_as_no_override(self):
        result = resolve_category_emoji(emoji='   ', name='Eggs')
        assert result == '🥚'

    def test_none_emoji_treated_as_no_override(self):
        result = resolve_category_emoji(emoji=None, name='Eggs')
        assert result == '🥚'


# ── Layer 2: keyword match ──────────────────────────────────────────────


class TestKeywordMatch:
    @pytest.mark.parametrize(
        'name,expected_emoji',
        [
            # Meat & protein
            ('Beef stew', '🥩'),
            ('Wołowina mielona', '🥩'),
            ('Pork chops', '🐖'),
            ('Wieprzowina', '🐖'),
            ('Chicken breast', '🍗'),
            ('Kurczak cały', '🍗'),
            ('Fresh fish', '🐟'),
            ('Ryba z frytownicy', '🐟'),
            ('Shrimp cocktail', '🦐'),
            ('Krewetki mrożone', '🦐'),
            ('Eggs (12)', '🥚'),
            ('Jajka wiejskie', '🥚'),
            ('Meat balls', '🍖'),
            ('Mięso mielone', '🍖'),
            # Prepared (dish types win over ingredient)
            ('Soup of the day', '🍲'),
            ('Zupa pomidorowa', '🍲'),
            ('Salad niçoise', '🥗'),
            ('Sałatka grecka', '🥗'),
            ('Orange juice', '🧃'),
            ('Sok jabłkowy', '🧃'),
            ('Ice cream', '🍨'),
            ('Lody waniliowe', '🍨'),
            # Bakery / pantry
            ('Bread loaf', '🍞'),
            ('Chleb wiejski', '🍞'),
            ('Pizza Margherita', '🍕'),
            ('Pasta carbonara', '🍝'),
            ('Makaron spaghetti', '🍝'),
            ('Rice bowl', '🍚'),
            ('Ryż basmati', '🍚'),
            ('Coffee beans', '☕'),
            ('Kawa mielona', '☕'),
            ('Tea time', '🍵'),
            ('Herbata czarna', '🍵'),
            ('Wine cellar', '🍷'),
            ('Wino czerwone', '🍷'),
            ('Beer craft', '🍺'),
            ('Piwo pszeniczne', '🍺'),
            ('Water bottle', '💧'),
            ('Woda mineralna', '💧'),
            # Dairy
            ('Milk 2%', '🥛'),
            ('Mleko UHT', '🥛'),
            ('Cheese board', '🧀'),
            ('Ser żółty', '🧀'),
            ('Butter unsalted', '🧈'),
            ('Masło ekstra', '🧈'),
            ('Greek yogurt', '🥛'),
            # Produce
            ('Fresh vegetable mix', '🥬'),
            ('Warzywa na patelnię', '🥬'),
            ('Apple pie', '🍎'),
            ('Jabłka zielone', '🍎'),
            ('Banana split', '🍌'),
            ('Banan dojrzały', '🍌'),
            ('Carrot sticks', '🥕'),
            ('Marchewka', '🥕'),
            ('Tomato sauce', '🍅'),
            ('Pomidory malinowe', '🍅'),
            ('Potato wedges', '🥔'),
            ('Ziemniaki młode', '🥔'),
            ('Onion rings', '🧅'),
            ('Cebula czerwona', '🧅'),
            # Equipment
            ('Laptop bag', '💻'),
            ('Monitor stand', '🖥️'),
            ('Ekran LCD', '🖥️'),
            ('Phone case', '📱'),
            ('Smartphone Pro', '📱'),
            ('Telefon biurowy', '📱'),
            ('Keyboard wireless', '⌨️'),
            ('Klawiatura mechaniczna', '⌨️'),
            ('Mouse pad', '🖱️'),
            ('Mysz bezprzewodowa', '🖱️'),
            ('Printer ink', '🖨️'),
            ('Drukarka laserowa', '🖨️'),
            ('Server rack', '🖥️'),
            ('Serwer produkcyjny', '🖥️'),
            ('Cable HDMI', '🔌'),
            ('Kabel sieciowy', '🔌'),
            # Tools
            ('Hammer drill', '🔨'),
            ('Młotek ślusarski', '🔨'),
            ('Wrench set', '🔧'),
            ('Klucz płaski', '🔧'),
            # Containers
            ('Glass bottle', '🍼'),
            ('Butelka wina', '🍼'),
            ('Storage jar', '🫙'),
            ('Słoik na przetwory', '🫙'),
            ('Canned beans', '🥫'),
            ('Puszka tuńczyka', '🥫'),
            # Office
            ('Office paper', '📄'),
            ('Papier ksero', '📄'),
            ('Długopis żelowy', '🖊️'),
            # Medical
            ('Pain medicine', '💊'),
            ('Lekarstwa domowe', '💊'),
            # Vehicles
            ('Family car', '🚗'),
            ('Samochód służbowy', '🚗'),
            ('Mountain bike', '🚲'),
            ('Rower górski', '🚲'),
        ],
    )
    def test_keyword_group_matches(self, name: str, expected_emoji: str):
        assert resolve_category_emoji(name=name) == expected_emoji

    def test_keyword_match_on_code(self):
        # When name is empty but code has the keyword, still matches.
        assert resolve_category_emoji(name='', code='EGGS') == '🥚'

    def test_keyword_match_is_case_insensitive(self):
        # 'egg' is a prefix keyword (whole_word=False), so 'eggs' matches.
        assert resolve_category_emoji(name='eggs') == '🥚'
        assert resolve_category_emoji(name='EGGS') == '🥚'
        assert resolve_category_emoji(name='EgGs') == '🥚'


# ── Layer 3: vertical default ────────────────────────────────────────────


class TestVerticalDefault:
    def test_equipment_context_with_no_keyword(self):
        result = resolve_category_emoji(name='Xylophone', context_tag='equipment')
        assert result == '💻'

    def test_food_context_with_no_keyword(self):
        result = resolve_category_emoji(name='Xylophone', context_tag='food')
        assert result == '🥫'

    def test_keyword_beats_vertical_default(self):
        # 'milk' keyword matches 🥛 even when context_tag='equipment'
        result = resolve_category_emoji(name='Milk 2%', context_tag='equipment')
        assert result == '🥛'

    def test_unknown_context_tag_falls_through(self):
        result = resolve_category_emoji(
            name='Xylophone', context_tag='unknown_vertical'
        )
        assert result == LAST_RESORT_EMOJI

    def test_null_context_tag_falls_through(self):
        result = resolve_category_emoji(name='Xylophone', context_tag=None)
        assert result == LAST_RESORT_EMOJI


# ── Layer 4: last resort ────────────────────────────────────────────────


class TestLastResort:
    def test_empty_everything_returns_package(self):
        assert (
            resolve_category_emoji(emoji=None, name='', code='', context_tag=None)
            == LAST_RESORT_EMOJI
        )

    def test_none_everything_returns_package(self):
        assert (
            resolve_category_emoji(emoji=None, name=None, code=None, context_tag=None)
            == LAST_RESORT_EMOJI
        )

    def test_unmatched_name_with_no_context_returns_package(self):
        assert (
            resolve_category_emoji(name='Zzzqwertyuiop', code='') == LAST_RESORT_EMOJI
        )


# ── Word-boundary rule (critical) ────────────────────────────────────────


class TestWordBoundary:
    """The matcher uses ``whole_word`` to prevent short stems from matching
    prefixes of unrelated words. E.g. PL 'ser' (cheese) must not match
    'serwer' (server), and 'can' (canned food) must not match 'canada'.
    """

    def test_ser_does_not_match_serwer(self):
        # 'serwer' starts with 'ser' but no word boundary on the right.
        result = resolve_category_emoji(name='Serwer produkcyjny')
        assert result == '🖥️'  # server wins

    def test_ser_matches_as_whole_word(self):
        assert resolve_category_emoji(name='Ser żółty') == '🧀'
        assert resolve_category_emoji(name='Ser') == '🧀'

    def test_can_does_not_match_canada(self):
        result = resolve_category_emoji(name='Canada')
        assert result == LAST_RESORT_EMOJI

    def test_can_does_not_match_candle(self):
        result = resolve_category_emoji(name='Candle wax')
        assert result == LAST_RESORT_EMOJI

    def test_can_matches_canned(self):
        # 'canned' is a separate prefix-keyword so it still matches.
        result = resolve_category_emoji(name='Canned beans')
        assert result == '🥫'

    def test_can_whole_word_matches(self):
        assert resolve_category_emoji(name='Can of beans') == '🥫'

    def test_box_does_not_match_boxer(self):
        # 'box' is whole_word=True. 'Boxer' has 'box' as a prefix but
        # no right boundary, so it must NOT match.
        result = resolve_category_emoji(name='Boxer')
        assert result == LAST_RESORT_EMOJI

    def test_box_matches_as_whole_word(self):
        assert resolve_category_emoji(name='Storage box') == '📦'
        assert resolve_category_emoji(name='Box') == '📦'

    def test_box_code_matches(self):
        assert resolve_category_emoji(name='', code='BOX-A1') == '📦'

    def test_bag_does_not_match_bagel(self):
        result = resolve_category_emoji(name='Bagel breakfast')
        assert result == LAST_RESORT_EMOJI

    def test_hat_does_not_match_hatch(self):
        result = resolve_category_emoji(name='Hatch door')
        assert result == LAST_RESORT_EMOJI

    def test_ice_cream_phrase_matches(self):
        # 'ice cream' is a literal phrase keyword.
        result = resolve_category_emoji(name='Ice cream tub')
        assert result == '🍨'

    def test_unicode_word_boundary_works_for_polish(self):
        # 'cebula' (onion) with Polish diacritics should match.
        result = resolve_category_emoji(name='Cebula czerwona')
        assert result == '🧅'


# ── Sync with frontend (TS) map ─────────────────────────────────────────


class TestKeywordMapsMatchFrontend:
    """Asserts that every keyword in the Python mirror matches the TypeScript
    source-of-truth file. If this test fails, one of the two maps drifted.
    """

    def test_python_map_is_non_empty(self):
        assert len(KEYWORD_EMOJI_MAP) > 0

    def test_vertical_defaults_documented(self):
        # Sanity: 'equipment' and 'food' are the only context_tags that
        # actually have defaults today. If a new one is added, update this.
        assert 'equipment' in VERTICAL_DEFAULT_EMOJI
        assert 'food' in VERTICAL_DEFAULT_EMOJI

    @pytest.mark.skipif(
        not Path('frontend/src/lib/categoryEmoji.ts').exists(),
        reason='frontend TS map not present in this checkout',
    )
    def test_keywords_present_in_python_and_frontend(self):
        """Parses the TS file with regex and asserts every keyword is mirrored."""
        ts_text = Path('frontend/src/lib/categoryEmoji.ts').read_text(encoding='utf-8')
        # Match the array entries: { keywords: ['beef', 'wołowin'], emoji: '🥩' }
        ts_entry_pattern = re.compile(
            r"keywords:\s*\[(?P<kws>[^\]]+)\]\s*,\s*emoji:\s*['\"](?P<e>[^'\"]+)['\"]"
        )
        ts_keywords: set[str] = set()
        for match in ts_entry_pattern.finditer(ts_text):
            kw_list = re.findall(r"['\"]([^'\"]+)['\"]", match.group('kws'))
            ts_keywords.update(kw_list)
        py_keywords: set[str] = set()
        for entry in KEYWORD_EMOJI_MAP:
            py_keywords.update(entry.keywords)
        missing_in_python = ts_keywords - py_keywords
        missing_in_frontend = py_keywords - ts_keywords
        assert not missing_in_python, (
            f'TS keywords missing from Python mirror: {sorted(missing_in_python)}'
        )
        assert not missing_in_frontend, (
            f'Python keywords missing from TS map: {sorted(missing_in_frontend)}'
        )


# ── Constants sanity ────────────────────────────────────────────────────


class TestConstants:
    def test_last_resort_is_package(self):
        assert LAST_RESORT_EMOJI == '📦'

    def test_healthy_glyph_diversity(self):
        """Sanity check: keywords should not all resolve to the same emoji
        (that would defeat the purpose). We just verify the unique-glyph count
        is a healthy fraction of the total entries.
        """
        glyphs = {entry.emoji for entry in KEYWORD_EMOJI_MAP}
        assert len(glyphs) >= 20, (
            f'Expected ≥20 distinct glyphs, got {len(glyphs)} — keyword map '
            f'may be too clustered.'
        )
