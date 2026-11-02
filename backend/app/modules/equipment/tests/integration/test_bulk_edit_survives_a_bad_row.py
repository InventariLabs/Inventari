"""One asset's failure must not take the batch down with it.

``bulk_edit_items`` catches a database error per item and carries on, which
reads like the docstring's promise — "one item's refusal never stops the
batch". It was not one. A failed statement poisons the transaction: every
later ``execute`` raises ``PendingRollbackError``, which is itself a
``SQLAlchemyError`` and so landed in the same handler looking like one more
rejected row, and the closing ``commit()`` then failed outright. The caller
got a 500 and lost the assets that had gone through.

The second half is what the failure said. ``str(exc)`` on a database error
carries the statement that failed, so a fragment of SQL travelled to the
browser — not the reader's to see, and not theirs to fix.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.modules.equipment import bulk_service


@pytest.fixture
def eq_second_item(
    db_session: Session,
    eq_org: Organization,
    eq_storage_location: StorageLocation,
    eq_category: Category,
) -> Item:
    """A second asset, so the batch has something left to lose."""
    item = Item(
        name='ThinkPad T14',
        organization_id=eq_org.id,
        storage_location_id=eq_storage_location.id,
        category_id=eq_category.id,
        quantity=1,
        meta_data={
            'equipment': {'serial_number': 'SN-002', 'equipment_status': 'AVAILABLE'}
        },
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def _break_on(monkeypatch: pytest.MonkeyPatch, item_id: Any) -> None:
    """Make ``change_status`` hit a real failing statement for one asset.

    A raised exception alone would not reproduce this: what took the batch
    down was the *transaction* the failed statement left behind. So the fake
    runs a division by zero in the database, exactly as a constraint
    violation would.
    """
    original = bulk_service._BULK_ACTIONS['change_status']

    async def _sometimes_breaks(db, org_id, item, data, user_id, **kwargs):  # type: ignore[no-untyped-def]
        if item.id == item_id:
            await db.execute(text('SELECT 1 / 0'))
        await original(db, org_id, item, data, user_id, **kwargs)

    monkeypatch.setitem(bulk_service._BULK_ACTIONS, 'change_status', _sometimes_breaks)


@pytest.mark.integration
class TestABadRowIsOneRow:
    def test_the_rest_of_the_batch_is_saved(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        eq_second_item: Item,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _break_on(monkeypatch, eq_item.id)

        response = client.patch(
            '/api/v1/equipment/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(eq_item.id), str(eq_second_item.id)],
                'action': 'change_status',
                'data': {'status': 'MAINTENANCE'},
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        body = response.json()
        assert body['updated'] == 1
        assert len(body['errors']) == 1
        assert body['errors'][0]['item_id'] == str(eq_item.id)

        db_session.expire_all()
        db_session.refresh(eq_second_item)
        assert eq_second_item.meta_data is not None
        assert (
            eq_second_item.meta_data['equipment']['equipment_status'] == 'MAINTENANCE'
        )

    def test_the_asset_that_broke_is_left_as_it_was(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        eq_second_item: Item,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _break_on(monkeypatch, eq_item.id)

        client.patch(
            '/api/v1/equipment/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(eq_item.id), str(eq_second_item.id)],
                'action': 'change_status',
                'data': {'status': 'MAINTENANCE'},
            },
        )

        db_session.expire_all()
        db_session.refresh(eq_item)
        assert eq_item.meta_data is not None
        assert eq_item.meta_data['equipment']['equipment_status'] == 'AVAILABLE'

    def test_the_failure_does_not_quote_sql_at_the_reader(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        eq_second_item: Item,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _break_on(monkeypatch, eq_item.id)

        response = client.patch(
            '/api/v1/equipment/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(eq_item.id), str(eq_second_item.id)],
                'action': 'change_status',
                'data': {'status': 'MAINTENANCE'},
            },
        )

        message = response.json()['errors'][0]['error']
        assert 'SELECT' not in message.upper()
        assert 'division by zero' not in message.lower()
        assert message.strip() != ''

    def test_a_domain_refusal_still_says_what_is_wrong(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        # The technical message is hidden; the one a person can act on is not.
        response = client.patch(
            '/api/v1/equipment/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(eq_item.id)],
                'action': 'change_status',
                'data': {'status': 'DEPLOYED'},
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        body = response.json()
        assert body['updated'] == 0
        assert len(body['errors']) == 1
        assert body['errors'][0]['code'] == 'EQUIPMENT_DEPLOY_REQUIRES_CHECKOUT'
        assert 'checking it out' in body['errors'][0]['error']

    def test_a_library_error_is_not_echoed_in_the_row(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        # ``uuid.UUID('invalid-uuid')`` raises a library ``ValueError``; its
        # words are for a programmer, so the row gets the generic sentence.
        response = client.patch(
            '/api/v1/equipment/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(eq_item.id)],
                'action': 'change_location',
                'data': {'location_id': 'invalid-uuid'},
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        body = response.json()
        assert body['updated'] == 0
        message = body['errors'][0]['error']
        assert 'hexadecimal' not in message.lower()
        assert message.strip() != ''
