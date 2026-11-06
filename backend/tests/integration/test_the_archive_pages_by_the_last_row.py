"""The archived products page by the last row the reader saw.

``GET /api/v1/items/archived`` paged with ``OFFSET`` and took a ``COUNT(*)``
on every request, sorted by the archive date alone. Nothing deletes an
archived record, so the list only grows, and a page boundary falling between
records archived at one instant could show one of them twice and hide
another. It now hands back a ``next_cursor`` naming the last row, the next
request starts below that row, and the count is taken on the first page and
carried in the cursor.

What these tests hold the endpoint to:

- walking the cursor visits every archived record exactly once, in the order
  the archive reads — newest archive date first, the id breaking ties, and the
  creation date standing in where a record carries no archive date;
- the figure the reader sees does not move between pages;
- a cursor is a position and nothing more: another organization's records
  stay out of reach, and a forged one is refused rather than guessed at.

The old ``offset`` still answers (``test_soft_delete_restore_purge.py``,
``TestArchivedPagination``). The shape of the work — that a deep page is read
off the index and costs what the first page costs — is measured in
``test_a_deep_archive_page_costs_what_the_first_costs.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash

_NOON = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


class _Archive:
    """An organization with a shelf, someone allowed to read it, and its archive."""

    def __init__(self, db: Session, label: str) -> None:
        org = Organization(
            name=f'Archive {label} {uuid4().hex[:6]}',
            enabled_modules=['core', 'items', 'locations'],
        )
        db.add(org)
        db.flush()
        user = User(
            email=f'archive-{label}-{uuid4().hex[:8]}@test.com',
            hashed_password=get_password_hash('pass'),
            full_name=f'Archive {label}',
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        storage_type = StorageType(
            name=f'Shelf {label}', type_code=f'A{uuid4().hex[:8]}'
        )
        db.add_all([user, storage_type])
        db.flush()
        location = StorageLocation(
            organization_id=org.id,
            created_by=user.id,
            storage_type_id=storage_type.id,
            name=f'Pantry {label}',
        )
        db.add(location)
        db.commit()
        self.org_id: UUID = org.id
        self.location_id: UUID = location.id
        self.headers = {
            'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
        }
        self._db = db
        #: (the date the record sorts by, its id), as archived.
        self.archived: list[tuple[datetime, UUID]] = []

    def archive(
        self, deleted_at: datetime | None, *, created_at: datetime | None = None
    ) -> UUID:
        made = created_at or (deleted_at - timedelta(days=30) if deleted_at else _NOON)
        item = Item(
            id=uuid4(),
            organization_id=self.org_id,
            storage_location_id=self.location_id,
            name=f'Archived {len(self.archived)}',
            quantity=Decimal('0'),
            is_deleted=True,
            deleted_at=deleted_at,
            created_at=made,
        )
        self._db.add(item)
        self._db.commit()
        self.archived.append((deleted_at or made, item.id))
        return item.id

    def in_order(self) -> list[str]:
        """The archive's order by its plain definition: newest first, then the id."""
        by_id = sorted(self.archived, key=lambda row: row[1])
        return [
            str(row_id)
            for _, row_id in sorted(by_id, key=lambda row: row[0], reverse=True)
        ]


@pytest.fixture
def archive(db_session: Session) -> _Archive:
    return _Archive(db_session, 'a')


def _get(client: TestClient, archive: _Archive, **params: object) -> dict:
    response = client.get(
        '/api/v1/items/archived', params=params, headers=archive.headers
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return response.json()


def _walk(client: TestClient, archive: _Archive, limit: int) -> list[dict]:
    """Every page of the archive, first to last, following ``next_cursor``."""
    pages = []
    cursor: str | None = None
    while True:
        params: dict[str, object] = {'limit': limit}
        if cursor:
            params['cursor'] = cursor
        page = _get(client, archive, **params)
        pages.append(page)
        cursor = page['next_cursor']
        if cursor is None:
            return pages
        assert len(pages) < 100, 'the cursor never ran out'


@pytest.mark.integration
class TestWalkingTheCursor:
    def test_every_archived_record_is_seen_once_in_the_archives_order(
        self, client: TestClient, archive: _Archive
    ) -> None:
        """Ties are the case: a seek on the date alone loses or repeats them.

        Eleven records were archived at one instant and four at another, and
        the page size cuts through both groups. Three carry no archive date at
        all, so the date they sort by is the one they were made on.
        """
        for _ in range(11):
            archive.archive(_NOON)
        for _ in range(4):
            archive.archive(_NOON - timedelta(hours=1))
        for hours in (2, 3, 4):
            archive.archive(None, created_at=_NOON - timedelta(hours=hours))
        archive.archive(_NOON + timedelta(days=1))

        pages = _walk(client, archive, limit=4)
        walked = [row['id'] for page in pages for row in page['items']]

        assert walked == archive.in_order()
        assert [page['offset'] for page in pages] == [0, 4, 8, 12, 16]
        assert {page['total'] for page in pages} == {19}

    def test_the_last_page_carries_no_cursor(
        self, client: TestClient, archive: _Archive
    ) -> None:
        """An archive that fills its pages exactly has no empty page after them."""
        for minutes in range(6):
            archive.archive(_NOON - timedelta(minutes=minutes))

        pages = _walk(client, archive, limit=3)

        assert [len(page['items']) for page in pages] == [3, 3]
        assert [page['has_more'] for page in pages] == [True, False]
        assert pages[-1]['next_cursor'] is None


@pytest.mark.integration
class TestTheCountRidesInTheCursor:
    def test_the_figure_does_not_move_while_the_reader_pages(
        self, client: TestClient, archive: _Archive
    ) -> None:
        """Records archived while the reader is on page one change nothing on page two.

        A new first page — the reader starting again — counts afresh.
        """
        for minutes in range(6):
            archive.archive(_NOON - timedelta(minutes=minutes))
        first = _get(client, archive, limit=3)
        archive.archive(_NOON + timedelta(hours=1))
        archive.archive(_NOON + timedelta(hours=2))

        second = _get(client, archive, limit=3, cursor=first['next_cursor'])
        again = _get(client, archive, limit=3)

        assert first['total'] == 6
        assert second['total'] == 6
        assert second['offset'] == 3
        assert [row['id'] for row in second['items']] == archive.in_order()[5:8]
        assert again['total'] == 8


@pytest.mark.integration
class TestACursorIsOnlyAPosition:
    def test_another_organizations_records_stay_out_of_reach(
        self, client: TestClient, archive: _Archive, db_session: Session
    ) -> None:
        stranger = _Archive(db_session, 'b')
        for minutes in range(4):
            archive.archive(_NOON - timedelta(minutes=minutes))
            stranger.archive(_NOON - timedelta(minutes=minutes))
        mine = _get(client, archive, limit=1)

        theirs = _get(client, stranger, limit=10, cursor=mine['next_cursor'])

        returned = {row['id'] for row in theirs['items']}
        assert returned
        assert returned <= {str(row_id) for _, row_id in stranger.archived}

    def test_a_forged_cursor_is_refused(
        self, client: TestClient, archive: _Archive
    ) -> None:
        archive.archive(_NOON)

        response = client.get(
            '/api/v1/items/archived',
            params={'cursor': 'not-a-cursor'},
            headers=archive.headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
