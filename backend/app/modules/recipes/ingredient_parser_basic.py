"""Basic (non-LLM) ingredient parser — regex fallback."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_VALID_UNITS: frozenset[str] = frozenset(
    [
        # Metric weight/volume
        'g',
        'kg',
        'mg',
        'ml',
        'l',
        'dl',
        'cl',
        # Count
        'pcs',
        'pack',
        # Culinary
        'cup',
        'cups',
        'tablespoon',
        'tablespoons',
        'tbsp',
        'teaspoon',
        'teaspoons',
        'tsp',
        'pinch',
        'clove',
        'cloves',
        # Imperial
        'oz',
        'lb',
        'lbs',
    ]
)


@dataclass
class ParsedIngredient:
    name: str
    quantity: Decimal
    unit_symbol: str | None
    group_name: str | None = None
    original_text: str | None = None
    original_quantity: Decimal | None = None
    original_unit_text: str | None = None
    unit_display: str | None = None


_FRACTION_MAP: dict[str, str] = {
    '½': '0.5',
    '⅓': '0.333',
    '¼': '0.25',
    '¾': '0.75',
    '⅔': '0.667',
}

_LEADING_NUM_RE = re.compile(r'^(\d+(?:[.,]\d+)?)\s*')
_DASH_NOTE_RE = re.compile(r'\s+[-–—]\s+')


def _parse_single_basic(text: str) -> ParsedIngredient:
    rem = text.strip()
    qty = Decimal('1')
    unit_symbol: str | None = None
    original_unit_text: str | None = None
    has_number = False

    for ch, val in _FRACTION_MAP.items():
        if rem.startswith(ch):
            qty = Decimal(val)
            rem = rem[len(ch) :].strip()
            has_number = True
            break
    else:
        m = _LEADING_NUM_RE.match(rem)
        if m:
            try:
                qty = Decimal(m.group(1).replace(',', '.'))
            except InvalidOperation:
                pass
            else:
                rem = rem[m.end() :].strip()
                has_number = True

    # Strip trailing " - note" BEFORE unit detection so a name followed by a
    # dash-note (e.g. '3 eggs - large') is not mistaken for an unrecognized unit.
    m = _DASH_NOTE_RE.search(rem)
    if m:
        rem = rem[: m.start()].strip()

    words = rem.split()
    if words and words[0].lower().rstrip('.,') in _VALID_UNITS:
        unit_symbol = words[0].lower().rstrip('.,')
        rem = ' '.join(words[1:]).strip()
    elif has_number and len(words) >= 2:
        # Unrecognized unit token right after the quantity (e.g. 'łyżka',
        # 'szklanka'): preserve it so downstream normalization/LLM can recover
        # the original unit. The token is NOT consumed from the name — a regex
        # parser cannot reliably tell a unit ('łyżka') from a modifier ('large'),
        # so keeping it avoids data loss.
        original_unit_text = words[0]

    return ParsedIngredient(
        name=rem if rem else text.strip(),
        quantity=qty,
        unit_symbol=unit_symbol,
        original_unit_text=original_unit_text,
    )


def parse_ingredients_basic(lines: list[str]) -> list[ParsedIngredient]:
    return [_parse_single_basic(line) for line in lines if line.strip()]
