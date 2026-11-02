"""A step-by-step cook opens its own history entry, and the rating lands on
the cook it belongs to.

The cooking mode never touches the shelf, so it never opened a picking
session — and the "Bon appétit" screen asked for a rating anyway, then wrote
it onto whatever session had closed last: a wrong day, wrong servings, "no
items picked" under a note about a different dinner. Finishing a cook now
records its own entry, and the rating patches that entry — even when an
older, unrelated closed session is sitting at the top of the history.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from app.modules.recipes.models import PickingSession

RECIPE_URL = '/api/v1/recipes'


def _recipe(client: TestClient, auth_headers: dict[str, str], servings: int = 2) -> str:
    payload: dict[str, Any] = {
        'name': f'Pancakes {uuid.uuid4().hex[:6]}',
        'description': '',
        'servings': servings,
        'prep_time_minutes': 10,
        'tags': [],
        'is_favorite': False,
        'ingredients': [],
    }
    created = client.post(RECIPE_URL, json=payload, headers=auth_headers)
    assert created.status_code == 201, created.text
    recipe_id: str = created.json()['id']
    return recipe_id


def _history(
    client: TestClient, auth_headers: dict[str, str], recipe_id: str
) -> list[dict[str, Any]]:
    listed = client.get(f'{RECIPE_URL}/{recipe_id}/history', headers=auth_headers)
    assert listed.status_code == 200, listed.text
    entries: list[dict[str, Any]] = listed.json()['items']
    return entries


@pytest.mark.integration
class TestStepByStepCookingHistory:
    def test_a_finished_cook_opens_its_own_entry(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        recipe_id = _recipe(client, auth_headers, servings=2)

        recorded = client.post(
            f'{RECIPE_URL}/{recipe_id}/history',
            json={'servings': 4},
            headers=auth_headers,
        )
        assert recorded.status_code == 201, recorded.text
        entry = recorded.json()
        assert entry['servings'] == 4
        assert entry['rating'] is None
        assert entry['cooked_at'] is not None
        assert entry['items_total'] == 0

        history = _history(client, auth_headers, recipe_id)
        assert len(history) == 1
        assert history[0]['session_id'] == entry['session_id']

    def test_a_rating_lands_on_its_own_cooking_not_on_the_older_one(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Any,
        test_user: Any,
    ) -> None:
        recipe_id = _recipe(client, auth_headers)

        # An older, unrelated closed session — the one the finished screen
        # used to write onto, because it was whatever the history had.
        older = PickingSession(
            organization_id=test_user.organization_id,
            recipe_id=uuid.UUID(recipe_id),
            user_id=test_user.id,
            servings=2,
            status='completed',
            created_at=datetime.now(UTC) - timedelta(days=3),
            completed_at=datetime.now(UTC) - timedelta(days=3),
        )
        db_session.add(older)
        db_session.commit()

        recorded = client.post(
            f'{RECIPE_URL}/{recipe_id}/history',
            json={'servings': 2},
            headers=auth_headers,
        )
        assert recorded.status_code == 201, recorded.text
        own_id = recorded.json()['session_id']

        rated = client.patch(
            f'{RECIPE_URL}/{recipe_id}/history/{own_id}',
            json={'rating': 4, 'notes': 'Came out thin'},
            headers=auth_headers,
        )
        assert rated.status_code == 200, rated.text

        history = _history(client, auth_headers, recipe_id)
        by_id = {row['session_id']: row for row in history}
        assert by_id[own_id]['rating'] == 4
        assert by_id[own_id]['notes'] == 'Came out thin'
        assert by_id[str(older.id)]['rating'] is None
        assert by_id[str(older.id)]['notes'] is None

    def test_a_cook_after_picking_closes_that_run_instead_of_a_second_entry(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """One dinner, one entry.

        Picking the ingredients and then cooking them step by step is one
        meal. Recorded as two entries it reads as two dinners: the picked
        run stays unrated and the note hangs on an entry saying nothing was
        picked — which is the shape this whole task exists to remove.
        """
        recipe_id = _recipe(client, auth_headers, servings=2)
        started = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 3},
            headers=auth_headers,
        )
        assert started.status_code == 201, started.text
        session_id = started.json()['picking_session_id']
        completed = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/complete',
            headers=auth_headers,
        )
        assert completed.status_code == 200, completed.text

        recorded = client.post(
            f'{RECIPE_URL}/{recipe_id}/history',
            json={'servings': 3, 'session_id': session_id},
            headers=auth_headers,
        )
        assert recorded.status_code == 201, recorded.text
        assert recorded.json()['session_id'] == session_id

        entries = _history(client, auth_headers, recipe_id)
        assert [e['session_id'] for e in entries] == [session_id]

    def test_cooking_in_the_evening_after_a_morning_pick_is_dated_by_the_cook(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Any,
        test_user: Any,
    ) -> None:
        """The entry says when the dinner was cooked, not when the shelf was walked.

        A run finished in the morning and continued by the evening's cook kept
        the morning's closing time, so the history dated the dinner to the
        wrong hour — and, near midnight, the wrong day on the meal plan.
        """
        recipe_id = _recipe(client, auth_headers)
        picked_at = datetime.now(UTC) - timedelta(hours=8)
        morning = PickingSession(
            organization_id=test_user.organization_id,
            recipe_id=uuid.UUID(recipe_id),
            user_id=test_user.id,
            servings=2,
            status='completed',
            created_at=picked_at - timedelta(minutes=10),
            completed_at=picked_at,
        )
        db_session.add(morning)
        db_session.commit()

        recorded = client.post(
            f'{RECIPE_URL}/{recipe_id}/history',
            json={'servings': 2, 'session_id': str(morning.id)},
            headers=auth_headers,
        )
        assert recorded.status_code == 201, recorded.text
        assert recorded.json()['session_id'] == str(morning.id)

        entry = _history(client, auth_headers, recipe_id)[0]
        cooked_at = datetime.fromisoformat(entry['cooked_at'])
        assert datetime.now(UTC) - cooked_at < timedelta(minutes=5)

    def test_a_second_cook_does_not_overwrite_the_dinner_already_rated(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """A rated run is a finished dinner, not a thread to keep pulling.

        Continuing a picking run is what makes one dinner one entry. But the
        continuation stayed open after it was used: cooking the same recipe a
        second time from the same card named the same run again, and the
        rating of the first dinner was overwritten by the second — one entry
        where there were two meals, and the first evening's note gone for
        good. A run that already carries a rating or a note is no longer
        continuable; the next cook opens its own entry.
        """
        recipe_id = _recipe(client, auth_headers, servings=2)
        started = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        assert started.status_code == 201, started.text
        session_id = started.json()['picking_session_id']
        completed = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/complete',
            headers=auth_headers,
        )
        assert completed.status_code == 200, completed.text

        first = client.post(
            f'{RECIPE_URL}/{recipe_id}/history',
            json={'servings': 2, 'session_id': session_id},
            headers=auth_headers,
        )
        assert first.status_code == 201, first.text
        rated = client.patch(
            f'{RECIPE_URL}/{recipe_id}/history/{session_id}',
            json={'rating': 5, 'notes': 'first dinner'},
            headers=auth_headers,
        )
        assert rated.status_code == 200, rated.text

        # The same thread, offered a second time.
        again = client.post(
            f'{RECIPE_URL}/{recipe_id}/history',
            json={'servings': 2, 'session_id': session_id},
            headers=auth_headers,
        )
        assert again.status_code == 404, again.text

        # And the cook that follows opens an entry of its own.
        second = client.post(
            f'{RECIPE_URL}/{recipe_id}/history',
            json={'servings': 2},
            headers=auth_headers,
        )
        assert second.status_code == 201, second.text
        second_id = second.json()['session_id']
        assert second_id != session_id

        history = _history(client, auth_headers, recipe_id)
        by_id = {row['session_id']: row for row in history}
        assert by_id[session_id]['rating'] == 5
        assert by_id[session_id]['notes'] == 'first dinner'
        assert by_id[second_id]['rating'] is None

    def test_a_run_from_another_recipe_is_not_a_session_this_cook_may_close(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """The id is scoped, so it cannot reach across dinners."""
        cooked = _recipe(client, auth_headers)
        other = _recipe(client, auth_headers)
        started = client.post(
            f'{RECIPE_URL}/{other}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )
        assert started.status_code == 201, started.text

        recorded = client.post(
            f'{RECIPE_URL}/{cooked}/history',
            json={'session_id': started.json()['picking_session_id']},
            headers=auth_headers,
        )

        assert recorded.status_code == 404, recorded.text

    @pytest.mark.parametrize('servings', [0, -5, 100000, 3000000000])
    def test_a_serving_count_outside_the_pot_is_refused(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        servings: int,
    ) -> None:
        """A serving count is a pot on a stove.

        Unbounded, it reached the column as an overflow: 3000000000 answered
        500 out of the database driver, 100000 was accepted outright. The
        picking start beside it has carried 1..200 all along.
        """
        recipe_id = _recipe(client, auth_headers)

        recorded = client.post(
            f'{RECIPE_URL}/{recipe_id}/history',
            json={'servings': servings},
            headers=auth_headers,
        )

        assert recorded.status_code == 422, recorded.text

    def test_an_unknown_recipe_is_refused_in_the_reader_s_language(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        refused = client.post(
            f'{RECIPE_URL}/{uuid.uuid4()}/history',
            json={},
            headers={**auth_headers, 'Accept-Language': 'pl'},
        )

        assert refused.status_code == 404, refused.text
        detail = refused.json()['detail']
        message = detail['message'] if isinstance(detail, dict) else detail
        assert 'not found' not in message.lower(), message

    def test_termination_never_writes_into_the_cook_s_note(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Any,
        test_user: Any,
    ) -> None:
        recipe_id = _recipe(client, auth_headers)

        started = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        assert started.status_code == 201, started.text
        session_id = started.json()['picking_session_id']

        select_session = select(PickingSession).where(
            PickingSession.id == uuid.UUID(session_id)
        )
        db_session.expire_all()
        session = db_session.scalars(select_session).first()
        session.notes = 'Came out thin, less milk next time'
        db_session.commit()

        cancelled = client.delete(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}',
            headers=auth_headers,
        )
        assert cancelled.status_code == 204, cancelled.text

        db_session.expire_all()
        session = db_session.scalars(select_session).first()
        assert session.status == 'cancelled'
        # The reason lives in the item history and the log; the note is the
        # cook's own words, not the machine's.
        assert session.notes == 'Came out thin, less milk next time'
