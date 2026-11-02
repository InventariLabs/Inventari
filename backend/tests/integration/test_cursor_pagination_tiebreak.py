"""Regression tests for cursor pagination tie-breaker.

Rows sharing an identical created_at (bulk imports, seeded data) used to
be skipped or returned twice when paginating /items/cursor-page, because
the keyset predicate compared only ``created_at < cursor_ts``. The cursor
now carries (id, created_at) and the predicate uses both.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.models.item import Item
from app.services.token_service import create_access_token

pytestmark = pytest.mark.integration


def _headers(user) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


def _make_item(db_session, user, storage, *, name: str, created_at) -> Item:
    item = Item(
        id=uuid.uuid4(),
        organization_id=user.organization_id,
        storage_location_id=storage.id,
        name=name,
        quantity=1,
        created_at=created_at,
    )
    db_session.add(item)
    return item


class TestCursorPaginationTieBreaker:
    def test_same_timestamp_rows_are_not_skipped_across_pages(
        self, client, db_session, test_user, test_storage_location
    ):
        same_ts = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
        items = [
            _make_item(
                db_session,
                test_user,
                test_storage_location,
                name=f'Bulk {i}',
                created_at=same_ts,
            )
            for i in range(5)
        ]
        db_session.commit()
        expected_ids = {str(i.id) for i in items}

        collected: list[str] = []
        cursor = None
        for _ in range(10):  # safety bound against an infinite loop
            params: dict = {'limit': 2}
            if cursor:
                params['cursor'] = cursor
            resp = client.get(
                '/api/v1/items/cursor-page',
                params=params,
                headers=_headers(test_user),
            )
            assert resp.status_code == 200
            body = resp.json()
            collected.extend(i['id'] for i in body['items'])
            cursor = body['next_cursor']
            if not body['has_more']:
                break

        assert len(collected) == len(set(collected)), 'duplicate rows across pages'
        assert expected_ids <= set(collected), 'rows with tied created_at were skipped'

    def test_invalid_cursor_returns_400(
        self, client, db_session, test_user, test_storage_location
    ):
        # Legacy pipe format must be rejected, not silently mis-decoded.
        legacy = f'{uuid.uuid4()}|2026-07-01T12:00:00+00:00'
        resp = client.get(
            '/api/v1/items/cursor-page',
            params={'cursor': legacy},
            headers=_headers(test_user),
        )
        assert resp.status_code == 400
