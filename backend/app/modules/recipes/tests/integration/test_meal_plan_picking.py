"""Integration tests for Meal Plan picking (Cook Now) integration."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.user import User
from app.modules.recipes.models import PickingSession

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


@pytest.mark.integration
class TestMealPlanPickingIntegration:
    def _setup_plan_with_entry(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> tuple[str, str, str]:
        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        recipe_id = client.post(
            RECIPE_URL,
            json={'name': 'Cook Now Recipe', 'servings': 2, 'ingredients': []},
            headers=auth_headers,
        ).json()['id']
        today = date.today()
        entry_id = client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': today.isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        ).json()['id']
        return plan_id, entry_id, recipe_id

    def test_cook_entry_creates_picking_session(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id, entry_id, _ = self._setup_plan_with_entry(client, auth_headers)
        r = client.post(
            f'{PLAN_URL}/{plan_id}/entries/{entry_id}/cook', headers=auth_headers
        )
        assert r.status_code == 200
        data = r.json()
        assert 'picking_session_id' in data

    def test_cook_entry_not_found_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        r = client.post(
            f'{PLAN_URL}/{plan_id}/entries/{uuid.uuid4()}/cook', headers=auth_headers
        )
        assert r.status_code == 404

    def test_cook_unknown_plan_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        r = client.post(
            f'{PLAN_URL}/{uuid.uuid4()}/entries/{uuid.uuid4()}/cook',
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_entry_is_completed_false_before_cooking(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id, entry_id, _ = self._setup_plan_with_entry(client, auth_headers)
        plan = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers).json()
        entry = next(e for e in plan['entries'] if e['id'] == entry_id)
        assert entry['is_completed'] is False
        assert entry['picking_session_id'] is None


def _complete_a_cook(
    db_session: Session, user: User, recipe_id: str, on: date
) -> uuid.UUID:
    """A finished cooking session of *recipe_id*, finished at noon on *on*.

    Noon, so the day is the same one in any organization's zone.
    """
    session = PickingSession(
        organization_id=user.organization_id,
        recipe_id=uuid.UUID(recipe_id),
        user_id=user.id,
        status='completed',
        completed_at=datetime.combine(on, time(12, 0), tzinfo=UTC),
    )
    db_session.add(session)
    db_session.commit()
    return session.id


@pytest.mark.integration
class TestARepeatedRecipeIsCookedOnItsOwnDay:
    """A cook marks the plan entry of the day it happened, and no other.

    A session used to complete the earliest entry of the recipe on or before
    the day it finished: cooking Tuna Pasta Salad on Saturday ticked off
    Thursday's dinner, and the week read Thursday as done.
    """

    def _plan_with_the_recipe_twice(
        self, client: TestClient, auth_headers: dict[str, str], first: date, last: date
    ) -> tuple[str, str, dict[date, str]]:
        plan_id = client.post(
            PLAN_URL,
            json=_plan_payload(start_date=first.isoformat(), end_date=last.isoformat()),
            headers=auth_headers,
        ).json()['id']
        recipe_id = client.post(
            RECIPE_URL,
            json={'name': 'Tuna Pasta Salad', 'servings': 2, 'ingredients': []},
            headers=auth_headers,
        ).json()['id']
        entries: dict[date, str] = {}
        for day in (first, last):
            response = client.post(
                f'{PLAN_URL}/{plan_id}/entries',
                json={
                    'date': day.isoformat(),
                    'slot': 'LUNCH',
                    'recipe_id': recipe_id,
                    'order': 0,
                },
                headers=auth_headers,
            )
            assert response.status_code == 201, response.text
            entries[day] = response.json()['id']
        return plan_id, recipe_id, entries

    def _entries_by_id(
        self, client: TestClient, auth_headers: dict[str, str], plan_id: str
    ) -> dict[str, dict[str, Any]]:
        plan = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers).json()
        return {e['id']: e for e in plan['entries']}

    def test_a_later_cook_leaves_the_earlier_entry_not_cooked(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        thursday = date.today() - timedelta(days=2)
        saturday = date.today()
        plan_id, recipe_id, entries = self._plan_with_the_recipe_twice(
            client, auth_headers, thursday, saturday
        )
        session_id = _complete_a_cook(db_session, test_user, recipe_id, saturday)

        by_id = self._entries_by_id(client, auth_headers, plan_id)
        assert by_id[entries[thursday]]['is_completed'] is False
        assert by_id[entries[thursday]]['picking_session_id'] is None
        assert by_id[entries[saturday]]['is_completed'] is True
        assert by_id[entries[saturday]]['picking_session_id'] == str(session_id)

        # The one-entry answer (what an edit returns) reads the same rule.
        edited = client.put(
            f'{PLAN_URL}/{plan_id}/entries/{entries[thursday]}',
            json={'notes': 'still to cook'},
            headers=auth_headers,
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()['is_completed'] is False

    def test_each_cook_marks_the_entry_of_its_own_day(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        thursday = date.today() - timedelta(days=2)
        saturday = date.today()
        plan_id, recipe_id, entries = self._plan_with_the_recipe_twice(
            client, auth_headers, thursday, saturday
        )
        on_thursday = _complete_a_cook(db_session, test_user, recipe_id, thursday)
        on_saturday = _complete_a_cook(db_session, test_user, recipe_id, saturday)

        by_id = self._entries_by_id(client, auth_headers, plan_id)
        assert by_id[entries[thursday]]['picking_session_id'] == str(on_thursday)
        assert by_id[entries[saturday]]['picking_session_id'] == str(on_saturday)

    def _plan_with_lunch_and_dinner(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> tuple[str, str, dict[str, str]]:
        # Two slots of one day ordinarily both carry order 0.
        today = date.today()
        plan_id = client.post(
            PLAN_URL,
            json=_plan_payload(enabled_slots=['LUNCH', 'DINNER']),
            headers=auth_headers,
        ).json()['id']
        recipe_id = client.post(
            RECIPE_URL,
            json={'name': 'Tuna Pasta Salad', 'servings': 2, 'ingredients': []},
            headers=auth_headers,
        ).json()['id']
        entries = {}
        for slot in ('LUNCH', 'DINNER'):
            response = client.post(
                f'{PLAN_URL}/{plan_id}/entries',
                json={
                    'date': today.isoformat(),
                    'slot': slot,
                    'recipe_id': recipe_id,
                    'order': 0,
                },
                headers=auth_headers,
            )
            assert response.status_code == 201, response.text
            entries[slot] = response.json()['id']
        return plan_id, recipe_id, entries

    def test_one_cook_of_a_recipe_planned_twice_in_a_day_reads_alike_everywhere(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        # A cook with no entry behind it (started from the recipe page) cannot
        # depend on which of the two cards is edited.
        plan_id, recipe_id, entries = self._plan_with_lunch_and_dinner(
            client, auth_headers
        )
        _complete_a_cook(db_session, test_user, recipe_id, date.today())

        plan = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers).json()
        on_plan = {e['slot']: e['is_completed'] for e in plan['entries']}
        assert sorted(on_plan.values()) == [False, True]

        for slot, entry_id in entries.items():
            edited = client.put(
                f'{PLAN_URL}/{plan_id}/entries/{entry_id}',
                json={'notes': 'same state'},
                headers=auth_headers,
            )
            assert edited.status_code == 200, edited.text
            assert edited.json()['is_completed'] is on_plan[slot]

    @pytest.mark.parametrize('cooked', ['LUNCH', 'DINNER'])
    def test_the_cook_completes_the_card_it_was_started_from(
        self,
        cooked: str,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        plan_id, _, entries = self._plan_with_lunch_and_dinner(client, auth_headers)
        started = client.post(
            f'{PLAN_URL}/{plan_id}/entries/{entries[cooked]}/cook',
            headers=auth_headers,
        )
        assert started.status_code == 200, started.text
        session = db_session.get(
            PickingSession, uuid.UUID(started.json()['picking_session_id'])
        )
        assert session is not None
        session.status = 'completed'
        session.completed_at = datetime.now(UTC)
        db_session.commit()

        plan = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers).json()
        on_plan = {e['slot']: e['is_completed'] for e in plan['entries']}
        assert on_plan == {slot: slot == cooked for slot in entries}
        for slot, entry_id in entries.items():
            edited = client.put(
                f'{PLAN_URL}/{plan_id}/entries/{entry_id}',
                json={'notes': 'same state'},
                headers=auth_headers,
            )
            assert edited.json()['is_completed'] is (slot == cooked)

    def test_the_picking_start_the_plan_page_sends_names_the_card(
        self, client: TestClient, auth_headers: dict[str, str], db_session: Session
    ) -> None:
        plan_id, recipe_id, entries = self._plan_with_lunch_and_dinner(
            client, auth_headers
        )
        started = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 3, 'meal_plan_entry_id': entries['LUNCH']},
            headers=auth_headers,
        )
        assert started.status_code == 201, started.text
        session = db_session.get(
            PickingSession, uuid.UUID(started.json()['picking_session_id'])
        )
        assert session is not None
        assert str(session.meal_plan_entry_id) == entries['LUNCH']
        assert session.servings == 3
        session.status = 'completed'
        session.completed_at = datetime.now(UTC)
        db_session.commit()
        on_plan = {
            e['slot']: e['is_completed']
            for e in client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers).json()[
                'entries'
            ]
        }
        assert on_plan == {'LUNCH': True, 'DINNER': False}

    def test_a_picking_start_refuses_a_card_that_is_not_the_recipes_own(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        _, recipe_id, entries = self._plan_with_lunch_and_dinner(client, auth_headers)
        other_recipe = client.post(
            RECIPE_URL,
            json={'name': 'Some Other Dish', 'servings': 2, 'ingredients': []},
            headers=auth_headers,
        ).json()['id']
        for recipe, entry in (
            (other_recipe, entries['LUNCH']),
            (recipe_id, str(uuid.uuid4())),
        ):
            refused = client.post(
                f'{RECIPE_URL}/{recipe}/picking/start',
                json={'servings': 2, 'meal_plan_entry_id': entry},
                headers=auth_headers,
            )
            assert refused.status_code == 404, refused.text

    def test_cook_now_on_the_sibling_card_moves_an_unfinished_cook_to_it(
        self, client: TestClient, auth_headers: dict[str, str], db_session: Session
    ) -> None:
        plan_id, _, entries = self._plan_with_lunch_and_dinner(client, auth_headers)
        first = client.post(
            f'{PLAN_URL}/{plan_id}/entries/{entries["LUNCH"]}/cook',
            headers=auth_headers,
        ).json()
        again = client.post(
            f'{PLAN_URL}/{plan_id}/entries/{entries["DINNER"]}/cook',
            headers=auth_headers,
        ).json()
        assert again['picking_session_id'] == first['picking_session_id']
        db_session.expire_all()
        session = db_session.get(PickingSession, uuid.UUID(first['picking_session_id']))
        assert session is not None
        assert str(session.meal_plan_entry_id) == entries['DINNER']
