"""Every allergen keyword is matched against a normalized name, so it must
already be in that form; a keyword with a diacritic or capital can never match.
"""

from __future__ import annotations

import pytest

from app.modules.recipes._allergens import (
    _ALLERGEN_NAME_MAP,
    infer_allergens,
    normalize_name,
)


@pytest.mark.parametrize('keyword', sorted(_ALLERGEN_NAME_MAP))
def test_a_keyword_equals_its_own_normalized_form(keyword: str) -> None:
    assert keyword == normalize_name(keyword)


@pytest.mark.parametrize(
    'name', ['Pstrąg', 'Pstrąg wędzony', 'Filet z pstrąga', 'Trout']
)
def test_trout_reads_fish(name: str) -> None:
    assert infer_allergens(name) == ['fish']
