"""A recipe can say which meals of which plans a delete would empty.

Deleting a recipe removes its meal-plan entries with it, and the confirmation
has to name them: the plan and the day and meal each one was in. A recipe in no
plan answers with an empty list, and another organization's plans never show.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from starlette.testclient import TestClient

RECIPE_URL = '/api/v1/recipes'
PLAN_URL = '/api/v1/recipes/meal-plans'


def _recipe(client: TestClient, headers: dict[str, str], name: str) -> str:
    created = client.post(
        RECIPE_URL,
        json={'name': name, 'servings': 2, 'ingredients': []},
        headers=headers,
    )
    assert created.status_code == 201
    return str(created.json()['id'])


def _plan(client: TestClient, headers: dict[str, str], name: str) -> str:
    today = date.today()
    created = client.post(
        PLAN_URL,
        json={
            'name': name,
            'start_date': today.isoformat(),
            'end_date': (today + timedelta(days=6)).isoformat(),
            'enabled_slots': ['BREAKFAST', 'LUNCH'],
        },
        headers=headers,
    )
    assert created.status_code == 201
    return str(created.json()['id'])


def _plan_it(
    client: TestClient,
    headers: dict[str, str],
    plan_id: str,
    recipe_id: str,
    day: date,
    slot: str,
) -> None:
    added = client.post(
        f'{PLAN_URL}/{plan_id}/entries',
        json={'date': day.isoformat(), 'slot': slot, 'recipe_id': recipe_id},
        headers=headers,
    )
    assert added.status_code == 201, added.text


@pytest.mark.integration
class TestARecipeNamesTheMealsThatPlanIt:
    def test_a_recipe_in_no_plan_answers_with_an_empty_list(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        recipe_id = _recipe(client, auth_headers, 'Garlic bread')

        response = client.get(f'{RECIPE_URL}/{recipe_id}/planned', headers=auth_headers)

        assert response.status_code == 200
        assert response.json()['items'] == []
        assert response.json()['total'] == 0

    def test_each_planned_meal_names_its_plan_day_and_slot(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        recipe_id = _recipe(client, auth_headers, 'Garlic bread')
        other = _recipe(client, auth_headers, 'Soup')
        plan_id = _plan(client, auth_headers, 'Week plan')
        today = date.today()
        _plan_it(
            client, auth_headers, plan_id, recipe_id, today + timedelta(1), 'LUNCH'
        )
        _plan_it(client, auth_headers, plan_id, recipe_id, today, 'BREAKFAST')
        _plan_it(client, auth_headers, plan_id, other, today, 'LUNCH')

        response = client.get(f'{RECIPE_URL}/{recipe_id}/planned', headers=auth_headers)

        assert response.status_code == 200
        meals: list[dict[str, Any]] = response.json()['items']
        assert [(m['date'], m['slot']) for m in meals] == [
            (today.isoformat(), 'BREAKFAST'),
            ((today + timedelta(1)).isoformat(), 'LUNCH'),
        ]
        assert {m['plan_id'] for m in meals} == {plan_id}
        assert {m['plan_name'] for m in meals} == {'Week plan'}

    def test_an_unknown_recipe_is_not_found(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get(
            f'{RECIPE_URL}/00000000-0000-0000-0000-00000000dead/planned',
            headers=auth_headers,
        )

        assert response.status_code == 404
