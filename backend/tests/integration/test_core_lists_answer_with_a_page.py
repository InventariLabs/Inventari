"""A Core list answers with a page: ``items`` plus how to ask for the rest.

The lists under ``app/api`` answered with a bare JSON array: no page size, no
total, nothing a client could follow. They now answer with the documented
``PaginatedResponse`` (``docs/subsystems/PAGINATION.md``). Two kinds are
pinned here — a small list sliced in memory (the categories) and a growing one
paged in the database (the notifications) — because they reach the envelope
by different roads and either can get ``total`` or ``has_more`` wrong.
"""

import pytest
from fastapi import status

from app.models.category import Category
from app.models.notification import Notification


def _categories(db_session, organization_id, count):
    for i in range(count):
        db_session.add(
            Category(
                name=f'Paged category {i}',
                code=f'paged_{i}',
                organization_id=organization_id,
                sort_order=i,
            )
        )
    db_session.commit()


def _page(client, auth_headers, path, **params):
    response = client.get(path, headers=auth_headers, params=params)
    assert response.status_code == status.HTTP_200_OK, response.text
    return response.json()


@pytest.mark.integration
class TestASmallListIsSlicedWithItsTrueTotal:
    def test_the_first_page_says_there_is_more(
        self, client, auth_headers, db_session, test_household
    ):
        _categories(db_session, test_household.id, 3)
        whole = _page(client, auth_headers, '/api/v1/categories')['total']

        page = _page(client, auth_headers, '/api/v1/categories', limit=2)

        assert len(page['items']) == 2
        assert page['total'] == whole
        assert (page['limit'], page['offset']) == (2, 0)
        assert page['has_more'] is True

    def test_the_pages_together_hold_every_row_once(
        self, client, auth_headers, db_session, test_household
    ):
        _categories(db_session, test_household.id, 3)
        whole = _page(client, auth_headers, '/api/v1/categories')

        ids = []
        offset = 0
        while True:
            page = _page(
                client, auth_headers, '/api/v1/categories', limit=2, offset=offset
            )
            ids += [row['id'] for row in page['items']]
            if not page['has_more']:
                break
            offset += 2

        assert ids == [row['id'] for row in whole['items']]

    def test_a_page_larger_than_the_cap_is_refused(self, client, auth_headers):
        response = client.get(
            '/api/v1/categories', headers=auth_headers, params={'limit': 201}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.integration
class TestAGrowingListIsPagedInTheDatabase:
    def test_the_notifications_count_every_row_and_serve_one_page(
        self, client, auth_headers, db_session, test_user
    ):
        for i in range(5):
            db_session.add(
                Notification(user_id=test_user.id, title=f'N{i}', content='C')
            )
        db_session.commit()

        first = _page(client, auth_headers, '/api/v1/notifications', limit=2)
        last = _page(client, auth_headers, '/api/v1/notifications', limit=2, offset=4)

        assert first['total'] == last['total'] == 5
        assert len(first['items']) == 2
        assert first['has_more'] is True
        assert len(last['items']) == 1
        assert last['has_more'] is False
