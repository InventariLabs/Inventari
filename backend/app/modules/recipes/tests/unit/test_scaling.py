"""One definition of the recipe multiplier.

The rule used to live in every consumer at once — four spellings of
``requested / recipe.servings``, two of them on ``float``, one guarded against
a recipe of zero servings and the rest dividing by whatever the recipe said.
A recipe of no servings is nonsense, but it is the kind of nonsense that
should cost a multiplier of one rather than a 500 on somebody's shopping
list. These tests are the one place that decides what a multiplier is.
"""

from decimal import Decimal

from app.modules.recipes._scaling import resolve_multiplier


def test_servings_without_a_scale_divide_the_request() -> None:
    assert resolve_multiplier(4, 8, None) == Decimal('2')


def test_a_scale_without_servings_is_the_multiplier() -> None:
    assert resolve_multiplier(4, None, Decimal('1.4')) == Decimal('1.4')


def test_a_scale_beats_servings() -> None:
    assert resolve_multiplier(4, 8, Decimal('1.4')) == Decimal('1.4')


def test_a_recipe_of_no_servings_does_not_divide_by_zero() -> None:
    assert resolve_multiplier(0, 4, None) == Decimal('4')
    assert resolve_multiplier(0, None, None) == Decimal('0')


def test_a_fractional_multiplier_stays_exact() -> None:
    multiplier = resolve_multiplier(5, 7, None)
    assert multiplier == Decimal('1.4')
    assert multiplier != Decimal('1.3999999')
    assert resolve_multiplier(5, 7, None) * Decimal('10') == Decimal('14.0')
