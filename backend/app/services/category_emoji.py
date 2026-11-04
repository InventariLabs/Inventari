"""Server-side mirror of the frontend keyword→emoji map.

Kept in sync with ``frontend/src/lib/categoryEmoji.ts`` via
``test_keyword_maps_match_frontend`` (asserts every TS keyword appears here
and vice versa).

Used by:
- ``app.cli.backfill_category_emoji`` to populate the ``Category.emoji`` column
  for high-confidence keyword matches.

The 4-layer cascade mirrors the frontend resolver:
  1. user-set ``emoji`` (overrides everything below)
  2. keyword guess on ``name`` / ``code`` (word-boundary, case-insensitive)
  3. vertical default by ``context_tag``
  4. last-resort ``📦``
"""

from __future__ import annotations

import re
from typing import NamedTuple

# Order matters within a group: longer / more-specific keys first so e.g.
# 'ice cream' matches before 'cream'. The matcher takes the first entry
# whose keywords produce a match.
#
# `whole_word=True` enforces a word-boundary on BOTH sides of the keyword
# (\\b{kw}\\b) so that short stems like 'ser' (cheese) do not match prefixes
# of unrelated words like 'serwer' (server). False (default) uses only the
# start boundary (\\b{kw}), which is fine for longer unambiguous stems.


class _EmojiEntry(NamedTuple):
    keywords: tuple[str, ...]
    emoji: str
    whole_word: bool = False


