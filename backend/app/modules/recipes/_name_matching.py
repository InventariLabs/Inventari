"""Canonical ASCII folding for ingredient names.

Two shapes are needed and they are not interchangeable:

``normalize_name`` is what gets persisted in
``IngredientNutritionDefault.name_normalized`` and matched with ``LIKE`` in
search, so token order carries meaning.

``match_key`` decides whether two ingredients are *the same ingredient* when
shopping lists and meal plans are merged, so token order must not matter —
"mąka pszenna" and "pszenna mąka" have to collapse onto one entry.

Both go through the same transliteration, which is the point of this module:
the two shapes share one implementation, which must not fall back to a
diacritics-preserving path when an optional dependency is missing: that would
write ``bakłażan`` next to ``baklazan`` and hand the cleanup to
``deduplicate_defaults``.
"""

from __future__ import annotations

import unicodedata

from anyascii import anyascii

__all__ = ['match_key', 'normalize_name', 'shows_a_character']

#: Letters and symbols that print as empty space although Unicode files them
#: with the visible ones: the Braille blank and the Hangul fillers.
_BLANK_GLYPHS = frozenset('\u2800\u115f\u1160\u3164\uffa0')


def normalize_name(name: str) -> str:
    """Return *name* transliterated to ASCII, lowercased and stripped.

    Stripped again after the fold: a zero-width space or a no-break space
    outside a name becomes a plain space only once transliterated.
    """
    return anyascii(name.strip()).strip().lower()


def match_key(name: str) -> str:
    """Return an order-insensitive key: :func:`normalize_name`, tokens sorted."""
    return ' '.join(sorted(normalize_name(name).split()))


def shows_a_character(name: str) -> bool:
    """True when *name* holds a letter, digit, mark, punctuation or symbol.

    A name whose key folds to nothing is either invisible (spaces, zero-width
    characters, a BOM) or written only in characters the ASCII fold has no
    spelling for: an Arabic word, a rare CJK ideograph. The two are refused
    with different sentences, because only the first is blank to its reader.
    """
    return any(
        unicodedata.category(char)[0] in 'LMNPS' and char not in _BLANK_GLYPHS
        for char in name
    )
