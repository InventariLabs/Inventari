"""A pasta named by its shape, not by the word "pasta", still carries gluten.

The inference read "Fusilli Pasta" but not "Spaghetti 500g", so the demo's
spaghetti recipe reached a visitor with no allergen on its card.
"""

from __future__ import annotations

import pytest

from app.modules.recipes._allergens import infer_allergens


@pytest.mark.parametrize(
    'name',
    [
        'Spaghetti 500g',
        'Penne',
        'Fusilli',
        'Tagliatelle',
        'Lasagne sheets',
        'Egg noodles',
    ],
)
def test_a_pasta_shape_carries_gluten(name: str) -> None:
    assert 'gluten' in infer_allergens(name)