KEYWORD_EMOJI_MAP: list[_EmojiEntry] = [
    # ── Food: meat & protein ─────────────────────────────────
    _EmojiEntry(('beef', 'wołowin'), '🥩'),
    _EmojiEntry(('pork', 'wieprzow'), '🐖'),
    _EmojiEntry(('chicken', 'kurczak'), '🍗'),
    _EmojiEntry(('fish', 'ryb'), '🐟'),
    _EmojiEntry(('seafood', 'shell', 'krewet', 'shrimp'), '🦐'),
    _EmojiEntry(('egg', 'jaj'), '🥚'),
    _EmojiEntry(('meat', 'mięso', 'mieso'), '🍖'),
    # ── Food: prepared (soup before tomato/apple so dish types win) ──
    _EmojiEntry(('soup', 'zupa'), '🍲'),
    _EmojiEntry(('juice', 'sok'), '🧃'),
    _EmojiEntry(('ice cream', 'lody'), '🍨'),
    # ── Food: bakery / pantry ────────────────────────────────
    _EmojiEntry(('bread', 'chleb'), '🍞'),
    _EmojiEntry(('croissant', 'rogalik'), '🥐'),
    _EmojiEntry(('pizza',), '🍕'),
    _EmojiEntry(('pasta', 'makaron'), '🍝'),
    _EmojiEntry(('rice', 'ryż', 'ryz'), '🍚'),
    _EmojiEntry(('sandwich', 'kanapk'), '🥪'),
    _EmojiEntry(('salad', 'sałatk'), '🥗'),
    _EmojiEntry(('cookie', 'ciastk'), '🍪'),
    _EmojiEntry(('cake', 'ciasto'), '🍰'),
    _EmojiEntry(('candy', 'cukierek'), '🍬'),
    _EmojiEntry(('chocolate', 'czekolad'), '🍫'),
    _EmojiEntry(('honey', 'miód', 'miod'), '🍯'),
    _EmojiEntry(('coffee', 'kawa'), '☕'),
    _EmojiEntry(('tea', 'herbat'), '🍵'),
    _EmojiEntry(('wine', 'wino'), '🍷'),
    _EmojiEntry(('beer', 'piwo'), '🍺'),
    _EmojiEntry(('water', 'woda'), '💧'),
    # ── Food: dairy ──────────────────────────────────────────
    _EmojiEntry(('milk', 'mlek'), '🥛'),
    _EmojiEntry(('cheese',), '🧀'),
    _EmojiEntry(('ser',), '🧀', whole_word=True),  # 'serwer' must NOT match
    _EmojiEntry(('butter', 'masł'), '🧈'),
    _EmojiEntry(('yogurt', 'jogurt'), '🥛'),
    # ── Food: produce ────────────────────────────────────────
    _EmojiEntry(('vegetable', 'warzywa'), '🥬'),
    _EmojiEntry(('apple', 'jabł'), '🍎'),
    _EmojiEntry(('fruit', 'owoc'), '🍎'),
    _EmojiEntry(('banana', 'banan'), '🍌'),
    _EmojiEntry(('carrot', 'marchew'), '🥕'),
    _EmojiEntry(('tomato', 'pomidor'), '🍅'),
    _EmojiEntry(('potato', 'ziemniak'), '🥔'),
    _EmojiEntry(('onion', 'cebula'), '🧅'),
    _EmojiEntry(('garlic', 'czosnek'), '🧄'),
    _EmojiEntry(('corn', 'kukurydz'), '🌽'),
    _EmojiEntry(('mushroom', 'pieczark'), '🍄'),
    _EmojiEntry(('avocado', 'awokado'), '🥑'),
    _EmojiEntry(('lemon', 'cytryna'), '🍋'),
    _EmojiEntry(('grape', 'winogron'), '🍇'),
    _EmojiEntry(('cherry', 'wiśnia'), '🍒'),
    _EmojiEntry(('strawberry', 'truskaw'), '🍓'),
    # ── Food: umbrella terms. A shop-level category is named 'Dairy' or
    # 'Snacks', not 'Milk' — without these every such card fell through to
    # the last-resort box.
    _EmojiEntry(('dairy', 'nabiał', 'nabial'), '🥛'),
    _EmojiEntry(('frozen', 'mrożon', 'mrozon'), '🧊'),
    _EmojiEntry(('deli',), '🥓', whole_word=True),  # avoid 'delivery'
    _EmojiEntry(('wędlin', 'wedlin'), '🥓'),
    _EmojiEntry(('drink', 'beverage', 'napój', 'napoj'), '🥤'),
    _EmojiEntry(('snack', 'przekąsk', 'przekask'), '🍿'),
    _EmojiEntry(('sweet', 'słodycz', 'slodycz'), '🍬'),
    _EmojiEntry(('spice', 'przypraw', 'herb', 'zioł'), '🧂'),
    _EmojiEntry(('sauce', 'sos'), '🥫'),
    _EmojiEntry(('oil', 'olej', 'oliw'), '🫒'),
    _EmojiEntry(('flour', 'mąka', 'maka'), '🌾'),
    _EmojiEntry(('grain', 'kasza', 'cereal', 'płatk', 'platk'), '🌾'),
    _EmojiEntry(('produce', 'warzyw'), '🥬'),
    # ── Equipment / IT (server before 'ser' group handled above) ──
    _EmojiEntry(('server', 'serwer'), '🗄️'),
    _EmojiEntry(('laptop', 'notebook'), '💻'),
    _EmojiEntry(('monitor', 'ekran', 'display'), '📺'),
    _EmojiEntry(('phone', 'smartphone', 'telefon'), '📱'),
    _EmojiEntry(('tablet',), '📱'),
    _EmojiEntry(('keyboard', 'klawiatur'), '⌨️'),
    _EmojiEntry(('mouse', 'mysz'), '🖱️'),
    _EmojiEntry(('printer', 'drukark'), '🖨️'),
    _EmojiEntry(('camera', 'aparat', 'kamer'), '📷'),
    _EmojiEntry(('cable', 'kabel', 'wire', 'przewód'), '🔌'),
    _EmojiEntry(('battery', 'bateria', 'akumulator'), '🔋'),
    _EmojiEntry(('chip', 'cpu', 'procesor'), '🔩'),
    _EmojiEntry(('desktop', 'stacjonarn'), '🖥️'),
    _EmojiEntry(('network', 'router', 'sieciow'), '🔌'),
    _EmojiEntry(('peripheral', 'peryferi'), '🖱️'),
    # The catch-all preset: by its code, so it does not share the laptop the
    # vertical default would give it.
    _EmojiEntry(('other_equipment',), '🧰'),
    # ── Tools ────────────────────────────────────────────────
    _EmojiEntry(('tool', 'narzędz'), '🧰'),
    _EmojiEntry(('hammer', 'młotek'), '🔨'),
    _EmojiEntry(('wrench', 'klucz'), '🔧'),
    _EmojiEntry(('screwdriver', 'śrubokręt'), '🪛'),
    _EmojiEntry(('drill', 'wiertark'), '🪛'),
    _EmojiEntry(('saw', 'piła', 'pila'), '🪚'),
    _EmojiEntry(('knife', 'nóż', 'noz'), '🔪'),
    _EmojiEntry(('scissors', 'nożyce'), '✂️'),
    _EmojiEntry(('ladder', 'drabina'), '🪜'),
    # ── Containers / storage ─────────────────────────────────
    _EmojiEntry(('box',), '📦', whole_word=True),  # avoid 'boxer', 'boxes'
    _EmojiEntry(('pudło', 'pudel'), '📦'),
    _EmojiEntry(('bottle', 'butelk'), '🍼'),
    _EmojiEntry(('jar', 'słoik'), '🫙'),
    _EmojiEntry(('canned', 'canned food', 'puszk'), '🥫'),
    _EmojiEntry(('can',), '🥫', whole_word=True),  # avoid 'canada', 'candle'
    _EmojiEntry(('bag',), '🛍️', whole_word=True),  # avoid 'bagel', 'baggage'
    _EmojiEntry(('torba',), '🛍️'),
    # ── Office / stationery ──────────────────────────────────
    _EmojiEntry(('book', 'książka', 'ksiazka'), '📚'),
    _EmojiEntry(('notes',), '📓'),
    _EmojiEntry(('pen',), '🖊️', whole_word=True),  # avoid 'pencil', 'pending'
    _EmojiEntry(('długopis',), '🖊️'),
    _EmojiEntry(('pencil', 'ołówek'), '✏️'),
    _EmojiEntry(('paper', 'papier'), '📄'),
    _EmojiEntry(('folder', 'teczk'), '📁'),
    _EmojiEntry(('stapler', 'zszywacz'), '📎'),
    # ── Medical / lab ────────────────────────────────────────
    _EmojiEntry(('medicine', 'lekarstw'), '💊'),
    _EmojiEntry(('pill', 'tabletka'), '💊'),
    _EmojiEntry(('bandage', 'bandaż'), '🩹'),
    _EmojiEntry(('thermometer', 'termometr'), '🌡️'),
    _EmojiEntry(('syringe', 'strzykawk'), '💉'),
    # ── Apparel / personal ───────────────────────────────────
    _EmojiEntry(('shirt', 'koszul'), '👕'),
    _EmojiEntry(('shoe',), '👟', whole_word=True),  # avoid 'shoebox'
    _EmojiEntry(('but',), '👟'),  # PL 'but' (shoe) — word-start match
    _EmojiEntry(('glasses', 'okular'), '👓'),
    _EmojiEntry(('hat',), '🧢', whole_word=True),  # avoid 'hatch', 'hatrack'
    _EmojiEntry(('kapelusz', 'czapk'), '🧢'),
    _EmojiEntry(('glove', 'rękawic'), '🧤'),
    # ── Vehicles ─────────────────────────────────────────────
    _EmojiEntry(('car', 'samochód'), '🚗'),
    _EmojiEntry(('bike', 'rower'), '🚲'),
    _EmojiEntry(('truck', 'ciężarów'), '🚚'),
    # ── Garden / outdoor ─────────────────────────────────────
    _EmojiEntry(('plant', 'roślin'), '🪴'),
    _EmojiEntry(('flower', 'kwiat'), '🌷'),
    _EmojiEntry(('tree', 'drzewo'), '🌳'),
    _EmojiEntry(('seed', 'nasion'), '🌱'),
    _EmojiEntry(('fertilizer', 'nawóz'), '🧪'),
]

