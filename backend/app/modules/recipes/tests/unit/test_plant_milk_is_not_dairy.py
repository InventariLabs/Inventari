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
        'Mleko migdałowe',
        'Coconut milk, canned',
        'Coconut milk 400 ml',
        'Walnut milk',
        'Macadamia milk',
        'Pistachio milk',
        'Peanut milk',
        'Cream of coconut',
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
        ('Walnut milk', 'nuts'),
        ('Peanut milk', 'peanuts'),
        ('Mleko owsiane', 'gluten'),
    ],
)
def test_a_plant_milk_keeps_the_allergen_of_its_plant(name: str, allergen: str) -> None:
    assert allergen in infer_allergens(name)


@pytest.mark.parametrize(
    'name',
    [
        'Milk',
        'Whole milk 1L',
        'Mleko 3.2%',
        'Cream',
        'Coconut milk and butter',
        'Hazelnut cream',
        'Almond cream',
        'Rice cream',
        'Almond milk chocolate',
        'Pea cream soup',
        'Smietana migdalowa',
    ],
)
def test_a_dairy_milk_still_carries_milk(name: str) -> None:
    assert 'milk' in infer_allergens(name)


@pytest.mark.parametrize(
    'name',
    ['Płatki owsiane', 'Owsianka', 'Mleko owsiane', 'Mąka owsiana', 'Oats'],
)
def test_oat_words_carry_gluten_in_polish_and_english(name: str) -> None:
    assert 'gluten' in infer_allergens(name)


@pytest.mark.parametrize(
    'name',
    [
        'Peanut butter',
        'Cocoa butter',
        'Shea butter',
        'Masło orzechowe',
        'Masło kakaowe',
    ],
)
def test_a_butter_that_is_no_dairy_does_not_carry_milk(name: str) -> None:
    assert 'milk' not in infer_allergens(name)


def test_a_nut_butter_keeps_the_allergen_of_its_nut() -> None:
    assert 'peanuts' in infer_allergens('Peanut butter')
    assert 'peanuts' in infer_allergens('Masło orzechowe')
    assert 'nuts' in infer_allergens('Almond butter')


@pytest.mark.parametrize(
    'name',
    [
        'Masło',
        'Masło klarowane',
        'Butter',
        'Peanut butter cookies',
        'Cocoa butter and milk',
        'Masło i masło orzechowe',
    ],
)
def test_dairy_butter_still_carries_milk(name: str) -> None:
    assert 'milk' in infer_allergens(name)
