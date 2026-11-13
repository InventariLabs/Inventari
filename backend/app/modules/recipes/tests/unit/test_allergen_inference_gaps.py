"""Allergen inference gaps: Polish milk adjectives, English groundnuts,
potatoes after a nut word, and seed butters.

Each case is a name the inference read wrongly: a milk or peanut allergy that
went unreported (the unsafe error), or a tree nut dropped for a potato.
"""

from __future__ import annotations

import pytest

from app.modules.recipes._allergens import infer_allergens


@pytest.mark.parametrize(
    'name', ['Czekolada mleczna', 'Napój mleczny', 'Milk chocolate']
)
def test_a_milk_adjective_reads_milk(name: str) -> None:
    assert infer_allergens(name) == ['milk']


@pytest.mark.parametrize(
    'name',
    [
        'Groundnuts',
        'Groundnut oil',
        'Ground nuts',
        'Ground nut',
        'Groundnut',
        'Ground-nut',
        'Ground-nut oil',
        'Ground-nuts',
    ],
)
def test_a_groundnut_reads_peanuts_and_not_tree_nuts(name: str) -> None:
    assert infer_allergens(name) == ['peanuts']


@pytest.mark.parametrize(
    'name', ['Orzechy ziemniaki', 'Sałatka z orzechami ziemniakami']
)
def test_a_nut_word_before_a_potato_keeps_tree_nuts_and_no_peanuts(name: str) -> None:
    assert infer_allergens(name) == ['nuts']


@pytest.mark.parametrize(
    'name',
    [
        'Orzechy ziemne',
        'Orzech ziemny',
        'Masło z orzechów ziemnych',
        'Orzechy ziemnych',
        'Orzechy ziemnymi',
    ],
)
def test_every_polish_peanut_form_still_reads_peanuts_only(name: str) -> None:
    assert infer_allergens(name) == ['peanuts']


def test_a_sunflower_seed_butter_is_no_dairy() -> None:
    assert infer_allergens('Sunflower seed butter') == []
    assert infer_allergens('Sunflower seed butter cookies') == ['milk']


def test_a_hyphenated_sunflower_seed_butter_is_no_dairy() -> None:
    assert infer_allergens('Sunflower-seed butter') == []
    assert infer_allergens('Sunflower-seed-butter') == []
    assert infer_allergens('Sunflower-seed butter cookies') == ['milk']
