"""Integration tests: putting several recipes on one shopping list.

The shopping list offers "add from recipes" for a selection of recipes. It
must reach a route that exists, reuse the same stock check as the single
recipe path, and merge what two recipes ask for instead of listing it twice.
"""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from tests.integration._shelf import put_on_shelf, run_in_async_session

RECIPE_URL = '/api/v1/recipes'
ADD_URL = f'{RECIPE_URL}/shopping-list/add-from-recipes'

pytestmark = pytest.mark.integration


def _shelve_grams(
    db: Session,
    engine: AsyncEngine,
    user: User,
    location: StorageLocation,
    name: str,
    quantity: Decimal,
) -> ProductTemplate:
    """A product of *name*, measured in grams, with *quantity* on the shelf."""
    grams = db.execute(text("SELECT id FROM uoms WHERE symbol = 'g'")).fetchone()
    assert grams is not None
    template = ProductTemplate(
        id=uuid.uuid4(),
        organization_id=user.organization_id,
        name=name,
        uom_id=grams[0],
    )
    db.add(template)
    db.commit()

    async def _put(session: AsyncSession) -> None:
        await put_on_shelf(session, user, template, location.id, quantity)

    run_in_async_session(engine, _put)
    db.expire_all()
    return template


def _uom_id(db: Session, symbol: str) -> uuid.UUID:
    row = db.execute(
        text('SELECT id FROM uoms WHERE symbol = :s'), {'s': symbol}
    ).fetchone()
    assert row is not None, f'UOM {symbol!r} is not seeded'
    return uuid.UUID(str(row[0]))


