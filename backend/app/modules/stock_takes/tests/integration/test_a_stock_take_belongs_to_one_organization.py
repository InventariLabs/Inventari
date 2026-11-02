"""A stock take, its rows and its counts answer to one organization only.

This module had no cross-organization test at all, and it is the worst place
in the tree to be missing one: ``stock_take_items`` and ``stock_take_counts``
carry no ``organization_id`` column of their own. Their isolation is
inherited through a foreign key to the parent stock take, which means every
route reaching a row by id depends on the parent being fetched with the
caller's organization -- and nothing measured that.

The stranger here is a real organization with its own user, its own storage
and its own stock take, created through the same API. Each test then asks
one route for the stranger's id and expects to be told it does not exist.

What each test fails on, measured by removing the filter and re-running:

- ``get_stock_take_or_404`` (the parent lookup): eight of the eleven go red.
- ``list_stock_takes_filtered`` / ``get_stock_take_item_or_404``: the list
  test goes red on the first, and nothing else -- the row-level tests are
  covered twice over and stay green while either half stands.
- Both removed at once: all eleven go red. That is the honest statement of
  what this file measures.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User

_MODULES = ['core', 'items', 'locations', 'stock_takes']


@pytest.fixture
def helper(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def stranger_org(helper: ModuleTestHelper) -> Organization:
    return helper.create_org('Strangers Counting Inc', _MODULES)


@pytest.fixture
def stranger_user(helper: ModuleTestHelper, stranger_org: Organization) -> User:
    return helper.create_user(stranger_org, email='counter@strangers.example')


@pytest.fixture
def stranger_headers(helper: ModuleTestHelper, stranger_user: User) -> dict[str, str]:
    return helper.get_auth_headers(stranger_user)


@pytest.fixture
def stranger_storage(
    helper: ModuleTestHelper, stranger_org: Organization, stranger_user: User
) -> StorageLocation:
    storage_type = helper.create_storage_type(
        'Stranger Shelf', 'STRANGER_SHELF', organization_id=stranger_org.id
    )
    return helper.create_storage_location(
        stranger_org, storage_type, stranger_user, name='Their Back Room'
    )


@pytest.fixture
def stranger_item(
    db_session: Session,
    stranger_org: Organization,
    stranger_storage: StorageLocation,
) -> Item:
    """Something on the stranger's shelf, so their stock take has a row."""
    item = Item(
        name='Their Widget',
        organization_id=stranger_org.id,
        storage_location_id=stranger_storage.id,
        quantity=3,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


@pytest.fixture
def stranger_stock_take(
    client: TestClient,
    stranger_headers: dict[str, str],
    stranger_storage: StorageLocation,
    stranger_item: Item,
) -> dict[str, Any]:
    """A stock take that exists, and belongs to somebody else."""
    response = client.post(
        '/api/v1/stock-takes',
        headers=stranger_headers,
        json={
            'name': 'Their Quarterly Count',
            'location_id': str(stranger_storage.id),
        },
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    created: dict[str, Any] = response.json()
    return created


@pytest.mark.integration
class TestReadingSomebodyElsesStockTake:
    def test_the_detail_route_does_not_find_it(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        stranger_stock_take: dict[str, Any],
    ) -> None:
        response = client.get(
            f'/api/v1/stock-takes/{stranger_stock_take["id"]}', headers=auth_headers
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.text

    def test_the_rows_route_does_not_find_it(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        stranger_stock_take: dict[str, Any],
    ) -> None:
        response = client.get(
            f'/api/v1/stock-takes/{stranger_stock_take["id"]}/items',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.text

    def test_the_report_route_does_not_find_it(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        stranger_stock_take: dict[str, Any],
    ) -> None:
        response = client.get(
            f'/api/v1/stock-takes/{stranger_stock_take["id"]}/report',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.text

    def test_the_list_route_shows_none_of_it(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        stranger_stock_take: dict[str, Any],
    ) -> None:
        response = client.get('/api/v1/stock-takes', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK, response.text
        ids = {row['id'] for row in response.json()['items']}
        assert stranger_stock_take['id'] not in ids


@pytest.mark.integration
class TestWritingToSomebodyElsesStockTake:
    def test_it_cannot_be_renamed(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        stranger_stock_take: dict[str, Any],
    ) -> None:
        response = client.put(
            f'/api/v1/stock-takes/{stranger_stock_take["id"]}',
            headers=auth_headers,
            json={'name': 'Mine now'},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.text

    def test_its_status_cannot_be_changed(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        stranger_stock_take: dict[str, Any],
    ) -> None:
        response = client.patch(
            f'/api/v1/stock-takes/{stranger_stock_take["id"]}/status',
            headers=auth_headers,
            json={'status': 'cancelled'},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.text

    def test_it_cannot_be_deleted(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        stranger_stock_take: dict[str, Any],
    ) -> None:
        response = client.delete(
            f'/api/v1/stock-takes/{stranger_stock_take["id"]}', headers=auth_headers
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.text

    def test_it_cannot_be_completed(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        stranger_stock_take: dict[str, Any],
    ) -> None:
        response = client.post(
            f'/api/v1/stock-takes/{stranger_stock_take["id"]}/complete',
            headers=auth_headers,
            json={},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.text

    def test_a_row_of_it_cannot_be_counted(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        stranger_headers: dict[str, str],
        stranger_stock_take: dict[str, Any],
    ) -> None:
        """The row-level routes are the ones with no org column to fall back on.

        ``stock_take_items`` has no ``organization_id``; the only thing
        standing between this id and a stranger writing a count onto it is
        the parent lookup at the top of the route.
        """
        rows = client.get(
            f'/api/v1/stock-takes/{stranger_stock_take["id"]}/items',
            headers=stranger_headers,
        )
        assert rows.status_code == status.HTTP_200_OK, rows.text
        assert rows.json(), 'the stranger stock take should have counted its shelf'
        row_id = rows.json()['items'][0]['id']

        response = client.patch(
            f'/api/v1/stock-takes/{stranger_stock_take["id"]}/items/{row_id}/count',
            headers=auth_headers,
            json={'counted_quantity': 999},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.text

    def test_a_row_of_it_cannot_be_recounted(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        stranger_headers: dict[str, str],
        stranger_stock_take: dict[str, Any],
    ) -> None:
        rows = client.get(
            f'/api/v1/stock-takes/{stranger_stock_take["id"]}/items',
            headers=stranger_headers,
        )
        row_id = rows.json()['items'][0]['id']

        response = client.post(
            f'/api/v1/stock-takes/{stranger_stock_take["id"]}/items/{row_id}/recount',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.text

    def test_its_rows_cannot_be_bulk_counted(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        stranger_headers: dict[str, str],
        stranger_stock_take: dict[str, Any],
    ) -> None:
        rows = client.get(
            f'/api/v1/stock-takes/{stranger_stock_take["id"]}/items',
            headers=stranger_headers,
        )
        row_id = rows.json()['items'][0]['id']

        response = client.patch(
            f'/api/v1/stock-takes/{stranger_stock_take["id"]}/items/bulk-count',
            headers=auth_headers,
            json=[{'item_id': row_id, 'counted_quantity': 5}],
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.text
