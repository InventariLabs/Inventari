"""Regression measurement for ingredient → catalogue matching.

``ingredient_matching_corpus.json`` is not an invented example set: the
catalogue is every product name carrying positive stock in the development
database, and the ingredient names are every ingredient of the recipes
stored alongside it. The expected column is hand-written and is the
specification — the misses matter more than the hits, because the first
"let's make it a little more forgiving" patch would quietly bring them back.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from uuid import UUID, uuid5

import pytest
from anyascii import anyascii

from app.modules.recipes._ingredient_matching import (
    head_token,
    match_templates,
    matching_key,
    narrowing_fragment,
)

CORPUS = json.loads(
    (pathlib.Path(__file__).parent / 'ingredient_matching_corpus.json').read_text(
        encoding='utf-8'
    )
)

_NAMESPACE = UUID('00000000-0000-0000-0000-0000000c0de0')


@dataclass(frozen=True)
class FakeTemplate:
    id: UUID
    name: str


def _catalog() -> list[FakeTemplate]:
    return [
        FakeTemplate(id=uuid5(_NAMESPACE, name), name=name)
        for name in CORPUS['catalog']
    ]


def _matched_names(ingredient_name: str) -> list[str]:
    return [m.template_name for m in match_templates(ingredient_name, _catalog())]


@pytest.mark.parametrize(
    ('ingredient', 'expected'),
    [(entry['name'], entry['expected']) for entry in CORPUS['ingredients']],
    ids=[entry['name'] for entry in CORPUS['ingredients']],
)
def test_match_templates_against_real_catalog(
    ingredient: str, expected: list[str]
) -> None:
    assert sorted(_matched_names(ingredient)) == sorted(expected)


def test_match_rate_over_the_real_recipe_set() -> None:
    """Guard the headline number, not just the individual rows.

    Counted over ingredient *rows* (a name repeated in five recipes counts
    five times), which is what a user experiences. Substring search scored
    0 of 53 on this data.
    """
    total = sum(entry['occurrences'] for entry in CORPUS['ingredients'])
    matched = sum(
        entry['occurrences']
        for entry in CORPUS['ingredients']
        if match_templates(entry['name'], _catalog())
    )
    assert total == 53
    assert matched >= 25


@pytest.mark.parametrize(
    ('ingredient', 'forbidden'),
    [
        ('Olej', 'Tunczyk w oleju'),
        ('Włoszczyzna', 'Orzechy wloskie'),
        ('Bazylia świeża', 'Bazylia suszona'),
        ('Oliwki kalamata', 'Oliwa z oliwek extra virgin'),
        ('Biała kiełbasa', 'Fasola biala w puszce'),
        ('Mąka żytnia typ 720', 'Maka pszenna typ 550'),
    ],
    ids=[
        'qualifier-after-preposition-is-not-the-goods',
        'shared-prefix-is-not-a-shared-stem',
        'second-token-must-land',
        'olives-are-not-olive-oil',
        'white-sausage-is-not-white-beans',
        'rye-is-not-wheat',
    ],
)
def test_named_pairs_that_must_not_match(ingredient: str, forbidden: str) -> None:
    assert forbidden not in _matched_names(ingredient)


def test_inflected_qualifier_still_lands() -> None:
    """ "z puszki" and "w puszce" are the same can."""
    assert _matched_names('Ciecierzyca z puszki') == ['Ciecierzyca w puszce']


def test_outright_match_hides_a_mere_mention() -> None:
    catalog = [
        FakeTemplate(id=uuid5(_NAMESPACE, 'a'), name='Makaron spaghetti 500g'),
        FakeTemplate(id=uuid5(_NAMESPACE, 'b'), name='Spaghetti pelne ziarno'),
    ]
    matches = match_templates('Spaghetti', catalog)
    assert [m.template_name for m in matches] == ['Spaghetti pelne ziarno']
    assert matches[0].head_match is True


def test_mention_survives_when_nothing_is_named_outright() -> None:
    matches = match_templates('Spaghetti', _catalog())
    assert [m.template_name for m in matches] == ['Makaron spaghetti 500g']
    assert matches[0].head_match is False


def test_least_qualified_name_comes_first() -> None:
    catalog = [
        FakeTemplate(id=uuid5(_NAMESPACE, 'a'), name='Cukier trzcinowy nierafinowany'),
        FakeTemplate(id=uuid5(_NAMESPACE, 'b'), name='Cukier'),
    ]
    assert [m.template_name for m in match_templates('Cukier', catalog)] == [
        'Cukier',
        'Cukier trzcinowy nierafinowany',
    ]


@pytest.mark.parametrize(
    'name',
    ['', '   ', '2 x 1/2', 'z do na', '18%'],
    ids=['empty', 'blank', 'digits', 'stopwords', 'percent'],
)
def test_names_that_identify_nothing_have_no_head(name: str) -> None:
    assert head_token(name) is None
    assert narrowing_fragment(name) is None
    assert match_templates(name, _catalog()) == []


@dataclass(frozen=True)
class FakeIngredient:
    name: str
    ingredient_group_name: str | None = None


class TestMatchingKey:
    """The key is derived on every read, so nothing has to be re-saved."""

    def test_falls_back_to_the_ingredient_name(self) -> None:
        """The ordinary case: typed by hand, no template, no group name."""
        assert (
            matching_key(FakeIngredient(name='Ciecierzyca z puszki'))
            == 'Ciecierzyca z puszki'
        )

    def test_explicit_group_name_wins(self) -> None:
        """The URL import sets it deliberately; it must not be second-guessed."""
        ingredient = FakeIngredient(
            name='Ciecierzyca z puszki', ingredient_group_name='ciecierzyca'
        )
        assert matching_key(ingredient) == 'ciecierzyca'

    def test_blank_group_name_does_not_shadow_the_name(self) -> None:
        ingredient = FakeIngredient(name='Sól', ingredient_group_name='')
        assert matching_key(ingredient) == 'Sól'

    def test_group_name_of_pure_noise_falls_through_to_the_name(self) -> None:
        ingredient = FakeIngredient(name='Sól', ingredient_group_name='2 x')
        assert matching_key(ingredient) == 'Sól'

    @pytest.mark.parametrize('name', ['', '  ', '1/2', 'z do na'])
    def test_a_name_identifying_nothing_has_no_key(self, name: str) -> None:
        """Unknown means unnameable — not 'we have none of it'."""
        assert matching_key(FakeIngredient(name=name)) is None


def test_narrowing_fragment_is_the_weakest_necessary_condition() -> None:
    """Whatever SQL narrows by must appear in every name the rules accept.

    Otherwise the batch query drops candidates before the rules ever see
    them and the matcher silently gets worse the larger the catalogue.
    """
    for entry in CORPUS['ingredients']:
        fragment = narrowing_fragment(entry['name'])
        for name in entry['expected']:
            assert fragment is not None
            assert fragment in anyascii(name).lower()
