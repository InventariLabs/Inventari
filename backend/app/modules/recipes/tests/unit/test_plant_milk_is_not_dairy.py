"""A plant "milk" is not dairy milk.

The inference matched "milk" as a substring, so the demo's Coconut Milk reached
a visitor's recipe card as a dairy allergen.
"""

from __future__ import annotations

import pytest

from app.modules.recipes._allergens import infer_allergens


@pytest.mark.parametrize(
    'name',
    [
        'Coconut Milk',
        'coconut cream',
        'Oat milk',
        'Rice milk',
        'Almond milk',
        'Soy milk',
        'Mleko kokosowe',
        'Mleko sojowe',
        'Kokosowe mleko',
    ],
)
def test_a_plant_milk_does_not_carry_dairy(name: str) -> None:
    assert 'milk' not in infer_allergens(name)


@pytest.mark.parametrize(
    ('name', 'allergen'),
    [
        ('Almond milk', 'nuts'),
        ('Soy milk', 'soy'),
        ('Oat milk', 'gluten'),
        ('Mleko sojowe', 'soy'),
    ],
)
def test_a_plant_milk_keeps_the_allergen_of_its_plant(name: str, allergen: str) -> None:
    assert allergen in infer_allergens(name)


@pytest.mark.parametrize(
    'name',
    ['Milk', 'Whole milk 1L', 'Mleko 3.2%', 'Cream', 'Coconut milk and butter'],
)
def test_a_dairy_milk_still_carries_milk(name: str) -> None:
    assert 'milk' in infer_allergens(name)
