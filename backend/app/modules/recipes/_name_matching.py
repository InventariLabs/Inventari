"""Canonical ASCII folding for ingredient names.

Two shapes are needed and they are not interchangeable:

``normalize_name`` is what gets persisted in
``IngredientNutritionDefault.name_normalized`` and matched with ``LIKE`` in
search, so token order carries meaning.

``match_key`` decides whether two ingredients are *the same ingredient* when
shopping lists and meal plans are merged, so token order must not matter —
"mąka pszenna" and "pszenna mąka" have to collapse onto one entry.

Both go through the same transliteration, which is the point of this module:
the two shapes used to be three separate implementations, and one of them fell
back to a diacritics-preserving path whenever its optional dependency was
missing — enough to write ``bakłażan`` next to ``baklazan`` and hand the
cleanup to ``deduplicate_defaults``.
"""

from __future__ import annotations

from anyascii import anyascii


def normalize_name(name: str) -> str:
    """Return *name* transliterated to ASCII, lowercased and stripped."""
    return anyascii(name.strip()).lower()


def match_key(name: str) -> str:
    """Return an order-insensitive key: :func:`normalize_name`, tokens sorted."""
    return ' '.join(sorted(normalize_name(name).split()))
