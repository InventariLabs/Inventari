"""The ``scale`` input on the recipe doors: a multiplier stated directly.

``servings`` rescales a recipe to a number of servings; ``scale`` says how
much of the recipe to cook without caring what one serving is. Every door
that takes one must agree: scale two on a four-serving recipe lands where
servings eight does, a fractional scale travels through the quantity math
exactly, an absurd one is refused, and when both arrive scale wins.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.product_template import ProductTemplate
from app.models.user import User

RECIPE_URL = '/api/v1/recipes'

pytestmark = pytest.mark.integration


def _uom_id(db: Session, symbol: str) -> str:
    row = db.execute(
        text('SELECT id FROM uoms WHERE symbol = :s'), {'s': symbol}
    ).fetchone()
    assert row is not None, f'UOM {symbol!r} is not seeded'
    return str(row[0])


def _recipe(
    client: TestClient,
    auth_headers: dict[str, str],
    *,
    servings: int = 4,
    quantity: str = '200',
    uom_id: str | None = None,
    template_id: str | None = None,
    name: str = 'Scaler Soup',
) -> str:
    """A recipe asking for ``quantity`` g of flour across ``servings``."""
    ingredient: dict[str, Any] = {
        'name': 'Flour',
        'quantity': quantity,
        'is_optional': False,
    }
    if uom_id:
        ingredient['uom_id'] = uom_id
    if template_id:
        ingredient['template_id'] = template_id
    response = client.post(
        RECIPE_URL,
        json={'name': name, 'servings': servings, 'ingredients': [ingredient]},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()['id'])


def _nutrition_template(
    db: Session, org_id: uuid.UUID | None, name: str
) -> ProductTemplate:
    assert org_id is not None, 'the test user has no organization'
    template = ProductTemplate(
        id=uuid.uuid4(),
        organization_id=org_id,
        name=name,
        meta_data={
            'nutrition': {
                'calories_kcal': 350.0,
                'protein_g': 12.0,
                'fat_g': 5.0,
                'carbs_g': 65.0,
                'fiber_g': 2.5,
                'sugar_g': 1.0,
                'salt_g': 0.5,
            }
        },
    )
    db.add(template)
    db.flush()
    return template


class TestScaleOnAvailability:
    def test_scale_two_lands_where_the_equivalent_servings_does(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        grams = _uom_id(db_session, 'g')
        recipe_id = _recipe(client, auth_headers, uom_id=grams)

        by_scale = client.get(
            f'{RECIPE_URL}/{recipe_id}/availability?scale=2', headers=auth_headers
        )
        assert by_scale.status_code == 200, by_scale.text
        by_servings = client.get(
            f'{RECIPE_URL}/{recipe_id}/availability?servings=8', headers=auth_headers
        )
        assert by_servings.status_code == 200, by_servings.text

        scale_row = by_scale.json()['ingredients'][0]
        servings_row = by_servings.json()['ingredients'][0]
        assert scale_row['required_quantity'] == servings_row['required_quantity']
        assert scale_row['required_quantity'] == 400.0
        assert by_scale.json()['servings_requested'] == 8

    def test_a_fractional_scale_travels_through_the_math_exactly(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        grams = _uom_id(db_session, 'g')
        recipe_id = _recipe(client, auth_headers, uom_id=grams)

        r = client.get(
            f'{RECIPE_URL}/{recipe_id}/availability?scale=1.4', headers=auth_headers
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # 200 g × 1.4 = 280 g — not what any whole serving count would say
        # (four servings scaled by one and a half is 300 g, and that is the
        # nearest whole servings this factor reaches).
        assert data['ingredients'][0]['required_quantity'] == 280.0
        # The whole serving count the factor works out to, for the clients
        # that still read one: 5.6 rounds to 6.
        assert data['servings_requested'] == 6

    def test_scale_wins_when_both_parameters_arrive(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        grams = _uom_id(db_session, 'g')
        recipe_id = _recipe(client, auth_headers, uom_id=grams)

        r = client.get(
            f'{RECIPE_URL}/{recipe_id}/availability?scale=2&servings=3',
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        # Servings three would ask for 150 g; the scale asked for 400 g.
        assert r.json()['ingredients'][0]['required_quantity'] == 400.0
        assert r.json()['servings_requested'] == 8

    @pytest.mark.parametrize('bad', ['0', '-1', '101', 'abc'])
    def test_an_absurd_scale_is_refused(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        bad: str,
    ) -> None:
        grams = _uom_id(db_session, 'g')
        recipe_id = _recipe(client, auth_headers, uom_id=grams)

        r = client.get(
            f'{RECIPE_URL}/{recipe_id}/availability?scale={bad}', headers=auth_headers
        )
        assert r.status_code == 422, r.text


class TestScaleOnNutrition:
    def test_scale_two_totals_where_the_equivalent_servings_does(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        grams = _uom_id(db_session, 'g')
        template = _nutrition_template(
            db_session, test_user.organization_id, 'Scaler Rice'
        )
        recipe_id = _recipe(
            client,
            auth_headers,
            servings=4,
            quantity='100',
            uom_id=grams,
            template_id=str(template.id),
        )

        by_scale = client.get(
            f'{RECIPE_URL}/{recipe_id}/nutrition?scale=2', headers=auth_headers
        )
        assert by_scale.status_code == 200, by_scale.text
        by_servings = client.get(
            f'{RECIPE_URL}/{recipe_id}/nutrition?servings=8', headers=auth_headers
        )
        assert by_servings.status_code == 200, by_servings.text

        assert (
            by_scale.json()['total']['calories_kcal']
            == by_servings.json()['total']['calories_kcal']
        )
        assert by_scale.json()['servings'] == 8

    def test_a_fractional_scale_scales_the_ingredients_and_reports_whole_servings(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        grams = _uom_id(db_session, 'g')
        template = _nutrition_template(
            db_session, test_user.organization_id, 'Scaler Rice'
        )
        recipe_id = _recipe(
            client,
            auth_headers,
            servings=4,
            quantity='100',
            uom_id=grams,
            template_id=str(template.id),
        )

        r = client.get(
            f'{RECIPE_URL}/{recipe_id}/nutrition?scale=1.4', headers=auth_headers
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data['ingredients'][0]['quantity'] == pytest.approx(140.0)
        assert data['servings'] == 6

    def test_scale_wins_when_both_parameters_arrive(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        grams = _uom_id(db_session, 'g')
        template = _nutrition_template(
            db_session, test_user.organization_id, 'Scaler Rice'
        )
        recipe_id = _recipe(
            client,
            auth_headers,
            servings=4,
            quantity='100',
            uom_id=grams,
            template_id=str(template.id),
        )

        r = client.get(
            f'{RECIPE_URL}/{recipe_id}/nutrition?scale=2&servings=3',
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        by_scale = client.get(
            f'{RECIPE_URL}/{recipe_id}/nutrition?scale=2', headers=auth_headers
        )
        assert by_scale.status_code == 200, by_scale.text
        # Servings three would report the recipe at three quarters; the
        # scale reported it at twice what is written.
        assert r.json()['total'] == by_scale.json()['total']
        assert r.json()['servings'] == 8


class TestScaleOnCost:
    def test_a_fractional_scale_scales_the_quantities(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        grams = _uom_id(db_session, 'g')
        recipe_id = _recipe(client, auth_headers, uom_id=grams)

        r = client.get(f'{RECIPE_URL}/{recipe_id}/cost?scale=1.4', headers=auth_headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data['ingredients'][0]['quantity'] == pytest.approx(280.0)
        assert data['servings'] == 6

    def test_scale_wins_when_both_parameters_arrive(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        grams = _uom_id(db_session, 'g')
        recipe_id = _recipe(client, auth_headers, uom_id=grams)

        r = client.get(
            f'{RECIPE_URL}/{recipe_id}/cost?scale=2&servings=3', headers=auth_headers
        )
        assert r.status_code == 200, r.text
        assert r.json()['ingredients'][0]['quantity'] == pytest.approx(400.0)
        assert r.json()['servings'] == 8


class TestScaleOnShoppingList:
    def test_scale_beats_servings_and_lands_on_the_list(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        grams = _uom_id(db_session, 'g')
        recipe_id = _recipe(client, auth_headers, uom_id=grams)

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/add-to-shopping-list',
            json={'servings': 3, 'scale': 2},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        list_id = r.json()['shopping_list_id']

        items = client.get(
            f'/api/v1/shopping-lists/{list_id}/items', headers=auth_headers
        )
        assert items.status_code == 200, items.text
        by_name = {
            i['name']: Decimal(str(i['quantity'])) for i in items.json()['items']
        }
        assert by_name['Flour'] == Decimal('400')

    def test_a_fractional_scale_adds_the_exact_amount(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        grams = _uom_id(db_session, 'g')
        recipe_id = _recipe(client, auth_headers, uom_id=grams)

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/add-to-shopping-list',
            json={'scale': 1.4},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        list_id = r.json()['shopping_list_id']

        items = client.get(
            f'/api/v1/shopping-lists/{list_id}/items', headers=auth_headers
        )
        assert items.status_code == 200, items.text
        by_name = {
            i['name']: Decimal(str(i['quantity'])) for i in items.json()['items']
        }
        assert by_name['Flour'] == Decimal('280')

    def test_a_scale_of_zero_is_refused(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        grams = _uom_id(db_session, 'g')
        recipe_id = _recipe(client, auth_headers, uom_id=grams)

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/add-to-shopping-list',
            json={'scale': 0},
            headers=auth_headers,
        )
        assert r.status_code == 422, r.text

    def test_scale_beats_servings_on_the_multi_recipe_door(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        grams = _uom_id(db_session, 'g')
        recipe_id = _recipe(client, auth_headers, uom_id=grams)

        r = client.post(
            f'{RECIPE_URL}/shopping-list/add-from-recipes',
            json={'recipe_ids': [recipe_id], 'servings': 3, 'scale': 2},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        list_id = r.json()['shopping_list_id']

        items = client.get(
            f'/api/v1/shopping-lists/{list_id}/items', headers=auth_headers
        )
        assert items.status_code == 200, items.text
        by_name = {
            i['name']: Decimal(str(i['quantity'])) for i in items.json()['items']
        }
        # Servings three would buy 150 g; the scale asked for 400 g — and
        # the door must not have quietly read the body as servings only.
        assert by_name['Flour'] == Decimal('400')

    def test_a_fractional_scale_buys_the_exact_amount_on_the_multi_recipe_door(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        grams = _uom_id(db_session, 'g')
        recipe_id = _recipe(client, auth_headers, uom_id=grams)

        r = client.post(
            f'{RECIPE_URL}/shopping-list/add-from-recipes',
            json={'recipe_ids': [recipe_id], 'scale': 1.4},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        list_id = r.json()['shopping_list_id']

        items = client.get(
            f'/api/v1/shopping-lists/{list_id}/items', headers=auth_headers
        )
        assert items.status_code == 200, items.text
        by_name = {
            i['name']: Decimal(str(i['quantity'])) for i in items.json()['items']
        }
        # 200 g × 1.4 = 280 g — the fraction crossed the multi-recipe door
        # untouched, not rounded onto a whole serving count (6 would say 300).
        assert by_name['Flour'] == Decimal('280')


class TestScaleOnPicking:
    def test_scale_two_starts_where_the_equivalent_servings_would(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        grams = _uom_id(db_session, 'g')
        recipe_id = _recipe(client, auth_headers, uom_id=grams)

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'scale': 2},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        data = r.json()
        # The sheet asks for 400 g, the same the equivalent servings eight
        # would — but the session keeps the recipe's own count as its
        # anchor and the stated multiplier beside it, not a folded count.
        assert data['items_to_pick'][0]['quantity_to_pick'] == pytest.approx(400.0)
        assert data['servings'] == 4
        # The column is Numeric: over JSON it reads back as a decimal string.
        assert Decimal(str(data['scale'])) == Decimal('2')

    def test_scale_wins_when_both_parameters_arrive(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        grams = _uom_id(db_session, 'g')
        recipe_id = _recipe(client, auth_headers, uom_id=grams)

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 3, 'scale': 2},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        # The session is a scale session: the multiplier is stored, and the
        # serving count it stands on is the recipe's own, not the request's.
        assert r.json()['servings'] == 4
        assert Decimal(str(r.json()['scale'])) == Decimal('2')

    def test_a_fractional_scale_travels_through_the_sheet_exactly(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        grams = _uom_id(db_session, 'g')
        recipe_id = _recipe(client, auth_headers, uom_id=grams)

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'scale': 1.4},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        data = r.json()
        # The column holds the fraction, so the sheet asks for what the
        # multiplier says — 200 g × 1.4 = 280 g, not what the nearest
        # whole serving count (6 → 300 g) would.
        assert data['items_to_pick'][0]['quantity_to_pick'] == pytest.approx(280.0)
        assert data['servings'] == 4
        assert Decimal(str(data['scale'])) == Decimal('1.4')

    def test_a_scale_of_zero_is_refused(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        grams = _uom_id(db_session, 'g')
        recipe_id = _recipe(client, auth_headers, uom_id=grams)

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'scale': 0},
            headers=auth_headers,
        )
        assert r.status_code == 422, r.text


def _send_scale(
    client: TestClient,
    auth_headers: dict[str, str],
    door: str,
    recipe_id: str,
    bad: str,
) -> Any:
    """The door's request with ``scale`` set to a raw, possibly bad value."""
    if door in ('availability', 'nutrition', 'cost'):
        return client.get(
            f'{RECIPE_URL}/{recipe_id}/{door}?scale={bad}', headers=auth_headers
        )
    value: Any = bad if bad == 'abc' else int(bad)
    if door == 'add-to-shopping-list':
        return client.post(
            f'{RECIPE_URL}/{recipe_id}/add-to-shopping-list',
            json={'scale': value},
            headers=auth_headers,
        )
    if door == 'add-from-recipes':
        return client.post(
            f'{RECIPE_URL}/shopping-list/add-from-recipes',
            json={'recipe_ids': [recipe_id], 'scale': value},
            headers=auth_headers,
        )
    return client.post(
        f'{RECIPE_URL}/{recipe_id}/picking/start',
        json={'scale': value},
        headers=auth_headers,
    )


class TestScaleBoundsDeclaredOnEveryDoor:
    """The le/gt declaration is written per door, so each door proves it.

    A recipe id nothing answers for keeps the door's own logic out of the
    way: 422 is the declaration refusing the value, 404 would be the value
    having walked straight through it into the recipe lookup.
    """

    @pytest.mark.parametrize(
        'door',
        [
            'availability',
            'nutrition',
            'cost',
            'add-to-shopping-list',
            'add-from-recipes',
            'picking-start',
        ],
    )
    @pytest.mark.parametrize('bad', ['0', '-1', '101', 'abc'])
    def test_an_out_of_range_scale_is_refused_before_the_recipe_lookup(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        door: str,
        bad: str,
    ) -> None:
        r = _send_scale(client, auth_headers, door, str(uuid.uuid4()), bad)
        assert r.status_code == 422, r.text
