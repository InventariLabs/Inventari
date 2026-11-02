"""A foreign key points at a row; it says nothing about whose row it is.

``create_storage`` looked a supplied ``storage_type_id`` up by primary key
alone, so any UUID that existed anywhere in the installation was accepted --
including another organisation's custom type. ``update_storage`` did not
look it up at all: the field went straight from the payload onto the model.

The right rule is not "must be mine": the type table holds global system
types with ``organization_id`` NULL, and every organisation is meant to use
those. It is "mine or global", and both halves are pinned below -- a guard
that only allowed one's own types would break every seeded shelf.

Nothing leaks back out of this: the shelf renders its type's name, which is
one word chosen by a stranger. The damage is a reference nobody can explain
later, in a table whose owner may delete the row underneath it.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.storage_type import StorageType


class _Neighbours:
    def __init__(self) -> None:
        self.headers: dict[str, str]
        self.own_type_id: str
        self.global_type_id: str
        self.their_type_id: str
        self.storage_id: str


@pytest.fixture
def neighbours(db_session: Session, client: TestClient) -> _Neighbours:
    """Two organisations, one global type, and a shelf to move around."""
    helper = ModuleTestHelper(db_session)
    fixture = _Neighbours()

    mine = helper.create_org('Mine', ['core', 'items', 'locations'])
    theirs = helper.create_org('Theirs', ['core', 'items', 'locations'])
    user = helper.create_user(mine, email='mine@example.com')
    fixture.headers = helper.get_auth_headers(user)

    own_type = StorageType(
        name='My Cupboard', type_code='MY_CUPBOARD', organization_id=mine.id
    )
    their_type = StorageType(
        name='Their Cupboard', type_code='THEIR_CUPBOARD', organization_id=theirs.id
    )
    global_type = StorageType(
        name='Shelf', type_code='SHELF_GLOBAL', organization_id=None, is_system=True
    )
    db_session.add_all([own_type, their_type, global_type])
    db_session.commit()
    for row in (own_type, their_type, global_type):
        db_session.refresh(row)
    fixture.own_type_id = str(own_type.id)
    fixture.their_type_id = str(their_type.id)
    fixture.global_type_id = str(global_type.id)

    created = client.post(
        '/api/v1/locations',
        headers=fixture.headers,
        json={'name': 'Aisle 1', 'location_type_id': fixture.own_type_id},
    )
    assert created.status_code == 201, created.text
    fixture.storage_id = created.json()['id']
    return fixture


@pytest.mark.integration
class TestCreatingAShelf:
    def test_a_type_belonging_to_another_organization_is_refused(
        self, client: TestClient, neighbours: _Neighbours
    ) -> None:
        response = client.post(
            '/api/v1/locations',
            headers=neighbours.headers,
            json={'name': 'Aisle 2', 'location_type_id': neighbours.their_type_id},
        )
        assert response.status_code == 404, response.text

    def test_a_global_type_is_still_accepted(
        self, client: TestClient, neighbours: _Neighbours
    ) -> None:
        response = client.post(
            '/api/v1/locations',
            headers=neighbours.headers,
            json={'name': 'Aisle 3', 'location_type_id': neighbours.global_type_id},
        )
        assert response.status_code == 201, response.text
        assert response.json()['location_type_id'] == neighbours.global_type_id

    def test_a_type_that_exists_nowhere_is_refused(
        self, client: TestClient, neighbours: _Neighbours
    ) -> None:
        response = client.post(
            '/api/v1/locations',
            headers=neighbours.headers,
            json={
                'name': 'Aisle 4',
                'location_type_id': '00000000-0000-0000-0000-0000000000ff',
            },
        )
        assert response.status_code == 404, response.text


@pytest.mark.integration
class TestEditingAShelf:
    def test_a_type_belonging_to_another_organization_is_refused(
        self, client: TestClient, neighbours: _Neighbours
    ) -> None:
        response = client.put(
            f'/api/v1/locations/{neighbours.storage_id}',
            headers=neighbours.headers,
            json={'location_type_id': neighbours.their_type_id},
        )
        assert response.status_code == 404, response.text

    def test_the_shelf_keeps_the_type_it_had(
        self, client: TestClient, neighbours: _Neighbours
    ) -> None:
        client.put(
            f'/api/v1/locations/{neighbours.storage_id}',
            headers=neighbours.headers,
            json={'location_type_id': neighbours.their_type_id},
        )
        after = client.get(
            f'/api/v1/locations/{neighbours.storage_id}', headers=neighbours.headers
        )
        assert after.status_code == 200
        assert after.json()['location_type_id'] == neighbours.own_type_id

    def test_moving_to_a_global_type_still_works(
        self, client: TestClient, neighbours: _Neighbours
    ) -> None:
        response = client.put(
            f'/api/v1/locations/{neighbours.storage_id}',
            headers=neighbours.headers,
            json={'location_type_id': neighbours.global_type_id},
        )
        assert response.status_code == 200, response.text
        assert response.json()['location_type_id'] == neighbours.global_type_id
