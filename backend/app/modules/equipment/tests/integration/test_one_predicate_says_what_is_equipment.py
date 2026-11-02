"""The count on a location and the list behind it ask one question.

Two predicates used to answer "is this record equipment": the core's
``claimed_by_module`` (which lists the module's locations and counts the
row) and the module's own marker list. They disagreed in both directions,
and both promises are ones a user can check:

- a location whose row said "1 asset" opened a list with nothing in it;
- a location holding an asset the module could list had no count and no
  link at all — the way in disappeared exactly where the content was.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation

ASSETS_URL = '/api/v1/equipment/assets'
STORAGES_URL = '/api/v1/locations'


def _row_count(client: TestClient, headers: dict[str, str], name: str) -> int | None:
    resp = client.get(f'{STORAGES_URL}?module_scope=equipment', headers=headers)
    assert resp.status_code == 200, resp.text
    for row in resp.json()['items']:
        if row['name'] == name:
            count = row.get('items_count')
            return int(count) if count is not None else None
    return None


def _list_count(client: TestClient, headers: dict[str, str], location_id: str) -> int:
    resp = client.get(
        f'{ASSETS_URL}?location_id={location_id}&limit=100', headers=headers
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()['total'])


@pytest.mark.integration
class TestTheRowAndTheListAgree:
    def test_a_record_under_an_ordinary_category_is_outside_the_module_on_both(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        db_session: Session,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
    ) -> None:
        """The category speaks first — and now it speaks to both surfaces.

        The module's own list used to show this record while the location
        holding it was missing from the module's locations entirely: a row
        the user could reach from the list and not from the map.
        """
        ordinary = Category(
            name='Cheese', code='CHEESE', context_tag=None, organization_id=eq_org.id
        )
        db_session.add(ordinary)
        db_session.commit()
        db_session.refresh(ordinary)
        db_session.add(
            Item(
                name='Refiled drill',
                organization_id=eq_org.id,
                storage_location_id=eq_storage_location.id,
                category_id=ordinary.id,
                quantity=1,
                module_name='equipment',
                meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
            )
        )
        db_session.commit()

        assert _list_count(client, eq_auth_headers, str(eq_storage_location.id)) == 0
        assert _row_count(client, eq_auth_headers, eq_storage_location.name) in (
            None,
            0,
        )

    def test_a_record_the_row_counts_is_a_record_the_list_shows(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        db_session: Session,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
    ) -> None:
        """The other direction: an uncategorised record the core counted for
        the module was missing from the module's own list, so the row
        promised an asset the list could not produce."""
        db_session.add(
            Item(
                name='Uncategorised drill',
                organization_id=eq_org.id,
                storage_location_id=eq_storage_location.id,
                quantity=1,
                module_name='equipment',
            )
        )
        db_session.commit()

        assert _row_count(client, eq_auth_headers, eq_storage_location.name) == 1
        assert _list_count(client, eq_auth_headers, str(eq_storage_location.id)) == 1
