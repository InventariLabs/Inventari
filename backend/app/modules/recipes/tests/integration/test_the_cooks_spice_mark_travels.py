"""The cook's spice mark lives on the recipe, not only in the import sheet.

The import review's "Spice" chip flips a local flag; the flag used to be
dropped on save, so a bay leaf the cook had marked came back in the main
list, its section decided by the bare amount. The mark is written with the
ingredient now, read back on GET, and carried by the availability answer
the card folds the seasonings section from.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

RECIPE_URL = '/api/v1/recipes'

pytestmark = pytest.mark.integration


def _uom_id(db: Session, symbol: str) -> uuid.UUID:
    row = db.execute(
        text('SELECT id FROM uoms WHERE symbol = :s'), {'s': symbol}
    ).fetchone()
    assert row is not None, f'UOM {symbol!r} is not seeded'
    return uuid.UUID(str(row[0]))


def _create_recipe(
    client: TestClient,
    auth_headers: dict[str, str],
    db: Session,
    *,
    name: str = 'Bolognese',
    ingredients: list[dict[str, Any]],
) -> dict[str, Any]:
    response = client.post(
        RECIPE_URL,
        json={'name': name, 'servings': 1, 'ingredients': ingredients},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def _bay_leaf(db: Session, *, is_spice: bool | None = None) -> dict[str, Any]:
    ingredient: dict[str, Any] = {
        'name': 'Bay leaf',
        'quantity': '1',
        'uom_id': str(_uom_id(db, 'pcs')),
        'is_optional': False,
    }
    if is_spice is not None:
        ingredient['is_spice'] = is_spice
    return ingredient


def _salt(db: Session) -> dict[str, Any]:
    return {
        'name': 'Salt',
        'quantity': '5',
        'uom_id': str(_uom_id(db, 'g')),
        'is_optional': False,
    }


def _by_name(ingredients: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {ingredient['name']: ingredient for ingredient in ingredients}


class TestTheCooksSpiceMarkIsPersisted:
    def test_a_marked_piece_is_still_marked_after_the_save(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        created = _create_recipe(
            client,
            auth_headers,
            db_session,
            ingredients=[_bay_leaf(db_session, is_spice=True), _salt(db_session)],
        )
        by_name = _by_name(created['ingredients'])
        assert by_name['Bay leaf']['is_spice'] is True
        # Nothing was marked on the salt; the amount alone will fold it.
        assert by_name['Salt']['is_spice'] is False

        read = client.get(f'{RECIPE_URL}/{created["id"]}', headers=auth_headers)
        assert read.status_code == 200, read.text
        by_name = _by_name(read.json()['ingredients'])
        assert by_name['Bay leaf']['is_spice'] is True

        # The card folds the seasonings section off the availability answer,
        # so the mark has to reach it too.
        availability = client.get(
            f'{RECIPE_URL}/{created["id"]}/availability', headers=auth_headers
        )
        assert availability.status_code == 200, availability.text
        by_name = _by_name(availability.json()['ingredients'])
        assert by_name['Bay leaf']['is_spice'] is True
        assert by_name['Salt']['is_spice'] is False

    def test_an_edit_carries_the_mark_it_was_given(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        created = _create_recipe(
            client,
            auth_headers,
            db_session,
            ingredients=[_bay_leaf(db_session)],
        )
        ingredient = created['ingredients'][0]
        assert ingredient['is_spice'] is False

        updated = client.put(
            f'{RECIPE_URL}/{created["id"]}',
            json={
                'ingredients': [
                    {**_bay_leaf(db_session, is_spice=True), 'id': ingredient['id']}
                ]
            },
            headers=auth_headers,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()['ingredients'][0]['is_spice'] is True

    def test_a_copy_keeps_the_mark(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        created = _create_recipe(
            client,
            auth_headers,
            db_session,
            ingredients=[_bay_leaf(db_session, is_spice=True)],
        )

        copied = client.post(
            f'{RECIPE_URL}/{created["id"]}/duplicate', headers=auth_headers
        )
        assert copied.status_code in (200, 201), copied.text
        assert copied.json()['ingredients'][0]['is_spice'] is True


class TestTheSpiceMarkSurvivesTheJsonRoundTrip:
    """The JSON serializers carry is_optional and allergens; the mark they
    left out is the one the card folds the seasonings section on, so an
    exported recipe came back unmarked."""

    def test_the_export_writes_the_mark_onto_the_exported_piece(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        created = _create_recipe(
            client,
            auth_headers,
            db_session,
            ingredients=[_bay_leaf(db_session, is_spice=True), _salt(db_session)],
        )

        exported = client.get(
            f'{RECIPE_URL}/{created["id"]}/export?format=json',
            headers=auth_headers,
        )
        assert exported.status_code == 200, exported.text
        by_name = _by_name(exported.json()['ingredients'])
        assert by_name['Bay leaf']['is_spice'] is True
        assert by_name['Salt']['is_spice'] is False

    def test_re_importing_the_export_keeps_the_mark(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        created = _create_recipe(
            client,
            auth_headers,
            db_session,
            ingredients=[_bay_leaf(db_session, is_spice=True), _salt(db_session)],
        )
        exported = client.get(
            f'{RECIPE_URL}/{created["id"]}/export?format=json',
            headers=auth_headers,
        )
        assert exported.status_code == 200, exported.text

        imported = client.post(
            f'{RECIPE_URL}/import',
            json={'format': 'json', 'data': exported.json()},
            headers=auth_headers,
        )
        assert imported.status_code == 201, imported.text
        by_name = _by_name(imported.json()['ingredients'])
        assert by_name['Bay leaf']['is_spice'] is True
        assert by_name['Salt']['is_spice'] is False

        # The card folds the seasonings section off the availability
        # answer, so the mark the re-import kept has to reach it too.
        availability = client.get(
            f'{RECIPE_URL}/{imported.json()["id"]}/availability',
            headers=auth_headers,
        )
        assert availability.status_code == 200, availability.text
        by_name = _by_name(availability.json()['ingredients'])
        assert by_name['Bay leaf']['is_spice'] is True
        assert by_name['Salt']['is_spice'] is False
