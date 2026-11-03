"""A stock take works for any location, however many the organization has.

The lookups behind a count used to read the organization's first 2 000
locations and search them, so once there were more, a location past that
point answered "not found" for a shelf that existed and scanned. They now
read the counted location's subtree and its ancestors only.
"""

from __future__ import annotations

import traceback
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.public_api import core_api
from app.core.testing import ModuleTestHelper
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.stock_takes.models import StockTake, StockTakeStatus
from tests.integration._shelf import post_on_shelf

# Past the cap the lookups used to carry.
_BEFORE = 2_050


@pytest.fixture
def large_organization(
    db_session: Session, test_user: User, test_storage_type: StorageType
) -> tuple[StorageLocation, StorageLocation]:
    """2 050 shelves named before the last rack, which holds one shelf of its own."""
    assert test_user.organization_id is not None
    org_id = test_user.organization_id
    db_session.add_all(
        StorageLocation(
            organization_id=org_id,
            created_by=test_user.id,
            storage_type_id=test_storage_type.id,
            name=f'Shelf {number:05d}',
        )
        for number in range(_BEFORE)
    )
    rack = StorageLocation(
        organization_id=org_id,
        created_by=test_user.id,
        storage_type_id=test_storage_type.id,
        name='Zz Rack',
    )
    db_session.add(rack)
    db_session.flush()
    shelf = StorageLocation(
        organization_id=org_id,
        created_by=test_user.id,
        storage_type_id=test_storage_type.id,
        name='Zz Shelf',
        parent_id=rack.id,
    )
    db_session.add(shelf)
    db_session.commit()
    return rack, shelf


@pytest.mark.integration
class TestACountPastTheFirstTwoThousandLocations:
    def test_it_is_created_counted_and_completed(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        large_organization: tuple[StorageLocation, StorageLocation],
    ) -> None:
        rack, shelf = large_organization
        assert test_user.organization_id is not None
        template = ModuleTestHelper(db_session).create_template(
            test_user.organization, name='Late shelf product'
        )
        post_on_shelf(client, auth_headers, template, shelf.id, 5)

        created = client.post(
            '/api/v1/stock-takes',
            headers=auth_headers,
            json={'name': 'Late rack', 'location_id': str(rack.id)},
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        stock_take_id = created.json()['id']
        assert created.json()['items_count'] == 1

        detail = client.get(
            f'/api/v1/stock-takes/{stock_take_id}', headers=auth_headers
        )
        assert detail.status_code == status.HTTP_200_OK
        assert [row['shelf_location'] for row in detail.json()['items']] == [
            'Zz Rack › Zz Shelf'
        ]

        counted = client.patch(
            f'/api/v1/stock-takes/{stock_take_id}/items/{detail.json()["items"][0]["id"]}/count',
            headers=auth_headers,
            json={'counted_quantity': '5'},
        )
        assert counted.status_code == status.HTTP_200_OK, counted.text

        completed = client.post(
            f'/api/v1/stock-takes/{stock_take_id}/complete',
            headers=auth_headers,
            json={'apply_adjustments': True},
        )
        assert completed.status_code == status.HTTP_200_OK, completed.text
        take = db_session.get(StockTake, UUID(stock_take_id))
        assert take is not None
        db_session.refresh(take)
        assert take.status == StockTakeStatus.COMPLETED

    def test_the_count_states_name_the_locations_the_counts_speak_of(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        large_organization: tuple[StorageLocation, StorageLocation],
    ) -> None:
        rack, shelf = large_organization
        created = client.post(
            '/api/v1/stock-takes',
            headers=auth_headers,
            json={'name': 'Late rack', 'location_id': str(rack.id)},
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        states = client.get('/api/v1/stock-takes/locations', headers=auth_headers)

        assert states.status_code == status.HTTP_200_OK
        assert {
            row['location_id']: row['stock_take_id'] for row in states.json()['items']
        } == {
            str(rack.id): created.json()['id'],
            str(shelf.id): created.json()['id'],
        }

    def test_no_stock_take_path_reads_the_organizations_whole_location_list(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        large_organization: tuple[StorageLocation, StorageLocation],
    ) -> None:
        rack, shelf = large_organization
        template = ModuleTestHelper(db_session).create_template(
            test_user.organization, name='Listed nowhere'
        )
        post_on_shelf(client, auth_headers, template, shelf.id, 5)
        ModuleTestHelper(db_session).set_module_settings(
            test_user.organization, 'stock_takes', {'count_every_days': 30}
        )
        listed_by: list[str] = []
        original = core_api.locations.list_async

        async def spy(*args: Any, **kwargs: Any) -> Any:
            callers = [f.filename for f in traceback.extract_stack()]
            if any('/modules/stock_takes/' in name for name in callers):
                listed_by.append(next(n for n in callers if '/stock_takes/' in n))
            return await original(*args, **kwargs)

        with patch.object(core_api.locations, 'list_async', spy):
            created = client.post(
                '/api/v1/stock-takes',
                headers=auth_headers,
                json={'name': 'Late rack', 'location_id': str(rack.id)},
            )
            stock_take_id = created.json()['id']
            client.get(f'/api/v1/stock-takes/{stock_take_id}', headers=auth_headers)
            client.get('/api/v1/stock-takes/locations', headers=auth_headers)
            rows = client.get(
                f'/api/v1/stock-takes/{stock_take_id}/items', headers=auth_headers
            ).json()['items']
            client.patch(
                f'/api/v1/stock-takes/{stock_take_id}/items/{rows[0]["id"]}/count',
                headers=auth_headers,
                json={'counted_quantity': '5'},
            )
            due = client.get(
                '/api/v1/warehouse/todo',
                headers=auth_headers,
                params={'date_to': '2099-01-01', 'limit': 50},
            )
            client.post(
                f'/api/v1/stock-takes/{stock_take_id}/complete',
                headers=auth_headers,
                json={'apply_adjustments': True},
            )

        assert created.status_code == status.HTTP_201_CREATED, created.text
        assert due.status_code == status.HTTP_200_OK, due.text
        assert listed_by == []
