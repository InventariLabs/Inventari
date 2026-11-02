"""Integration tests for Meal Plan shopping list generation."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
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
from tests.integration._shelf import (
    put_on_shelf,
    reserve_for_an_order,
    run_in_async_session,
)

PLAN_URL = '/api/v1/recipes/meal-plans'
RECIPE_URL = '/api/v1/recipes'


def _plan_payload(**overrides: Any) -> dict[str, Any]:
    today = date.today()
    base = {
        'start_date': today.isoformat(),
        'end_date': (today + timedelta(days=6)).isoformat(),
        'enabled_slots': ['LUNCH'],
        'default_servings': 2,
    }
    base.update(overrides)
    return base


def _shelve(
    db: Session,
    engine: AsyncEngine,
    user: User,
    location: StorageLocation,
    *,
    name: str,
    cans: int = 7,
    weight_value: Decimal | None = Decimal('400'),
    reserved: int = 0,
) -> ProductTemplate:
    pcs = db.execute(text("SELECT id FROM uoms WHERE symbol = 'pcs'")).fetchone()
    grams = db.execute(text("SELECT id FROM uoms WHERE symbol = 'g'")).fetchone()
    assert pcs is not None and grams is not None
    template = ProductTemplate(
        id=uuid.uuid4(),
        organization_id=user.organization_id,
        name=name,
        uom_id=pcs[0],
        weight_value=weight_value,
        weight_uom_id=grams[0] if weight_value is not None else None,
    )
    db.add(template)
    db.commit()

    async def _put(session: AsyncSession) -> None:
        await put_on_shelf(session, user, template, location.id, cans)
        if reserved:
            await reserve_for_an_order(session, template, location.id, reserved)

    run_in_async_session(engine, _put)
    db.expire_all()
    return template


def _plan_with(
    client: TestClient,
    auth_headers: dict[str, str],
    db: Session,
    *,
    ingredient_names: list[str],
    grams: str = '400',
) -> str:
    gram_uom = db.execute(text("SELECT id FROM uoms WHERE symbol = 'g'")).fetchone()
    assert gram_uom is not None
    plan_id = client.post(PLAN_URL, json=_plan_payload(), headers=auth_headers).json()[
        'id'
    ]
    today = date.today()
    for order, ingredient_name in enumerate(ingredient_names):
        recipe_id = client.post(
            RECIPE_URL,
            json={
                'name': f'Danie {order}',
                'servings': 1,
                'ingredients': [
                    {
                        'name': ingredient_name,
                        'quantity': grams,
                        'uom_id': str(gram_uom[0]),
                        'is_optional': False,
                    }
                ],
            },
            headers=auth_headers,
        ).json()['id']
        client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': today.isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': order,
            },
            headers=auth_headers,
        )
    return str(plan_id)


def _generate(
    client: TestClient, auth_headers: dict[str, str], plan_id: str
) -> dict[str, Any]:
    r = client.post(
        f'{PLAN_URL}/{plan_id}/generate-shopping-list', headers=auth_headers
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


@pytest.mark.integration
class TestShoppingListGeneration:
    def test_generate_shopping_list_empty_plan_returns_400(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        r = client.post(
            f'{PLAN_URL}/{plan_id}/generate-shopping-list', headers=auth_headers
        )
        assert r.status_code == 400

    def test_generate_shopping_list_with_recipe(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        recipe_r = client.post(
            RECIPE_URL,
            json={'name': 'Simple Dish', 'servings': 2, 'ingredients': []},
            headers=auth_headers,
        )
        recipe_id = recipe_r.json()['id']
        today = date.today()
        client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': today.isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        )
        r = client.post(
            f'{PLAN_URL}/{plan_id}/generate-shopping-list', headers=auth_headers
        )
        assert r.status_code == 200
        data = r.json()
        assert 'shopping_list_id' in data
        assert data['shopping_list_id'] is not None

    def test_generate_shopping_list_keeps_the_recipe_fraction(
        self, client: TestClient, auth_headers: dict[str, str], db_session: Session
    ) -> None:
        """A recipe asking for 0.75 kg puts 0.75 on the generated list.

        The generated-item schema declared the quantity an integer, so the
        fractional line this module reintroduced was thrown away with a raw
        pydantic dump before any list existed.
        """
        plan_id = _plan_with(
            client, auth_headers, db_session, ingredient_names=['Mąka'], grams='0.75'
        )
        r = client.post(
            f'{PLAN_URL}/{plan_id}/generate-shopping-list', headers=auth_headers
        )
        assert r.status_code == 200, r.text
        quantities = [item['quantity'] for item in r.json()['items']]
        # A fraction, not the "1" the integer schema would have demanded.
        assert Decimal(str(quantities[0])) == Decimal('1.5')

    def test_a_line_that_rounds_to_zero_does_not_fail_the_plans_list(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """An ingredient stored as 0.000 g asks the planner to buy nothing.
        Handed to the list as a zero, the store refuses it and the whole
        plan's list fails with a 400; skipped, the other lines still land.

        The shelf holds the same goods in pieces with no weight, so the two
        measures cannot be compared and the whole requirement — the zero —
        reaches the rounding. Without that, a zero shortfall leaves the line
        earlier and the skip under test never runs."""
        _shelve(
            db_session,
            async_engine_fixture,
            test_user,
            test_storage_location,
            name='Saffron dust',
            weight_value=None,
        )
        gram_uom = db_session.execute(
            text("SELECT id FROM uoms WHERE symbol = 'g'")
        ).fetchone()
        assert gram_uom is not None
        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        recipe_id = client.post(
            RECIPE_URL,
            json={
                'name': 'Dust',
                'servings': 1,
                'ingredients': [
                    {
                        'name': 'Saffron dust',
                        'quantity': '0.0004',
                        'uom_id': str(gram_uom[0]),
                        'is_optional': False,
                    },
                    {
                        'name': 'Flour',
                        'quantity': '500',
                        'uom_id': str(gram_uom[0]),
                        'is_optional': False,
                    },
                ],
            },
            headers=auth_headers,
        ).json()['id']
        client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': date.today().isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        )

        result = _generate(client, auth_headers, plan_id)

        names = [item['name'] for item in result['items']]
        assert names == ['Flour']
        assert result['to_buy_count'] == 1

    def test_generate_shopping_list_idempotent(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Second call returns same shopping_list_id."""
        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        recipe_id = client.post(
            RECIPE_URL,
            json={'name': 'Simple Dish', 'servings': 2, 'ingredients': []},
            headers=auth_headers,
        ).json()['id']
        today = date.today()
        client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': today.isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        )
        first = client.post(
            f'{PLAN_URL}/{plan_id}/generate-shopping-list', headers=auth_headers
        ).json()['shopping_list_id']
        second = client.post(
            f'{PLAN_URL}/{plan_id}/generate-shopping-list', headers=auth_headers
        ).json()['shopping_list_id']
        assert first == second

    def test_generate_shopping_list_unknown_plan_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        r = client.post(
            f'{PLAN_URL}/{uuid.uuid4()}/generate-shopping-list', headers=auth_headers
        )
        assert r.status_code == 404

    def test_shopping_list_excludes_optional_ingredients(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Optional ingredients must not appear on the generated shopping list."""
        recipe_r = client.post(
            RECIPE_URL,
            json={
                'name': 'Optional Ingredient Recipe',
                'servings': 2,
                'ingredients': [
                    {
                        'name': 'Required Flour',
                        'quantity': '500',
                        'is_optional': False,
                    },
                    {
                        'name': 'Optional Vanilla',
                        'quantity': '10',
                        'is_optional': True,
                    },
                ],
            },
            headers=auth_headers,
        )
        recipe_id = recipe_r.json()['id']

        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        today = date.today()
        client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': today.isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        )

        r = client.post(
            f'{PLAN_URL}/{plan_id}/generate-shopping-list', headers=auth_headers
        )
        assert r.status_code == 200
        item_names = [i['name'].lower() for i in r.json()['items']]
        assert any('required flour' in n for n in item_names)
        assert not any('optional vanilla' in n for n in item_names)

    def test_generated_list_name_and_notes_follow_language(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """generated list name and item notes are localized."""
        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        recipe_id = client.post(
            RECIPE_URL,
            json={
                'name': 'Simple Dish',
                'servings': 2,
                'ingredients': [
                    {
                        'name': 'Required Flour',
                        'quantity': '500',
                        'is_optional': False,
                    },
                ],
            },
            headers=auth_headers,
        ).json()['id']
        today = date.today()
        client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': today.isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        )

        pl_headers = {**auth_headers, 'Accept-Language': 'pl'}
        r = client.post(
            f'{PLAN_URL}/{plan_id}/generate-shopping-list', headers=pl_headers
        )
        assert r.status_code == 200
        list_id = r.json()['shopping_list_id']

        plan_data = client.get(f'{PLAN_URL}/{plan_id}', headers=pl_headers).json()
        list_r = client.get(f'/api/v1/shopping-lists/{list_id}', headers=pl_headers)
        assert list_r.status_code == 200
        data = list_r.json()
        assert data['name'] == f'Lista zakupów — {plan_data["name"]}'
        # The date is written the way Polish writes dates, not as the wire
        # format it travelled in: the note is prose a person reads.
        assert any(
            item['notes'] == f'Potrzebne do: {today.strftime("%d.%m.%Y")}'
            for item in data['items']
        )
        assert not any(
            today.isoformat() in (item['notes'] or '') for item in data['items']
        )
        # Beside the composed text the parts travel as data, so a reader in
        # any language can re-tell the note in their own.
        assert all(
            item['note_data']['needed_by'] == today.isoformat()
            for item in data['items']
        )


@pytest.mark.integration
class TestShoppingListDeductsWhatIsOnTheShelf:
    """Without this, the list said "buy chickpeas" over 36 cans of chickpeas."""

    def test_cans_on_the_shelf_cover_a_requirement_in_grams(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """7 cans of 400 g against 400 g needed: nothing to buy."""
        _shelve(
            db_session,
            async_engine_fixture,
            test_user,
            test_storage_location,
            name='Ciecierzyca w puszce',
        )
        plan_id = _plan_with(
            client, auth_headers, db_session, ingredient_names=['Ciecierzyca z puszki']
        )

        result = _generate(client, auth_headers, plan_id)

        assert result['to_buy_count'] == 0
        assert result['available_count'] == 1

    def test_incomparable_measures_get_a_note_instead_of_a_deficit(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """No pack size recorded: buy the whole amount and say why, don't invent 363.6."""
        _shelve(
            db_session,
            async_engine_fixture,
            test_user,
            test_storage_location,
            name='Ciecierzyca w puszce',
            weight_value=None,
        )
        plan_id = _plan_with(
            client, auth_headers, db_session, ingredient_names=['Ciecierzyca z puszki']
        )

        result = _generate(client, auth_headers, plan_id)

        assert result['to_buy_count'] == 1
        line = result['items'][0]
        # The plan doubles servings, so 400 g per serving is 800 g wanted —
        # all of it, because none of the stock could be weighed against it.
        assert Decimal(str(line['quantity'])) == 800
        assert line['quantities_comparable'] is False
        assert line['matched_approximately'] is True

        list_r = client.get(
            f'/api/v1/shopping-lists/{result["shopping_list_id"]}',
            headers=auth_headers,
        )
        notes = list_r.json()['items'][0]['notes']
        assert 'Check stock' in notes
        assert '7 pcs in stock' in notes
        assert 'recipe needs 800 g' in notes
        assert 'Ciecierzyca w puszce' in notes
        # The same reading as structured parts: the interface re-tells it in
        # the reader's language and translates the symbols itself.
        stored = list_r.json()['items'][0]['note_data']
        assert stored['check_stock'] == {
            'available_qty': 7.0,
            'available_uom_id': stored['check_stock']['available_uom_id'],
            'required_qty': 800.0,
            'required_uom_id': stored['check_stock']['required_uom_id'],
        }
        assert stored['check_stock']['required_uom_id'] is not None
        assert stored['matched_by_name'] == 'Ciecierzyca w puszce'

    def test_two_wordings_of_the_same_goods_buy_it_once(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """Aggregation keys on the resolved product, not on the spelling."""
        _shelve(
            db_session,
            async_engine_fixture,
            test_user,
            test_storage_location,
            name='Ciecierzyca w puszce',
            cans=1,
        )
        plan_id = _plan_with(
            client,
            auth_headers,
            db_session,
            ingredient_names=['Ciecierzyca z puszki', 'Ciecierzyca w puszce'],
            grams='500',
        )

        result = _generate(client, auth_headers, plan_id)

        assert result['total_ingredients'] == 1
        assert result['to_buy_count'] == 1
        # 2 × 500 g × 2 servings wanted across both wordings, 400 g on the shelf.
        assert Decimal(str(result['items'][0]['quantity'])) == 1600
        # The summary chip reads like the list does: a number and its measure.
        assert result['items'][0]['uom_symbol'] == 'g'


@pytest.mark.integration
class TestStockSpokenForIsNotStockYouHave:
    """Reserved goods belong to a document; the list must not spend them twice.

    The verdict summed the whole quant, reservations included, so the list
    said "nothing to buy" over stock another document had already claimed --
    and it said it exactly when the warehouse is busiest, which is when
    buying too little hurts most.
    """

    def test_a_reservation_turns_a_covered_ingredient_into_a_shortfall(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """7 cans, 6 of them spoken for: one can against 800 g wanted."""
        _shelve(
            db_session,
            async_engine_fixture,
            test_user,
            test_storage_location,
            name='Ciecierzyca w puszce',
            reserved=6,
        )
        plan_id = _plan_with(
            client, auth_headers, db_session, ingredient_names=['Ciecierzyca z puszki']
        )

        result = _generate(client, auth_headers, plan_id)

        assert result['to_buy_count'] == 1
        assert Decimal(str(result['items'][0]['quantity'])) == 400

    def test_the_same_shelf_without_a_reservation_buys_nothing(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """The control: the deduction still counts what is genuinely free."""
        _shelve(
            db_session,
            async_engine_fixture,
            test_user,
            test_storage_location,
            name='Ciecierzyca w puszce',
        )
        plan_id = _plan_with(
            client, auth_headers, db_session, ingredient_names=['Ciecierzyca z puszki']
        )

        result = _generate(client, auth_headers, plan_id)

        assert result['to_buy_count'] == 0

    def test_the_note_about_unweighable_stock_counts_the_same_way(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """ "7 pcs in stock" over six reserved cans would be the same lie."""
        _shelve(
            db_session,
            async_engine_fixture,
            test_user,
            test_storage_location,
            name='Ciecierzyca w puszce',
            weight_value=None,
            reserved=6,
        )
        plan_id = _plan_with(
            client, auth_headers, db_session, ingredient_names=['Ciecierzyca z puszki']
        )

        result = _generate(client, auth_headers, plan_id)

        list_r = client.get(
            f'/api/v1/shopping-lists/{result["shopping_list_id"]}',
            headers=auth_headers,
        )
        assert '1 pcs in stock' in list_r.json()['items'][0]['notes']


@pytest.mark.integration
class TestAlwaysAtHomeAndTheRefresh:
    """The plan's road honours exclusions and keeps its list current."""

    def test_an_excluded_product_stays_off_the_generated_list(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        from app.modules.recipes._name_matching import match_key
        from app.modules.recipes.models import ShoppingExclusion

        db_session.add(
            ShoppingExclusion(
                organization_id=test_user.organization_id,
                name='Sól',
                name_normalized=match_key('Sól'),
            )
        )
        db_session.commit()

        plan_id = _plan_with(
            client,
            auth_headers,
            db_session,
            ingredient_names=['Sól', 'Cukier'],
            grams='100',
        )

        result = _generate(client, auth_headers, plan_id)

        assert result['to_buy_count'] == 1
        assert [item['name'] for item in result['items']] == ['Cukier']

    def test_a_meal_added_after_generation_lands_on_the_same_list(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """The second run used to return the list with zeros and add nothing.

        A meal planned after the first generation was a meal that never
        reached the shopping list; the run now refreshes the list it made.
        """
        plan_id = _plan_with(
            client,
            auth_headers,
            db_session,
            ingredient_names=['Pierwszy'],
            grams='100',
        )
        first = _generate(client, auth_headers, plan_id)

        grams = db_session.execute(
            text("SELECT id FROM uoms WHERE symbol = 'g'")
        ).fetchone()
        assert grams is not None
        second_recipe = client.post(
            RECIPE_URL,
            json={
                'name': 'Drugie danie',
                'servings': 1,
                'ingredients': [
                    {'name': 'Drugi', 'quantity': '100', 'uom_id': str(grams[0])}
                ],
            },
            headers=auth_headers,
        ).json()['id']
        client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': date.today().isoformat(),
                'slot': 'LUNCH',
                'recipe_id': second_recipe,
                'order': 1,
            },
            headers=auth_headers,
        )

        second = _generate(client, auth_headers, plan_id)

        assert second['shopping_list_id'] == first['shopping_list_id']
        assert second['to_buy_count'] == 2
        list_r = client.get(
            f'/api/v1/shopping-lists/{second["shopping_list_id"]}',
            headers=auth_headers,
        )
        names = [item['name'] for item in list_r.json()['items']]
        assert sorted(names) == ['Drugi', 'Pierwszy']

    def test_regeneration_does_not_duplicate_what_is_already_listed(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        plan_id = _plan_with(
            client,
            auth_headers,
            db_session,
            ingredient_names=['Pierwszy'],
            grams='100',
        )
        first = _generate(client, auth_headers, plan_id)

        second = _generate(client, auth_headers, plan_id)

        assert second['shopping_list_id'] == first['shopping_list_id']
        list_r = client.get(
            f'/api/v1/shopping-lists/{second["shopping_list_id"]}',
            headers=auth_headers,
        )
        names = [item['name'] for item in list_r.json()['items']]
        assert names.count('Pierwszy') == 1

    def test_the_plan_says_when_a_meal_is_missing_from_its_list(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """The plan screen's "meals added after the list" line needs a fact.

        It stood under every generated list whether or not anything had been
        planned since; the plan now says whether a meal was added after the
        list was made, and the next run clears it.
        """
        plan_id = _plan_with(
            client,
            auth_headers,
            db_session,
            ingredient_names=['Pierwszy'],
            grams='100',
        )

        def missing() -> bool:
            plan = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers).json()
            return bool(plan['meals_added_since_list'])

        assert missing() is False  # no list yet: nothing is missing from it
        _generate(client, auth_headers, plan_id)
        assert missing() is False

        recipe_id = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers).json()[
            'entries'
        ][0]['recipe_id']
        client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': date.today().isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 5,
            },
            headers=auth_headers,
        )
        assert missing() is True

        _generate(client, auth_headers, plan_id)
        assert missing() is False

    def test_the_line_follows_the_meals_the_plan_holds_now(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """Whether a meal is missing is asked of the plan as it stands.

        A mark set by planning a meal stayed set after that meal was taken
        off again, and the screen went on saying a meal was missing from the
        list while every meal left was on it.
        """
        plan_id = _plan_with(
            client,
            auth_headers,
            db_session,
            ingredient_names=['Pierwszy'],
            grams='100',
        )

        def plan() -> dict[str, Any]:
            answer: dict[str, Any] = client.get(
                f'{PLAN_URL}/{plan_id}', headers=auth_headers
            ).json()
            return answer

        _generate(client, auth_headers, plan_id)
        listed = plan()['entries'][0]
        added = client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': date.today().isoformat(),
                'slot': 'LUNCH',
                'recipe_id': listed['recipe_id'],
                'order': 5,
            },
            headers=auth_headers,
        )
        assert added.status_code == 201, added.text
        assert plan()['meals_added_since_list'] is True

        removed = client.delete(
            f'{PLAN_URL}/{plan_id}/entries/{added.json()["id"]}',
            headers=auth_headers,
        )
        assert removed.status_code == 204, removed.text
        assert plan()['meals_added_since_list'] is False

        # Moved to another day it is the same meal, and already listed.
        moved = client.put(
            f'{PLAN_URL}/{plan_id}/entries/{listed["id"]}',
            json={'date': (date.today() + timedelta(days=1)).isoformat()},
            headers=auth_headers,
        )
        assert moved.status_code == 200, moved.text
        assert plan()['meals_added_since_list'] is False

        # More servings need more than the list was made for.
        resized = client.put(
            f'{PLAN_URL}/{plan_id}/entries/{listed["id"]}',
            json={'servings': (listed['servings'] or 1) + 3},
            headers=auth_headers,
        )
        assert resized.status_code == 200, resized.text
        assert plan()['meals_added_since_list'] is True

    def test_a_larger_plan_default_needs_more_than_the_list_was_made_for(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """A meal that states no servings follows the plan's default.

        The list was made for the servings the meal stood for then; kept as
        the entry's own (empty) value, raising the plan from two servings to
        five left the record unchanged, and the plan said nothing was missing
        from a list made for less than half of what it now asks for.
        """
        plan_id = _plan_with(
            client,
            auth_headers,
            db_session,
            ingredient_names=['Pierwszy'],
            grams='100',
        )
        _generate(client, auth_headers, plan_id)

        raised = client.put(
            f'{PLAN_URL}/{plan_id}',
            json={'default_servings': 5},
            headers=auth_headers,
        )
        assert raised.status_code == 200, raised.text
        plan = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers).json()
        assert plan['entries'][0]['servings'] == 5
        assert plan['meals_added_since_list'] is True

    def test_a_list_made_for_more_servings_covers_fewer(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """The line asks whether the plan needs more of a dish than was listed.

        Each meal was compared as an exact (recipe, servings) pair, so cutting
        a plan from five servings to two said a meal was missing from a list
        bought for five, and a dish planned twice at two each read as two
        meals the list did not know although it was made for five servings of
        that dish.
        """
        plan_id = _plan_with(
            client,
            auth_headers,
            db_session,
            ingredient_names=['Pierwszy'],
            grams='100',
        )

        def plan() -> dict[str, Any]:
            answer: dict[str, Any] = client.get(
                f'{PLAN_URL}/{plan_id}', headers=auth_headers
            ).json()
            return answer

        def set_default(servings: int) -> None:
            r = client.put(
                f'{PLAN_URL}/{plan_id}',
                json={'default_servings': servings},
                headers=auth_headers,
            )
            assert r.status_code == 200, r.text

        set_default(5)
        _generate(client, auth_headers, plan_id)
        listed = plan()['entries'][0]
        assert plan()['meals_added_since_list'] is False

        set_default(2)
        assert plan()['meals_added_since_list'] is False

        def plan_again() -> str:
            r = client.post(
                f'{PLAN_URL}/{plan_id}/entries',
                json={
                    'date': date.today().isoformat(),
                    'slot': 'LUNCH',
                    'recipe_id': listed['recipe_id'],
                    'order': 5 + len(plan()['entries']),
                },
                headers=auth_headers,
            )
            assert r.status_code == 201, r.text
            return str(r.json()['id'])

        # The same dish twice at two servings is four of the five listed.
        plan_again()
        assert plan()['meals_added_since_list'] is False

        # A third time is six: one more than the list was made for.
        third = plan_again()
        assert plan()['meals_added_since_list'] is True
        r = client.delete(f'{PLAN_URL}/{plan_id}/entries/{third}', headers=auth_headers)
        assert r.status_code == 204, r.text
        assert plan()['meals_added_since_list'] is False

        # A meal's own servings count the same way, down and up.
        r = client.put(
            f'{PLAN_URL}/{plan_id}/entries/{listed["id"]}',
            json={'servings': 1},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert plan()['meals_added_since_list'] is False
        r = client.put(
            f'{PLAN_URL}/{plan_id}/entries/{listed["id"]}',
            json={'servings': 4},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert plan()['meals_added_since_list'] is True

    def test_a_list_made_before_its_meals_were_kept_is_not_vouched_for(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """A plan listed before the plan kept what its list was made from.

        Nothing says which meals that list carries, so a meal planned after
        it may be missing from it. Answering no hid every such meal until the
        list happened to be made again; the plan offers the refresh instead,
        and the refresh records what the list is made from.
        """
        plan_id = _plan_with(
            client,
            auth_headers,
            db_session,
            ingredient_names=['Pierwszy'],
            grams='100',
        )
        _generate(client, auth_headers, plan_id)
        db_session.execute(
            text('UPDATE meal_plans SET listed_meals = NULL WHERE id = :id'),
            {'id': plan_id},
        )
        db_session.commit()

        def missing() -> bool:
            plan = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers).json()
            return bool(plan['meals_added_since_list'])

        assert missing() is True
        _generate(client, auth_headers, plan_id)
        assert missing() is False
