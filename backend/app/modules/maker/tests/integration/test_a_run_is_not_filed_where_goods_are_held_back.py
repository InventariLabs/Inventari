"""A run's output goes where goods are kept, not where they wait or are held.

The warehouse sets two kinds of place apart: a receiving area and the
quarantine location. Stock a run made there would sit where picking does not
look, so the planned run, the run recorded after the fact and the location
list a picker reads all treat them as places goods are not kept in.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User

from .conftest import _make_template

pytestmark = pytest.mark.integration

WAREHOUSE_API = '/api/v1/warehouse'
ORDERS = '/api/v1/maker/production/orders'


@pytest.fixture
def org(h: ModuleTestHelper) -> Organization:
    return h.create_org(
        'Held Back Org',
        ['core', 'items', 'locations', 'categories', 'stats', 'maker', 'warehouse'],
    )


@pytest.fixture
def user(h: ModuleTestHelper, org: Organization) -> User:
    return h.create_user(org, email='heldback@example.com')


@pytest.fixture
def headers(h: ModuleTestHelper, user: User) -> dict[str, str]:
    return h.get_auth_headers(user)


@pytest.fixture
def storage_type(h: ModuleTestHelper) -> StorageType:
    return h.create_storage_type('Dry Store', 'DRY_STORE')


def _location(
    h: ModuleTestHelper,
    db: Session,
    org: Organization,
    storage_type: StorageType,
    user: User,
    name: str,
    parent: StorageLocation | None = None,
) -> StorageLocation:
    location = h.create_storage_location(org, storage_type, user, name=name)
    if parent is not None:
        location.parent_id = parent.id
        db.commit()
    return location


@pytest.fixture
def warehouse(
    h: ModuleTestHelper,
    db_session: Session,
    org: Organization,
    storage_type: StorageType,
    user: User,
) -> StorageLocation:
    return _location(h, db_session, org, storage_type, user, 'Main warehouse')


@pytest.fixture
def shelf(
    h: ModuleTestHelper,
    db_session: Session,
    org: Organization,
    storage_type: StorageType,
    user: User,
    warehouse: StorageLocation,
) -> StorageLocation:
    return _location(h, db_session, org, storage_type, user, 'Shelf', warehouse)


@pytest.fixture
def quarantine(
    client: TestClient,
    headers: dict[str, str],
    h: ModuleTestHelper,
    db_session: Session,
    org: Organization,
    storage_type: StorageType,
    user: User,
    warehouse: StorageLocation,
) -> StorageLocation:
    location = _location(
        h, db_session, org, storage_type, user, 'Quarantine', warehouse
    )
    named = client.put(
        f'{WAREHOUSE_API}/profile',
        headers=headers,
        json={'quarantine_location_id': str(location.id)},
    )
    assert named.status_code == 200, named.text
    return location


@pytest.fixture
def receiving_area(
    client: TestClient, headers: dict[str, str], warehouse: StorageLocation
) -> UUID:
    resp = client.put(
        f'{WAREHOUSE_API}/putaway/receiving-modes/{warehouse.id}',
        headers=headers,
        json={'two_step': True},
    )
    assert resp.status_code == 200, resp.text
    return UUID(resp.json()['receiving_location_id'])


def _order(
    client: TestClient,
    headers: dict[str, str],
    db: Session,
    org: Organization,
    where: UUID,
    *,
    made: bool = False,
) -> Any:
    template = _make_template(db, org, name='Held back product')
    return client.post(
        f'{ORDERS}/made' if made else ORDERS,
        headers=headers,
        json={
            'output_template_id': str(template.id),
            'planned_qty': '3',
            'output_location_id': str(where),
        },
    )


class TestARunIsNotFiledWhereGoodsAreHeldBack:
    @pytest.mark.parametrize('made', [False, True])
    def test_the_quarantine_location_is_refused_with_its_reason(
        self,
        client: TestClient,
        headers: dict[str, str],
        db_session: Session,
        org: Organization,
        quarantine: StorageLocation,
        made: bool,
    ) -> None:
        resp = _order(client, headers, db_session, org, quarantine.id, made=made)

        assert resp.status_code == 400, resp.text
        assert resp.json()['detail']['message'].startswith(
            'A quarantine location cannot take what a production run makes'
        )

    @pytest.mark.parametrize('made', [False, True])
    def test_a_receiving_area_is_refused_with_its_reason(
        self,
        client: TestClient,
        headers: dict[str, str],
        db_session: Session,
        org: Organization,
        receiving_area: UUID,
        made: bool,
    ) -> None:
        resp = _order(client, headers, db_session, org, receiving_area, made=made)

        assert resp.status_code == 400, resp.text
        assert resp.json()['detail']['message'].startswith(
            'A receiving area cannot take what a production run makes'
        )

    def test_a_shelf_passes_on_to_the_next_question(
        self,
        client: TestClient,
        headers: dict[str, str],
        db_session: Session,
        org: Organization,
        shelf: StorageLocation,
        quarantine: StorageLocation,
    ) -> None:
        resp = _order(client, headers, db_session, org, shelf.id)

        # The product has no recipe: the refusal is the next one, so the
        # location itself was accepted.
        assert resp.status_code == 400, resp.text
        assert resp.json()['detail']['message'].startswith('No BOM for this product')


class TestThePickerListIsKeptClean:
    def _names(
        self, client: TestClient, headers: dict[str, str], **params: Any
    ) -> set[str]:
        resp = client.get(
            '/api/v1/locations', headers=headers, params={'limit': 200, **params}
        )
        assert resp.status_code == 200, resp.text
        return {row['name'] for row in resp.json()['items']}

    def test_held_back_places_are_left_out_when_asked(
        self,
        client: TestClient,
        headers: dict[str, str],
        shelf: StorageLocation,
        quarantine: StorageLocation,
        receiving_area: UUID,
    ) -> None:
        everything = self._names(client, headers)
        kept = self._names(client, headers, exclude_held_back='true')

        assert {'Shelf', 'Quarantine'} <= everything
        assert 'Shelf' in kept
        assert 'Quarantine' not in kept
        assert len(everything - kept) == 2
