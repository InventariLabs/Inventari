"""Peanuts, tree nuts and nut butters in the allergen inference.

Polish has two common spellings for a peanut ("orzeszki ziemne" and "orzechy
ziemne"); the second contains "orzech" and used to read as a tree nut. The
English generic nut words carried no allergen because bare "nut" also sits in
coconut and donut.
"""

from __future__ import annotations

import pytest

from app.modules.recipes._allergens import infer_allergens


@pytest.mark.parametrize(
    'name',
    [
        'Orzechy ziemne',
        'Orzechy ziemne prażone',
        'Masło z orzechów ziemnych',
        'Orzech ziemny',
        'Orzeszek ziemny',
        'Orzeszki ziemne',
    ],
)
def test_a_polish_peanut_reads_peanuts_and_not_tree_nuts(name: str) -> None:
    assert infer_allergens(name) == ['peanuts']


@pytest.mark.parametrize(
    'name', ['Nuts', 'Mixed nuts', 'Nut butter', 'Pine nuts', 'Nut mix']
)
def test_a_generic_nut_word_reads_tree_nuts(name: str) -> None:
    assert 'nuts' in infer_allergens(name)


@pytest.mark.parametrize(
    'name', ['Coconut', 'Coconut milk', 'Donut', 'Doughnuts', 'Nutmeg']
)
def test_a_word_that_only_contains_nut_carries_no_nuts(name: str) -> None:
    assert 'nuts' not in infer_allergens(name)


def test_peanuts_do_not_also_read_as_tree_nuts() -> None:
    assert infer_allergens('Peanuts') == ['peanuts']
    assert infer_allergens('Peanut butter') == ['peanuts']


@pytest.mark.parametrize(
    'name',
    [
        'Walnut butter',
        'Pistachio butter',
        'Macadamia butter',
        'Coconut butter',
        'Sunflower butter',
        'Apple butter',
        'Peanut-butter',
        'Masło sezamowe',
        'Masło kokosowe',
        'Masło z orzechów nerkowca',
        'Masło z orzechów laskowych',
    ],
)
def test_a_butter_that_is_no_dairy_carries_no_milk(name: str) -> None:
    assert 'milk' not in infer_allergens(name)


@pytest.mark.parametrize(
    ('name', 'allergen'),
    [
        ('Walnut butter', 'nuts'),
        ('Peanut-butter', 'peanuts'),
        ('Masło sezamowe', 'sesame'),
        ('Masło z orzechów nerkowca', 'nuts'),
    ],
)
def test_a_non_dairy_butter_keeps_the_allergen_of_its_plant(
    name: str, allergen: str
) -> None:
    assert allergen in infer_allergens(name)


@pytest.mark.parametrize(
    'name',
    ['Peanut butter cookies', 'Peanut-butter cookies', 'Coconut butter and milk'],
)
def test_a_butter_followed_by_a_further_noun_keeps_milk(name: str) -> None:
    assert 'milk' in infer_allergens(name)
