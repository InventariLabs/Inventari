"""The organization journal pages by the last entry the reader saw.

``GET /api/v1/audit-log`` paged with ``OFFSET`` and ran a ``COUNT(*)`` for every
page, so the hundredth page cost a hundred pages and the figure was taken again
each time the reader turned one. It now hands back a ``next_cursor`` that names
the last entry, the next request starts below it, and the count is taken on the
first page and carried in the cursor — the same way the movement ledger pages
(``test_the_ledger_pages_by_the_last_row.py``).

What these tests hold the endpoint to:

- walking the cursor visits every entry exactly once, newest first, including
  entries that share one instant — a batch writes its rows together, so ties
  are the ordinary case here and not a corner;
- the figure the reader sees does not move between pages;
- a cursor is a position and nothing more: a forged one is refused and another
  organization's entries stay out of reach;
- the list of target types the screen offers is still exactly the types the log
  holds, once each and in order, now that it is read by walking an index.

The shape of the work — a deep page costing what the first costs, the list of
types reading one index entry per type — is measured in
``test_a_long_journal_stays_quick.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.services.token_service import create_access_token

pytestmark = pytest.mark.integration

_NOON = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


def _auth(user) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


async def _write(
    db,
    org_id: UUID,
    at: datetime,
    *,
    target_type: str = 'item',
    count: int = 1,
) -> list[UUID]:
    """Entries written straight into the journal, all at the instant *at*."""
    entries = [
        AuditLog(
            id=uuid4(),
            organization_id=org_id,
            action='UPDATE',
            target_type=target_type,
            target_id=uuid4(),
            created_at=at,
        )
        for _ in range(count)
    ]
    db.add_all(entries)
    await db.commit()
    return [entry.id for entry in entries]


async def _get(client, user, **params: object) -> dict:
    response = await client.get('/api/v1/audit-log', params=params, headers=_auth(user))
    assert response.status_code == 200, response.text
    return response.json()


async def _walk(client, user, limit: int, **filters: object) -> list[dict]:
    pages: list[dict] = []
    cursor: str | None = None
    while True:
        params: dict[str, object] = {'limit': limit, **filters}
        if cursor:
            params['cursor'] = cursor
        page = await _get(client, user, **params)
        pages.append(page)
        cursor = page['next_cursor']
        if cursor is None:
            return pages
        assert len(pages) < 100, 'the cursor never ran out'


@pytest.mark.asyncio
class TestWalkingTheCursor:
    async def test_every_entry_is_seen_once_newest_first(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """A batch writes its rows at one instant, and the page size cuts through it."""
        org = async_test_household.id
        await _write(real_async_db_session, org, _NOON, count=9)
        await _write(real_async_db_session, org, _NOON - timedelta(hours=1), count=5)
        for hours in (2, 3, 4):
            await _write(real_async_db_session, org, _NOON - timedelta(hours=hours))
        await _write(real_async_db_session, org, _NOON + timedelta(days=1))

        everything = (await _get(real_async_client, async_test_user, limit=200))[
            'items'
        ]
        walked = [
            entry
            for page in await _walk(real_async_client, async_test_user, limit=4)
            for entry in page['items']
        ]

        assert len(everything) >= 18
        assert [e['id'] for e in walked] == [e['id'] for e in everything]
        assert len({e['id'] for e in walked}) == len(everything)
        stamps = [e['created_at'] for e in walked]
        assert stamps == sorted(stamps, reverse=True)

    async def test_the_last_page_carries_no_cursor(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        org = async_test_household.id
        await (
            real_async_db_session.commit()
        )  # the fixtures' user must be visible to the app
        existing = (await _get(real_async_client, async_test_user, limit=200))['total']
        for minutes in range(6):
            await _write(real_async_db_session, org, _NOON - timedelta(minutes=minutes))
        total = existing + 6

        pages = await _walk(real_async_client, async_test_user, limit=total // 2 or 1)

        assert pages[-1]['next_cursor'] is None
        assert pages[-1]['has_more'] is False
        assert all(page['has_more'] for page in pages[:-1])

    async def test_the_filters_hold_on_every_page(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        org = async_test_household.id
        for minutes in range(5):
            at = _NOON - timedelta(minutes=minutes)
            await _write(real_async_db_session, org, at, target_type='storage_location')
            await _write(real_async_db_session, org, at, target_type='item')

        pages = await _walk(
            real_async_client, async_test_user, limit=2, target_type='storage_location'
        )

        rows = [entry for page in pages for entry in page['items']]
        assert len(rows) == 5
        assert {row['target_type'] for row in rows} == {'storage_location'}
        assert {page['total'] for page in pages} == {5}


@pytest.mark.asyncio
class TestTheFigureTheReaderSees:
    async def test_the_count_is_taken_on_the_first_page_and_carried(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """Older entries land between the pages; the figure on screen holds."""
        org = async_test_household.id
        for minutes in range(8):
            await _write(
                real_async_db_session,
                org,
                _NOON - timedelta(minutes=minutes),
                target_type='counted',
            )
        first = await _get(
            real_async_client, async_test_user, limit=4, target_type='counted'
        )
        for days in (5, 6, 7):
            await _write(
                real_async_db_session,
                org,
                _NOON - timedelta(days=days),
                target_type='counted',
            )

        second = await _get(
            real_async_client,
            async_test_user,
            limit=4,
            target_type='counted',
            cursor=first['next_cursor'],
        )

        assert first['total'] == 8
        assert second['total'] == 8

    async def test_each_page_says_how_many_entries_came_before_it(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        org = async_test_household.id
        for minutes in range(7):
            await _write(
                real_async_db_session,
                org,
                _NOON - timedelta(minutes=minutes),
                target_type='counted',
            )

        pages = await _walk(
            real_async_client, async_test_user, limit=3, target_type='counted'
        )

        assert [page['offset'] for page in pages] == [0, 3, 6]
        assert [len(page['items']) for page in pages] == [3, 3, 1]


@pytest.mark.asyncio
class TestACursorIsOnlyAPosition:
    async def test_a_malformed_cursor_is_refused(
        self, real_async_client, real_async_db_session, async_test_user
    ):
        await real_async_db_session.commit()  # the fixtures' user must be visible
        for bad in ('not-a-cursor', 'e30=', 'W10='):
            response = await real_async_client.get(
                '/api/v1/audit-log',
                params={'cursor': bad},
                headers=_auth(async_test_user),
            )
            assert response.status_code == 400, bad

    async def test_another_organizations_cursor_opens_none_of_its_entries(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        # Entries of another organization, in the range the cursor points at.
        other = Organization(name=f'Other {uuid4().hex[:6]}', enabled_modules=['core'])
        real_async_db_session.add(other)
        await real_async_db_session.commit()
        await _write(real_async_db_session, other.id, _NOON, count=5)
        for minutes in range(5):
            await _write(
                real_async_db_session,
                async_test_household.id,
                _NOON - timedelta(minutes=minutes),
                target_type='mine',
            )
        first = await _get(
            real_async_client, async_test_user, limit=2, target_type='mine'
        )

        page = await _get(
            real_async_client,
            async_test_user,
            limit=100,
            cursor=first['next_cursor'],
        )

        assert {e['organization_id'] for e in page['items']} <= {
            str(async_test_household.id)
        }


@pytest.mark.asyncio
class TestTheOldOffsetStillAnswers:
    async def test_offset_without_a_cursor_pages_as_it_did(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        org = async_test_household.id
        for minutes in range(5):
            await _write(
                real_async_db_session,
                org,
                _NOON - timedelta(minutes=minutes),
                target_type='counted',
            )
        everything = (
            await _get(
                real_async_client, async_test_user, limit=100, target_type='counted'
            )
        )['items']

        page = await _get(
            real_async_client,
            async_test_user,
            limit=2,
            offset=2,
            target_type='counted',
        )

        assert [e['id'] for e in page['items']] == [e['id'] for e in everything[2:4]]
        assert page['offset'] == 2
        assert page['total'] == 5


@pytest.mark.asyncio
class TestTheTypesTheLogHolds:
    async def test_each_type_once_in_order_however_many_entries_it_has(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        org = async_test_household.id
        await _write(
            real_async_db_session, org, _NOON, target_type='zeta_kind', count=4
        )
        await _write(
            real_async_db_session, org, _NOON, target_type='alpha_kind', count=1
        )
        await _write(
            real_async_db_session, org, _NOON, target_type='middle_kind', count=7
        )

        response = await real_async_client.get(
            '/api/v1/audit-log/target-types', headers=_auth(async_test_user)
        )

        assert response.status_code == 200
        types = response.json()
        assert types == sorted(set(types))
        assert {'alpha_kind', 'middle_kind', 'zeta_kind'} <= set(types)
        assert types.index('alpha_kind') < types.index('middle_kind')
        assert types.index('middle_kind') < types.index('zeta_kind')

    async def test_another_organizations_types_are_not_listed(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        other = Organization(name=f'Other {uuid4().hex[:6]}', enabled_modules=['core'])
        real_async_db_session.add(other)
        await real_async_db_session.commit()
        await _write(real_async_db_session, other.id, _NOON, target_type='secret_kind')

        response = await real_async_client.get(
            '/api/v1/audit-log/target-types', headers=_auth(async_test_user)
        )

        assert 'secret_kind' not in response.json()

    async def test_an_empty_journal_lists_nothing(
        self, real_async_client, real_async_db_session, async_test_user
    ):
        other = Organization(name=f'Empty {uuid4().hex[:6]}', enabled_modules=['core'])
        real_async_db_session.add(other)
        await real_async_db_session.commit()
        from app.core.testing import ModuleTestHelper

        user = await ModuleTestHelper.create_user_async(
            real_async_db_session, other, email=f'empty_{uuid4().hex[:8]}@test.com'
        )
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/audit-log/target-types', headers=_auth(user)
        )

        assert response.status_code == 200
        assert response.json() == []