# Vertical default emoji (cascade layer 3). Keys correspond to
# ``Category.context_tag`` values actually used in the codebase. New verticals
# MUST add an entry here; the matcher also falls through to LAST_RESORT_EMOJI.
VERTICAL_DEFAULT_EMOJI: dict[str, str] = {
    'equipment': '💻',
    'food': '🥫',
}

LAST_RESORT_EMOJI = '📦'


def resolve_category_emoji(
    *,
    emoji: str | None = None,
    name: str | None = None,
    code: str | None = None,
    context_tag: str | None = None,
) -> str:
    """Resolve the display emoji for a category, applying the 4-layer cascade.

    Pure function — same inputs always yield the same output. Used by
    ``app.cli.backfill_category_emoji`` and any backend service that needs
    to know which emoji a category would render with (e.g. for analytics
    exports or PDF generation).
    """
    result, _layer = resolve_category_emoji_with_layer(
        emoji=emoji, name=name, code=code, context_tag=context_tag
    )
    return result


def resolve_category_emoji_with_layer(
    *,
    emoji: str | None = None,
    name: str | None = None,
    code: str | None = None,
    context_tag: str | None = None,
) -> tuple[str, int]:
    """Like :func:`resolve_category_emoji` but also returns which cascade
    layer produced the result:

    - 1 = user-set ``emoji`` (override)
    - 2 = keyword match on name / code
    - 3 = vertical default by ``context_tag``
    - 4 = last resort

    Used by the backfill CLI to decide whether a backfilled emoji is
    high-confidence (layer 2) and worth persisting. Layers 3 and 4 stay
    dynamic so a future ``context_tag`` change is still reflected at
    render time even after the DB row has been backfilled.
    """
    # Layer 1: explicit user override.
    if emoji and emoji.strip():
        return emoji, 1

    # Layer 2: keyword match on name OR code, case-insensitive, word-boundary.
    # \\b keeps short keywords like "box" from matching inside "boxer"; the
    # 'u' flag makes \\b Unicode-aware for PL diacritics (ąćęłńóśźż). Entries
    # with whole_word=True enforce BOTH boundaries (\\b{kw}\\b) for known
    # ambiguous stems (e.g. PL 'ser' must not match 'serwer').
    haystack = f'{name or ""} {code or ""}'.lower()
    for entry in KEYWORD_EMOJI_MAP:
        suffix = r'\b' if entry.whole_word else r''
        for kw in entry.keywords:
            if re.search(rf'\b{kw}{suffix}', haystack, flags=re.UNICODE):
                return entry.emoji, 2

    # Layer 3: vertical default.
    if context_tag and context_tag in VERTICAL_DEFAULT_EMOJI:
        return VERTICAL_DEFAULT_EMOJI[context_tag], 3

    # Layer 4: last resort.
    return LAST_RESORT_EMOJI, 4