def _recipe(
    client: TestClient,
    auth_headers: dict[str, str],
    name: str,
    ingredients: list[dict[str, Any]],
) -> str:
    response = client.post(
        RECIPE_URL,
        json={
            'name': name,
            'servings': 1,
            'instructions': 'Mix.',
            'ingredients': ingredients,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()['id'])


class TestAddFromRecipes:
    def test_two_recipes_land_on_one_list_with_shared_goods_merged(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        grams = str(_uom_id(db_session, 'g'))
        bread = _recipe(
            client,
            auth_headers,
            'Bread',
            [
                {'name': 'Flour', 'quantity': '500', 'uom_id': grams},
                {'name': 'Salt', 'quantity': '10', 'uom_id': grams},
            ],
        )
        cake = _recipe(
            client,
            auth_headers,
            'Cake',
            [
                {'name': 'Flour', 'quantity': '300', 'uom_id': grams},
                {'name': 'Sugar', 'quantity': '200', 'uom_id': grams},
            ],
        )

        response = client.post(
            ADD_URL,
            json={'recipe_ids': [bread, cake], 'servings': 1},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # Flour asked for twice is bought once.
        assert body['added_count'] == 3

        items = client.get(
            f'/api/v1/shopping-lists/{body["shopping_list_id"]}/items',
            headers=auth_headers,
        )
        assert items.status_code == 200
        by_name = {
            i['name']: Decimal(str(i['quantity'])) for i in items.json()['items']
        }
        assert set(by_name) == {'Flour', 'Salt', 'Sugar'}
        assert by_name['Flour'] == Decimal('800')

    def test_unknown_recipe_is_rejected(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        response = client.post(
            ADD_URL,
            json={'recipe_ids': [str(uuid.uuid4())], 'servings': 1},
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_a_scaled_quantity_past_the_column_ceiling_is_refused_with_a_sentence(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        # The row's column is numeric(12, 3): a scaled quantity past its
        # largest value is refused where the row is built, with the ceiling
        # named — not with the driver's overflow on the INSERT.
        grams = str(_uom_id(db_session, 'g'))
        bread = _recipe(
            client,
            auth_headers,
            'Bread',
            [{'name': 'Flour', 'quantity': '500', 'uom_id': grams}],
        )

        response = client.post(
            ADD_URL,
            json={'recipe_ids': [bread], 'servings': 3000000},
            headers=auth_headers,
        )

        assert response.status_code == 400, response.text
        assert '999999999.999' in response.text

    def test_empty_selection_is_rejected(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        response = client.post(
            ADD_URL, json={'recipe_ids': [], 'servings': 1}, headers=auth_headers
        )
        assert response.status_code == 422


class TestFractionalQuantitiesKeepTheirUnit:
    def test_half_a_gram_of_saffron_is_not_rounded_to_one(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        """The rounding reads the unit's step, not whole pieces.

        0.5 g of saffron used to become "1 g" — a ten-times over-buy that
        the unit's rounding (0.001 for a gram) never asked for. Countable
        units keep their ceiling: 0.3 pcs is still 1 pc to buy.
        """
        grams = str(_uom_id(db_session, 'g'))
        pcs = str(_uom_id(db_session, 'pcs'))
        saffron = _recipe(
            client,
            auth_headers,
            'Saffron rice',
            [{'name': 'Saffron', 'quantity': '0.5', 'uom_id': grams}],
        )
        buns = _recipe(
            client,
            auth_headers,
            'Buns',
            [{'name': 'Eggs', 'quantity': '0.3', 'uom_id': pcs}],
        )

        response = client.post(
            ADD_URL,
            json={'recipe_ids': [saffron, buns], 'servings': 1},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        list_id = response.json()['shopping_list_id']

        items = client.get(
            f'/api/v1/shopping-lists/{list_id}/items',
            headers=auth_headers,
        )
        assert items.status_code == 200
        by_name = {
            i['name']: Decimal(str(i['quantity'])) for i in items.json()['items']
        }

        # A measured unit keeps the fraction the recipe asked for.
        assert by_name['Saffron'] == Decimal('0.500')
        # A countable unit still rounds up, never under one piece.
        assert by_name['Eggs'] == Decimal('1')


class TestAQuantityThatRoundsToZeroIsSkipped:
    def test_an_unmeasurable_ingredient_does_not_fail_the_whole_list(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        """An ingredient stored as 0.000 g cannot be bought — but its line
        must not take the whole recipe's list down with it: the request
        succeeds and carries the lines that say something."""
        grams = str(_uom_id(db_session, 'g'))
        recipe = _recipe(
            client,
            auth_headers,
            'Dust',
            [
                {'name': 'Saffron dust', 'quantity': '0.0004', 'uom_id': grams},
                {'name': 'Flour', 'quantity': '500', 'uom_id': grams},
            ],
        )

        response = client.post(
            ADD_URL,
            json={'recipe_ids': [recipe], 'servings': 1},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['added_count'] == 1

        items = client.get(
            f'/api/v1/shopping-lists/{body["shopping_list_id"]}/items',
            headers=auth_headers,
        )
        assert items.status_code == 200
        assert [i['name'] for i in items.json()['items']] == ['Flour']


class TestTheListAddsTheShortfallNotTheWholeRecipe:
    """What the shelf covers is deducted from the line.

    The route put the recipe's whole requirement on the list — 500 g of
    flour over the 300 g already in the cupboard — while the meal-plan road
    had been deducting for as long as it existed.
    """

    def test_shelf_cover_is_deducted_from_the_recipe_line(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        _shelve_grams(
            db_session,
            async_engine_fixture,
            test_user,
            test_storage_location,
            'Flour',
            Decimal('300'),
        )
        grams = str(_uom_id(db_session, 'g'))
        recipe = _recipe(
            client,
            auth_headers,
            'Bread',
            [{'name': 'Flour', 'quantity': '500', 'uom_id': grams}],
        )

        response = client.post(
            ADD_URL,
            json={'recipe_ids': [recipe], 'servings': 1},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['added_count'] == 1

        items = client.get(
            f'/api/v1/shopping-lists/{body["shopping_list_id"]}/items',
            headers=auth_headers,
        )
        by_name = {
            i['name']: Decimal(str(i['quantity'])) for i in items.json()['items']
        }
        assert by_name['Flour'] == Decimal('200')


class TestAlwaysAtHomeIsHonoured:
    """A product the organization marked "Always at home" is not bought."""

    def test_an_excluded_product_is_left_off_the_list(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        from app.modules.recipes._name_matching import match_key
        from app.modules.recipes.models import ShoppingExclusion

        db_session.add(
            ShoppingExclusion(
                organization_id=test_user.organization_id,
                name='Mąka',
                name_normalized=match_key('Mąka'),
            )
        )
        db_session.commit()

        grams = str(_uom_id(db_session, 'g'))
        recipe = _recipe(
            client,
            auth_headers,
            'Bread',
            [
                {'name': 'Mąka', 'quantity': '500', 'uom_id': grams},
                {'name': 'Cukier', 'quantity': '200', 'uom_id': grams},
            ],
        )

        response = client.post(
            ADD_URL,
            json={'recipe_ids': [recipe], 'servings': 1},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['added_count'] == 1

        items = client.get(
            f'/api/v1/shopping-lists/{body["shopping_list_id"]}/items',
            headers=auth_headers,
        )
        assert [i['name'] for i in items.json()['items']] == ['Cukier']


class TestARecipeOnTheListTwice:
    """The recipe screen's "Add missing" pressed again, and a second recipe."""

    def test_the_second_run_says_the_lines_are_already_listed(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        grams = str(_uom_id(db_session, 'g'))
        bread = _recipe(
            client,
            auth_headers,
            'Bread',
            [{'name': 'Flour', 'quantity': '500', 'uom_id': grams}],
        )
        first = client.post(
            f'{RECIPE_URL}/{bread}/add-to-shopping-list',
            json={'servings': 1},
            headers=auth_headers,
        )
        assert first.status_code == 200, first.text
        assert first.json()['added_count'] == 1

        second = client.post(
            f'{RECIPE_URL}/{bread}/add-to-shopping-list',
            json={'servings': 1, 'shopping_list_id': first.json()['shopping_list_id']},
            headers=auth_headers,
        )
        assert second.status_code == 200, second.text
        body = second.json()
        # "Added 0 items" said nothing about why; the answer now carries it.
        assert body['added_count'] == 0
        assert body['already_listed_count'] == 1
        assert body['list_name']

    def test_a_second_recipe_needing_the_same_goods_tops_the_line_up(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """200 g for one recipe, then 300 g for another: the list asks 500 g.

        The line was dropped as "already listed" whatever the new recipe
        needed, so the second recipe added nothing and the list stayed short.
        """
        grams = str(_uom_id(db_session, 'g'))
        bread = _recipe(
            client,
            auth_headers,
            'Bread',
            [{'name': 'Flour', 'quantity': '200', 'uom_id': grams}],
        )
        cake = _recipe(
            client,
            auth_headers,
            'Cake',
            [{'name': 'Flour', 'quantity': '300', 'uom_id': grams}],
        )
        first = client.post(
            f'{RECIPE_URL}/{bread}/add-to-shopping-list',
            json={'servings': 1},
            headers=auth_headers,
        ).json()
        list_id = first['shopping_list_id']

        second = client.post(
            ADD_URL,
            json={'recipe_ids': [cake], 'servings': 1, 'shopping_list_id': list_id},
            headers=auth_headers,
        )

        assert second.status_code == 200, second.text
        body = second.json()
        assert (body['added_count'], body['raised_count']) == (0, 1)
        assert body['already_listed_count'] == 0
        [line] = client.get(
            f'/api/v1/shopping-lists/{list_id}/items', headers=auth_headers
        ).json()['items']
        assert Decimal(str(line['quantity'])) == Decimal('500')
        # The line says which recipes it is for, and the note went with it.
        assert line['note_data']['for_recipe'] == 'Bread, Cake'
        assert 'Bread, Cake' in line['notes']

        # Either recipe pressed again is covered: nothing is added twice.
        for recipe_id in (bread, cake):
            again = client.post(
                ADD_URL,
                json={
                    'recipe_ids': [recipe_id],
                    'servings': 1,
                    'shopping_list_id': list_id,
                },
                headers=auth_headers,
            ).json()
            assert (again['added_count'], again['raised_count']) == (0, 0)
            assert again['already_listed_count'] == 1
        [line] = client.get(
            f'/api/v1/shopping-lists/{list_id}/items', headers=auth_headers
        ).json()['items']
        assert Decimal(str(line['quantity'])) == Decimal('500')

    def test_a_recipe_after_the_goods_were_bought_adds_a_new_line(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        grams = str(_uom_id(db_session, 'g'))
        bread = _recipe(
            client,
            auth_headers,
            'Bread',
            [{'name': 'Flour', 'quantity': '200', 'uom_id': grams}],
        )
        cake = _recipe(
            client,
            auth_headers,
            'Cake',
            [{'name': 'Flour', 'quantity': '300', 'uom_id': grams}],
        )
        list_id = client.post(
            f'{RECIPE_URL}/{bread}/add-to-shopping-list',
            json={'servings': 1},
            headers=auth_headers,
        ).json()['shopping_list_id']
        list_url = f'/api/v1/shopping-lists/{list_id}'
        line = client.get(f'{list_url}/items', headers=auth_headers).json()['items'][0]
        client.patch(f'{list_url}/items/{line["id"]}/purchase', headers=auth_headers)

        body = client.post(
            ADD_URL,
            json={'recipe_ids': [cake], 'servings': 1, 'shopping_list_id': list_id},
            headers=auth_headers,
        ).json()

        assert (body['added_count'], body['raised_count']) == (1, 0)
        lines = client.get(
            f'{list_url}?purchased_filter=all', headers=auth_headers
        ).json()['items']
        assert sorted(
            (i['is_purchased'], Decimal(str(i['quantity']))) for i in lines
        ) == [
            (False, Decimal('300')),
            (True, Decimal('200')),
        ]

    @pytest.mark.parametrize('bought', [False, True])
    def test_a_press_naming_a_listed_recipe_adds_only_the_new_recipes_need(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        bought: bool,
    ) -> None:
        """Bread (200 g) listed, then Bread + Cake (300 g) pressed together.

        Both recipes need 500 g. The press carries the merge of *both*, so
        topping the line up by all of it asked for 700 g, counting Bread's
        200 g twice; the line is raised by Cake's 300 g alone. With the
        Bread line already bought, Cake's 300 g is a new line instead.
        """
        grams = str(_uom_id(db_session, 'g'))
        bread = _recipe(
            client,
            auth_headers,
            'Bread',
            [{'name': 'Flour', 'quantity': '200', 'uom_id': grams}],
        )
        cake = _recipe(
            client,
            auth_headers,
            'Cake',
            [{'name': 'Flour', 'quantity': '300', 'uom_id': grams}],
        )
        list_id = client.post(
            f'{RECIPE_URL}/{bread}/add-to-shopping-list',
            json={'servings': 1},
            headers=auth_headers,
        ).json()['shopping_list_id']
        list_url = f'/api/v1/shopping-lists/{list_id}'
        if bought:
            line = client.get(f'{list_url}/items', headers=auth_headers).json()[
                'items'
            ][0]
            client.patch(
                f'{list_url}/items/{line["id"]}/purchase', headers=auth_headers
            )

        body = client.post(
            ADD_URL,
            json={
                'recipe_ids': [bread, cake],
                'servings': 1,
                'shopping_list_id': list_id,
            },
            headers=auth_headers,
        ).json()

        assert (body['added_count'], body['raised_count']) == (
            (1, 0) if bought else (0, 1)
        )
        lines = client.get(
            f'{list_url}?purchased_filter=all', headers=auth_headers
        ).json()['items']
        assert sum(Decimal(str(i['quantity'])) for i in lines) == Decimal('500')
        open_lines = [i for i in lines if not i['is_purchased']]
        assert len(open_lines) == 1
        # The new line is for Cake only; the raised one for both.
        assert open_lines[0]['note_data']['for_recipe'] == (
            'Cake' if bought else 'Bread, Cake'
        )

    def test_the_list_it_creates_is_not_named_after_the_recipe(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """The first list became every later recipe's destination.

        Named "Bread", it then received the cake's missing goods under a name
        that said they were for bread; the recipe door's list is a shopping
        list, named as one.
        """
        grams = str(_uom_id(db_session, 'g'))
        bread = _recipe(
            client,
            auth_headers,
            'Bread',
            [{'name': 'Flour', 'quantity': '500', 'uom_id': grams}],
        )
        body = client.post(
            f'{RECIPE_URL}/{bread}/add-to-shopping-list',
            json={'servings': 1},
            headers=auth_headers,
        ).json()

        assert body['list_name'] != 'Bread'
        assert body['list_name'] == 'Shopping list'

    def test_the_line_names_its_recipe_as_data_not_as_a_sentence(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """'For recipe: Bread' was frozen in the language of whoever pressed
        the button; the recipe travels as data the list renders in the
        reader's own language."""
        grams = str(_uom_id(db_session, 'g'))
        bread = _recipe(
            client,
            auth_headers,
            'Bread',
            [{'name': 'Flour', 'quantity': '500', 'uom_id': grams}],
        )
        body = client.post(
            f'{RECIPE_URL}/{bread}/add-to-shopping-list',
            json={'servings': 1},
            headers=auth_headers,
        ).json()

        items = client.get(
            f'/api/v1/shopping-lists/{body["shopping_list_id"]}/items',
            headers=auth_headers,
        ).json()['items']
        assert items[0]['note_data'] == {
            'for_recipe': 'Bread',
            'for_recipes': ['Bread'],
        }
