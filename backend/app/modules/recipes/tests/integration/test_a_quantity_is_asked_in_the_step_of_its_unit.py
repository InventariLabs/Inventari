"""What the app asks a person to buy or pick is stated in whole steps of its
unit, and only quantities that share a measure are added together.

Two defects met in one place. The shopping list aggregated by product alone,
so 500 g of flour and 2 packs of flour became "502" in whichever unit came
first — a number nobody can shop for. And every computed quantity was rounded
to a hard three decimal places, so a recipe scaled down asked for 0.333 of a
piece, which is not a thing anyone can take off a shelf.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

PLAN_URL = '/api/v1/recipes/meal-plans'
RECIPE_URL = '/api/v1/recipes'


def _uom_id(db: Session, symbol: str) -> str:
    row = db.execute(
        text('SELECT id FROM uoms WHERE symbol = :s'), {'s': symbol}
    ).fetchone()
    assert row is not None, f'the seed has no {symbol}'
    return str(row[0])


def _recipe(
    client: TestClient,
    auth_headers: dict[str, str],
    *,
    name: str,
    servings: int,
    ingredient: str,
    quantity: str,
    uom_id: str,
) -> str:
    r = client.post(
        RECIPE_URL,
        json={
            'name': name,
            'servings': servings,
            'ingredients': [
                {
                    'name': ingredient,
                    'quantity': quantity,
                    'uom_id': uom_id,
                    'is_optional': False,
                }
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code in (200, 201), r.text
    return str(r.json()['id'])


def _plan_of(
    client: TestClient, auth_headers: dict[str, str], recipe_ids: list[str]
) -> dict[str, Any]:
    """One plan, one lunch slot per recipe, generated straight away."""
    today = date.today()
    plan_id = client.post(
        PLAN_URL,
        json={
            'start_date': today.isoformat(),
            'end_date': (today + timedelta(days=6)).isoformat(),
            'enabled_slots': ['LUNCH'],
            'default_servings': 1,
        },
        headers=auth_headers,
    ).json()['id']
    for order, recipe_id in enumerate(recipe_ids):
        client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': (today + timedelta(days=order)).isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
                'servings': 1,
            },
            headers=auth_headers,
        )
    r = client.post(
        f'{PLAN_URL}/{plan_id}/generate-shopping-list', headers=auth_headers
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


@pytest.mark.integration
class TestOnlyWhatSharesAMeasureIsAddedUp:
    def test_grams_and_pieces_of_one_product_stay_two_lines(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """Weight and count do not meet, so the list keeps them apart.

        They used to be added as bare numbers: 500 g plus 2 pcs came out as
        502 of whichever unit the first recipe happened to name.
        """
        name = f'Flour {uuid.uuid4().hex[:6]}'
        result = _plan_of(
            client,
            auth_headers,
            [
                _recipe(
                    client,
                    auth_headers,
                    name='Weighed dish',
                    servings=1,
                    ingredient=name,
                    quantity='500',
                    uom_id=_uom_id(db_session, 'g'),
                ),
                _recipe(
                    client,
                    auth_headers,
                    name='Counted dish',
                    servings=1,
                    ingredient=name,
                    quantity='2',
                    uom_id=_uom_id(db_session, 'pcs'),
                ),
            ],
        )

        lines = {
            item['uom_symbol']: item['quantity']
            for item in result['items']
            if item['name'] == name
        }
        assert {sym: Decimal(str(qty)) for sym, qty in lines.items()} == {
            'g': Decimal('500'),
            'pcs': Decimal('2'),
        }
        assert 502 not in lines.values()

    def test_grams_and_kilograms_of_one_product_buy_it_once(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """Both measure weight, so they are one line — converted, not summed."""
        name = f'Sugar {uuid.uuid4().hex[:6]}'
        result = _plan_of(
            client,
            auth_headers,
            [
                _recipe(
                    client,
                    auth_headers,
                    name='In grams',
                    servings=1,
                    ingredient=name,
                    quantity='500',
                    uom_id=_uom_id(db_session, 'g'),
                ),
                _recipe(
                    client,
                    auth_headers,
                    name='In kilograms',
                    servings=1,
                    ingredient=name,
                    quantity='0.5',
                    uom_id=_uom_id(db_session, 'kg'),
                ),
            ],
        )

        lines = [item for item in result['items'] if item['name'] == name]
        assert len(lines) == 1
        # One kilogram of it, said in whichever unit came first.
        assert (
            lines[0]['uom_symbol'],
            Decimal(str(lines[0]['quantity'])),
        ) in {
            ('g', Decimal('1000')),
            ('kg', Decimal('1')),
        }


@pytest.mark.integration
class TestARequirementTakesTheStepOfItsUnit:
    def test_a_third_of_a_piece_is_asked_for_as_one(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """A recipe for three, cooked for one, still needs a whole egg.

        ``pcs`` is counted in ones — that is what ``uom.rounding`` says — so
        the checklist may not ask for 0.333 of one.
        """
        recipe_id = _recipe(
            client,
            auth_headers,
            name='Omelette for three',
            servings=3,
            ingredient=f'Egg {uuid.uuid4().hex[:6]}',
            quantity='1',
            uom_id=_uom_id(db_session, 'pcs'),
        )

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        item = r.json()['items_to_pick'][0]

        assert item['uom_symbol'] == 'pcs'
        assert Decimal(str(item['quantity_to_pick'])) == Decimal('1')

    def test_a_third_of_a_gram_still_reads_in_grams(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """A unit counted in thousandths keeps them — and rounds up.

        Not a neutrality control: a third of a gram is 0.3333…, and the
        assertion below is what CEILING makes of it. Nearest-step rounding
        would say 0.333 here, so this guards the direction as much as the
        step.
        """
        recipe_id = _recipe(
            client,
            auth_headers,
            name='Sauce for three',
            servings=3,
            ingredient=f'Salt {uuid.uuid4().hex[:6]}',
            quantity='1',
            uom_id=_uom_id(db_session, 'g'),
        )

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        item = r.json()['items_to_pick'][0]

        assert item['uom_symbol'] == 'g'
        assert Decimal(str(item['quantity_to_pick'])) == Decimal('0.334')

    def test_an_empty_pantry_still_asks_for_a_whole_piece(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """The step comes from the unit, not from what is on the shelf.

        The stock context returned early — with no units at all — when the
        catalogue matched nothing, so the requirement fell back to the
        quantity columns' own scale and the screen asked for 0.334 of an
        egg. An empty pantry is exactly when a person reads that screen.
        """
        recipe_id = _recipe(
            client,
            auth_headers,
            name='Omelette nobody has stock for',
            servings=3,
            ingredient=f'Nonesuch {uuid.uuid4().hex[:8]}',
            quantity='1',
            uom_id=_uom_id(db_session, 'pcs'),
        )

        r = client.get(
            f'{RECIPE_URL}/{recipe_id}/availability',
            params={'servings': 1},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        ingredient = r.json()['ingredients'][0]

        assert ingredient['required_uom'] == 'pcs'
        assert Decimal(str(ingredient['required_quantity'])) == Decimal('1')

    def test_a_half_a_piece_says_what_the_whole_was_rounded_from(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """The card can explain the 1 where the recipe says ½.

        Rounding a requirement up to its unit's step is deliberate — part of
        a carton is a carton — but the screen showed only the rounded number,
        so the half someone had just typed looked like it never saved.
        """
        recipe_id = _recipe(
            client,
            auth_headers,
            name='Milk by the carton',
            servings=1,
            ingredient=f'Milk {uuid.uuid4().hex[:6]}',
            quantity='0.5',
            uom_id=_uom_id(db_session, 'pcs'),
        )

        r = client.get(
            f'{RECIPE_URL}/{recipe_id}/availability',
            params={'servings': 1},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        ingredient = r.json()['ingredients'][0]

        assert Decimal(str(ingredient['required_quantity'])) == Decimal('1')
        assert Decimal(str(ingredient['required_quantity_unrounded'])) == Decimal('0.5')

    def test_a_requirement_already_on_its_step_carries_no_rounding(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """Nothing was rounded away, so there is nothing to explain.

        The companion of the test above: a field that always carried the
        pre-round number would put "rounded up from 2" on every whole row.
        """
        recipe_id = _recipe(
            client,
            auth_headers,
            name='Two cartons',
            servings=1,
            ingredient=f'Milk {uuid.uuid4().hex[:6]}',
            quantity='2',
            uom_id=_uom_id(db_session, 'pcs'),
        )

        r = client.get(
            f'{RECIPE_URL}/{recipe_id}/availability',
            params={'servings': 1},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        ingredient = r.json()['ingredients'][0]

        assert Decimal(str(ingredient['required_quantity'])) == Decimal('2')
        assert ingredient['required_quantity_unrounded'] is None
