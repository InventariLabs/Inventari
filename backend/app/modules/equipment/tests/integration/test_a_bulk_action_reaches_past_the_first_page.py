"""A bulk action described by the list's filters, not by a page of ids.

"Select page" told the truth about its reach, and the reader who wanted to
archive all 61 assets matching a filter still had to do it page by page. The
endpoints under ``/equipment/assets/matching`` take the same filters as the
list and act on everything that matches — with a ceiling, because one HTTP
request is the wrong place for several thousand rows.
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
ARCHIVE_URL = '/api/v1/items/archived'


def _add_asset(
    db_session: Session,
    org: Organization,
    location: StorageLocation,
    category: Category,
    name: str,
    *,
    status: str = 'AVAILABLE',
) -> Item:
    item = Item(
        name=name,
        organization_id=org.id,
        storage_location_id=location.id,
        category_id=category.id,
        quantity=1,
        meta_data={'equipment': {'equipment_status': status}},
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


@pytest.fixture
def three_assets(
    db_session: Session,
    eq_org: Organization,
    eq_storage_location: StorageLocation,
    eq_category: Category,
) -> list[Item]:
    return [
        _add_asset(db_session, eq_org, eq_storage_location, eq_category, 'Laptop A'),
        _add_asset(db_session, eq_org, eq_storage_location, eq_category, 'Laptop B'),
        _add_asset(
            db_session,
            eq_org,
            eq_storage_location,
            eq_category,
            'Laptop C',
            status='MAINTENANCE',
        ),
    ]


@pytest.mark.integration
class TestArchiveEverythingThatMatches:
    def test_the_action_reaches_rows_the_first_page_does_not_show(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        three_assets: list[Item],
    ) -> None:
        page = client.get(
            ASSETS_URL, headers=eq_auth_headers, params={'limit': 1}
        ).json()
        assert len(page['items']) == 1
        assert page['total'] == 3

        resp = client.post(
            f'{ASSETS_URL}/matching/archive', headers=eq_auth_headers, json={}
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {'archived': 3, 'errors': []}
        after = client.get(ASSETS_URL, headers=eq_auth_headers).json()
        assert after['total'] == 0

    def test_the_filter_narrows_what_the_action_touches(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        three_assets: list[Item],
        db_session: Session,
    ) -> None:
        resp = client.post(
            f'{ASSETS_URL}/matching/archive',
            headers=eq_auth_headers,
            json={'status': 'MAINTENANCE'},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()['archived'] == 1
        for item in three_assets:
            db_session.refresh(item)
        assert [i.is_deleted for i in three_assets] == [False, False, True]

    def test_too_many_matches_are_refused_before_anything_changes(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        three_assets: list[Item],
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr('app.modules.equipment._router_bulk.BULK_FILTER_CEILING', 2)

        resp = client.post(
            f'{ASSETS_URL}/matching/archive', headers=eq_auth_headers, json={}
        )

        assert resp.status_code == 422, resp.text
        detail = resp.json()['detail']
        assert detail['code'] == 'BULK_SCOPE_TOO_LARGE'
        assert detail['matched'] == 3
        assert detail['limit'] == 2
        assert '3' in detail['message'] and '2' in detail['message']
        for item in three_assets:
            db_session.refresh(item)
        assert not any(i.is_deleted for i in three_assets)

    def test_the_archive_holds_every_asset_the_action_archived(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """What the reader archived is what the reader can find afterwards.

        Assets saved without a category — the form never required one — went
        into the archive and out of the module's sight: the Archive tab asked
        the category alone, so it showed none of the 60 rows the bulk action
        had just removed, and nothing inside the module could restore them.
        """
        for name in ('Uncategorised A', 'Uncategorised B'):
            db_session.add(
                Item(
                    name=name,
                    organization_id=eq_org.id,
                    storage_location_id=eq_storage_location.id,
                    category_id=None,
                    module_name='equipment',
                    quantity=1,
                    meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
                )
            )
        db_session.commit()

        archived = client.post(
            f'{ASSETS_URL}/matching/archive', headers=eq_auth_headers, json={}
        ).json()['archived']

        assert archived == 2
        assert client.get(ASSETS_URL, headers=eq_auth_headers).json()['total'] == 0
        archive = client.get(
            ARCHIVE_URL, headers=eq_auth_headers, params={'module_scope': 'equipment'}
        ).json()
        assert archive['total'] == archived
        assert {i['name'] for i in archive['items']} == {
            'Uncategorised A',
            'Uncategorised B',
        }


@pytest.mark.integration
class TestRetireEverythingThatMatches:
    def test_retire_by_filter_sets_the_status_on_every_match(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        three_assets: list[Item],
        db_session: Session,
    ) -> None:
        resp = client.post(
            f'{ASSETS_URL}/matching/retire',
            headers=eq_auth_headers,
            json={'search': 'Laptop'},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {'retired': 3, 'errors': []}
        for item in three_assets:
            db_session.refresh(item)
            assert (item.meta_data or {})['equipment']['equipment_status'] == 'RETIRED'
