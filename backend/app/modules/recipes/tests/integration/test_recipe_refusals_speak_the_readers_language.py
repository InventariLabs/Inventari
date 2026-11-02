"""The recipe, meal plan and exclusion refusals answer in the reader's language.

Each of these raised an English sentence under a code of its own, while the
400/409 envelope was stamped with the reader's ``lang``. The assertions are
equalities on the Polish text and the code: a site reverted to its English
literal answers the same status and the same code, so only the sentence
tells the two apart.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.exceptions import ConflictException
from app.i18n import MAINTAINED_LANGUAGES
from app.i18n.service import get_error_message, set_current_lang
from app.models.user import User
from app.modules.recipes import _meal_plan
from app.modules.recipes.models import PickingSession

pytestmark = pytest.mark.integration

PLAN_URL = '/api/v1/recipes/meal-plans'

NEW_KEYS = {
    'picking_active_recipe_locked',
    'meal_plan_dates_exclude_entries',
    'meal_plan_position_taken',
    'meal_plan_entry_date_out_of_range',
    'meal_plan_slot_not_enabled',
    'shopping_exclusion_exists',
}


def _polish(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, 'Accept-Language': 'pl'}


def _plan_and_recipe(client: TestClient, headers: dict[str, str]) -> tuple[str, str]:
    today = date.today()
    plan: dict[str, Any] = {
        'name': 'Week',
        'start_date': today.isoformat(),
        'end_date': (today + timedelta(days=6)).isoformat(),
        'enabled_slots': ['LUNCH', 'DINNER'],
        'default_servings': 2,
    }
    plan_id = client.post(PLAN_URL, json=plan, headers=headers).json()['id']
    recipe_id = client.post(
        '/api/v1/recipes',
        json={'name': 'Soup', 'servings': 2, 'ingredients': []},
        headers=headers,
    ).json()['id']
    return plan_id, recipe_id


def _refusal(response: Any, code: str) -> str:
    assert response.status_code == 409
    detail = response.json()['detail']
    assert detail['code'] == code
    return str(detail['message'])


def test_an_entry_outside_the_plan_dates_is_refused_in_polish(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    plan_id, recipe_id = _plan_and_recipe(client, auth_headers)

    response = client.post(
        f'{PLAN_URL}/{plan_id}/entries',
        json={
            'date': (date.today() + timedelta(days=30)).isoformat(),
            'slot': 'LUNCH',
            'recipe_id': recipe_id,
            'order': 0,
        },
        headers=_polish(auth_headers),
    )

    assert (
        _refusal(response, 'ENTRY_DATE_OUT_OF_RANGE')
        == 'Data wpisu wykracza poza zakres dat planu.'
    )


def test_an_entry_in_a_disabled_meal_is_refused_in_polish(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    plan_id, recipe_id = _plan_and_recipe(client, auth_headers)

    response = client.post(
        f'{PLAN_URL}/{plan_id}/entries',
        json={
            'date': date.today().isoformat(),
            'slot': 'BREAKFAST',
            'recipe_id': recipe_id,
            'order': 0,
        },
        headers=_polish(auth_headers),
    )

    assert (
        _refusal(response, 'SLOT_NOT_ENABLED')
        == 'Ten posiłek nie jest włączony w tym planie.'
    )


def test_shrinking_the_plan_past_an_entry_is_refused_in_polish(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    plan_id, recipe_id = _plan_and_recipe(client, auth_headers)
    client.post(
        f'{PLAN_URL}/{plan_id}/entries',
        json={
            'date': (date.today() + timedelta(days=5)).isoformat(),
            'slot': 'LUNCH',
            'recipe_id': recipe_id,
            'order': 0,
        },
        headers=auth_headers,
    )

    response = client.put(
        f'{PLAN_URL}/{plan_id}',
        json={'end_date': (date.today() + timedelta(days=1)).isoformat()},
        headers=_polish(auth_headers),
    )

    assert (
        _refusal(response, 'MEAL_PLAN_DATE_CONFLICT')
        == 'Najpierw usuń wpisy z wykluczonych dni.'
    )


def test_a_second_exclusion_of_the_same_name_is_refused_in_polish(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    url = f'{PLAN_URL}/exclusions'
    assert (
        client.post(url, json={'name': 'Salt'}, headers=auth_headers).status_code == 201
    )

    response = client.post(url, json={'name': 'Salt'}, headers=_polish(auth_headers))

    assert _refusal(response, 'EXCLUSION_EXISTS') == 'To wykluczenie już istnieje.'


def test_editing_ingredients_during_a_picking_session_is_refused_in_polish(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_user: User,
) -> None:
    recipe_id = client.post(
        '/api/v1/recipes',
        json={'name': 'Soup', 'servings': 2, 'ingredients': []},
        headers=auth_headers,
    ).json()['id']
    db_session.add(
        PickingSession(
            organization_id=test_user.organization_id,
            recipe_id=recipe_id,
            user_id=test_user.id,
            servings=2,
            status='active',
        )
    )
    db_session.commit()

    response = client.put(
        f'/api/v1/recipes/{recipe_id}',
        json={
            'name': 'Soup',
            'servings': 2,
            'ingredients': [{'name': 'Leek', 'quantity': '1', 'is_optional': False}],
        },
        headers=_polish(auth_headers),
    )

    assert _refusal(response, 'PICKING_ACTIVE') == (
        'Nie można edytować składników, gdy sesja zbierania jest aktywna. '
        'Najpierw anuluj lub zakończ sesję.'
    )


class _CollidingSession:
    """A session whose every insert collides with a position another request took."""

    def begin_nested(self) -> Any:
        raise IntegrityError('insert', {}, Exception('uq_meal_plan_entry_position'))

    def __contains__(self, _entry: object) -> bool:
        return False


@pytest.mark.asyncio
async def test_a_meal_whose_positions_keep_colliding_is_refused_in_polish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def next_order(*_args: object) -> int:
        return 1

    monkeypatch.setattr(_meal_plan, '_next_order_in_cell_async', next_order)
    entry = _meal_plan.MealPlanEntry(
        meal_plan_id=uuid4(), date=date.today(), slot='LUNCH', order=0
    )
    set_current_lang('pl')
    try:
        with pytest.raises(ConflictException) as caught:
            await _meal_plan._insert_entry_at_a_free_position_async(
                cast(AsyncSession, _CollidingSession()), entry
            )
    finally:
        set_current_lang('en')

    detail = cast(dict[str, Any], caught.value.detail)
    assert detail['code'] == 'MEAL_PLAN_ENTRY_POSITION_TAKEN'
    assert detail['message'] == 'Nie udało się znaleźć wolnego miejsca w tym posiłku.'


@pytest.mark.parametrize('key', sorted(NEW_KEYS))
def test_every_new_key_is_translated_in_every_maintained_language(key: str) -> None:
    english = get_error_message(key, 'en')
    assert english != key
    for lang in MAINTAINED_LANGUAGES:
        if lang != 'en':
            assert get_error_message(key, lang) != english, (key, lang)
