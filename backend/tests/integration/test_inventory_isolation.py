"""Multi-tenant isolation tests for the inventory core (Suite A).

Every read/mutate endpoint on items must be scoped to the caller's
organization.  These tests create a second org (with its own storage +
item) and assert the first org's user can neither list, read, nor mutate
the second org's resources.

The cursor-page case (``test_cursor_page_does_not_leak_cross_org_when_no_storages``)
is a regression guard for the historical cross-org leak, fixed in commit 77351f9e:
the org filter is now applied unconditionally, not only via ``storage_ids``
(which is empty when a user belongs to no storage location).
"""

from __future__ import annotations

import pytest

from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.services.token_service import create_access_token

from ._core_api_helpers import make_other_org, make_user


def _token_headers(user_id) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user_id)})}'
    }


def _seed_other_org_item(
    db_session,
    storage_type,
    *,
    item_name: str = 'Secret Other Org Item',
):
    """Create a second org with one storage location + one item. Commits."""
    other_org = make_other_org(db_session)
    other_user = make_user(db_session, 'other-org@example.com', other_org.id)
    location = StorageLocation(
        organization_id=other_org.id,
        created_by=other_user.id,
        storage_type_id=storage_type.id,
        name='Other Org Loc',
        description='d',
        location_details='x',
    )
    db_session.add(location)
    db_session.commit()
    db_session.refresh(location)
    item = Item(
        organization_id=other_org.id,
        storage_location_id=location.id,
        name=item_name,
        quantity=7,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return other_org, other_user, location, item


@pytest.mark.integration
class TestInventoryTenantIsolation:
    """A user in org A must never see or touch org B's inventory."""

    def test_cursor_page_does_not_leak_cross_org_when_no_storages(
        self, client, db_session, test_user, test_storage_type
    ):
        # org A (test_user) has NO storage locations -> user_storage_ids == [].
        # Regression guard: the org filter must apply unconditionally,
        # not only via storage_ids (which is skipped when empty).
        _, _, _, other_item = _seed_other_org_item(db_session, test_storage_type)
        resp = client.get(
            '/api/v1/items/cursor-page', headers=_token_headers(test_user.id)
        )
        assert resp.status_code == 200
        ids = [i['id'] for i in resp.json()['items']]
        assert str(other_item.id) not in ids, (
            'cross-tenant leak: /items/cursor-page returned another org item'
        )

    def test_main_list_excludes_other_org(
        self,
        client,
        db_session,
        test_user,
        test_storage_location,
        test_item,
        test_storage_type,
    ):
        _, _, _, other_item = _seed_other_org_item(db_session, test_storage_type)
        resp = client.get('/api/v1/items', headers=_token_headers(test_user.id))
        assert resp.status_code == 200
        ids = [i['id'] for i in resp.json()['items']]
        assert str(other_item.id) not in ids

    def test_get_item_by_id_returns_404_for_other_org(
        self, client, db_session, test_user, test_storage_type
    ):
        _, _, _, other_item = _seed_other_org_item(db_session, test_storage_type)
        resp = client.get(
            f'/api/v1/items/{other_item.id}',
            headers=_token_headers(test_user.id),
        )
        assert resp.status_code == 404

    def test_history_feed_excludes_other_org(
        self,
        client,
        db_session,
        test_user,
        test_storage_location,
        test_item,
        test_storage_type,
    ):
        _, _, _, other_item = _seed_other_org_item(db_session, test_storage_type)
        resp = client.get('/api/v1/items/history', headers=_token_headers(test_user.id))
        assert resp.status_code == 200
        item_ids = [e['item_id'] for e in resp.json()['items']]
        assert str(other_item.id) not in item_ids

    def test_quantity_update_on_other_org_item_returns_404(
        self, client, db_session, test_user, test_storage_type
    ):
        _, _, _, other_item = _seed_other_org_item(db_session, test_storage_type)
        resp = client.patch(
            f'/api/v1/items/{other_item.id}/quantity',
            json={'quantity': 99},
            headers=_token_headers(test_user.id),
        )
        assert resp.status_code == 404
