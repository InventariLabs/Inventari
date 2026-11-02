"""The movement ledger pages by the last row the reader saw.

``GET /api/v1/stock-moves`` used to page with ``OFFSET`` and a ``COUNT(*)`` on
every request, so the hundredth page cost a hundred pages and the count was
taken again each time the reader turned one. It now hands back a
``next_cursor`` that names the last row, the next request starts below that
row, and the count is taken on the first page and carried in the cursor.

What these tests hold the endpoint to:

- walking the cursor visits every movement exactly once, in the order the
  ledger reads — including movements that share one instant, which is where a
  seek on the date alone drops or repeats rows at a page boundary;
- the figure the reader sees does not move between pages;
- a cursor is a position and nothing more: another organization's rows stay
  out of reach, and a forged one is refused rather than guessed at;
- the old ``offset`` still answers, so a caller written against it keeps
  working while it moves.

The shape of the work — that a page deep in a long ledger is read off the index
and costs what the first page costs — is measured in
``test_the_ledger_stays_quick_when_it_is_long.py`` and
``test_a_deep_ledger_page_costs_what_the_first_costs.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash

_NOON = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


class _Warehouse:
    """An organization with a place, a product and someone allowed to read."""

    def __init__(self, db: Session, label: str) -> None:
        org = Organization(
            name=f'Ledger {label} {uuid4().hex[:6]}',
            enabled_modules=['core', 'warehouse'],
        )
        db.add(org)
        db.flush()
        user = User(
            email=f'ledger-{label}-{uuid4().hex[:8]}@test.com',
            hashed_password=get_password_hash('pass'),
            full_name=f'Ledger {label}',
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        storage_type = StorageType(
            name=f'Shelf {label}', type_code=f'L{uuid4().hex[:8]}'
        )
        db.add_all([user, storage_type])
        db.flush()
        location = StorageLocation(
            organization_id=org.id,
            created_by=user.id,
            storage_type_id=storage_type.id,
            name=f'Aisle {label}',
        )
        product = ProductTemplate(
            organization_id=org.id,
            name=f'Product {label}',
            sku=f'SKU-{uuid4().hex[:8]}',
        )
        db.add_all([location, product])
        db.commit()
        self.org_id: UUID = org.id
        self.location_id: UUID = location.id
        self.product_id: UUID = product.id
        self.headers = _auth(user)
        self._db = db

    def move(
        self,
        completed_at: datetime | None,
        *,
        created_at: datetime | None = None,
        product_id: UUID | None = None,
    ) -> UUID:
        move = StockMove(
            id=uuid4(),
            organization_id=self.org_id,
            product_template_id=product_id or self.product_id,
            from_location_id=None,
            to_location_id=self.location_id,
            quantity=Decimal('1.000'),
            state='done',
            reference_type='item',
            reference_id=uuid4(),
            created_at=created_at or completed_at or _NOON,
            completed_at=completed_at,
        )
        self._db.add(move)
        self._db.commit()
        return move.id


@pytest.fixture
def warehouse(db_session: Session) -> _Warehouse:
    return _Warehouse(db_session, 'a')


def _get(client: TestClient, warehouse: _Warehouse, **params: object) -> dict:
    response = client.get(
        '/api/v1/stock-moves', params=params, headers=warehouse.headers
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return response.json()


def _walk(client: TestClient, warehouse: _Warehouse, limit: int, **filters: object):
    """Every page of the ledger, first to last, following ``next_cursor``."""
    pages = []
    cursor: str | None = None
    while True:
        params: dict[str, object] = {'limit': limit, **filters}
        if cursor:
            params['cursor'] = cursor
        page = _get(client, warehouse, **params)
        pages.append(page)
        cursor = page['next_cursor']
        if cursor is None:
            return pages
        assert len(pages) < 100, 'the cursor never ran out'


@pytest.mark.integration
class TestWalkingTheCursor:
    def test_every_movement_is_seen_once_in_the_ledgers_order(
        self, client: TestClient, warehouse: _Warehouse
    ) -> None:
        """Ties are the case: a seek on the date alone loses or repeats them.

        Eleven movements share one instant and four more share another, and
        the page size cuts through both groups. Three carry no completion date
        at all, so the date they sort by is the one they were written on.
        """
        for _ in range(11):
            warehouse.move(_NOON)
        for _ in range(4):
            warehouse.move(_NOON - timedelta(hours=1))
        for hours in (2, 3, 4):
            warehouse.move(None, created_at=_NOON - timedelta(hours=hours))
        warehouse.move(_NOON + timedelta(days=1))

        everything = _get(client, warehouse, limit=100)['items']
        walked = [
            row for page in _walk(client, warehouse, limit=4) for row in page['items']
        ]

        assert len(everything) == 19
        assert [row['id'] for row in walked] == [row['id'] for row in everything]
        assert len({row['id'] for row in walked}) == 19

    def test_the_last_page_carries_no_cursor(
        self, client: TestClient, warehouse: _Warehouse
    ) -> None:
        """A ledger that fills its pages exactly has no empty page after them."""
        for minutes in range(6):
            warehouse.move(_NOON - timedelta(minutes=minutes))

        pages = _walk(client, warehouse, limit=3)

        assert [len(page['items']) for page in pages] == [3, 3]
        assert [page['has_more'] for page in pages] == [True, False]
        assert pages[-1]['next_cursor'] is None

    def test_a_ledger_that_fits_one_page_has_no_cursor(
        self, client: TestClient, warehouse: _Warehouse
    ) -> None:
        warehouse.move(_NOON)

        page = _get(client, warehouse, limit=5)

        assert page['next_cursor'] is None
        assert page['has_more'] is False
        assert page['total'] == 1

    def test_the_filters_hold_on_every_page(
        self, client: TestClient, db_session: Session, warehouse: _Warehouse
    ) -> None:
        other = ProductTemplate(
            organization_id=warehouse.org_id, name='Other', sku=f'S-{uuid4().hex[:8]}'
        )
        db_session.add(other)
        db_session.commit()
        for minutes in range(6):
            warehouse.move(_NOON - timedelta(minutes=minutes))
            warehouse.move(_NOON - timedelta(minutes=minutes), product_id=other.id)

        pages = _walk(
            client, warehouse, limit=2, product_template_id=str(warehouse.product_id)
        )

        rows = [row for page in pages for row in page['items']]
        assert len(rows) == 6
        assert {row['product_template_id'] for row in rows} == {
            str(warehouse.product_id)
        }
        assert {page['total'] for page in pages} == {6}


@pytest.mark.integration
class TestTheFigureTheReaderSees:
    def test_the_count_is_taken_on_the_first_page_and_carried(
        self, client: TestClient, warehouse: _Warehouse
    ) -> None:
        """Later pages do not count again, so the figure holds while they read.

        Three older movements land between the first page and the second. A
        page that counted for itself would report them; the cursor carries the
        figure the first page took, so the reader's "of 8" does not become
        "of 11" under their finger.
        """
        for minutes in range(8):
            warehouse.move(_NOON - timedelta(minutes=minutes))
        first = _get(client, warehouse, limit=4)
        for days in (5, 6, 7):
            warehouse.move(_NOON - timedelta(days=days))

        second = _get(client, warehouse, limit=4, cursor=first['next_cursor'])

        assert first['total'] == 8
        assert second['total'] == 8

    def test_a_new_first_page_counts_afresh(
        self, client: TestClient, warehouse: _Warehouse
    ) -> None:
        for minutes in range(3):
            warehouse.move(_NOON - timedelta(minutes=minutes))
        assert _get(client, warehouse, limit=2)['total'] == 3

        warehouse.move(_NOON - timedelta(days=3))

        assert _get(client, warehouse, limit=2)['total'] == 4

    def test_each_page_says_how_many_rows_came_before_it(
        self, client: TestClient, warehouse: _Warehouse
    ) -> None:
        for minutes in range(7):
            warehouse.move(_NOON - timedelta(minutes=minutes))

        pages = _walk(client, warehouse, limit=3)

        assert [page['offset'] for page in pages] == [0, 3, 6]
        assert [len(page['items']) for page in pages] == [3, 3, 1]


@pytest.mark.integration
class TestACursorIsOnlyAPosition:
    def test_a_malformed_cursor_is_refused(
        self, client: TestClient, warehouse: _Warehouse
    ) -> None:
        for bad in ('not-a-cursor', 'e30=', 'W10='):
            response = client.get(
                '/api/v1/stock-moves',
                params={'cursor': bad},
                headers=warehouse.headers,
            )
            assert response.status_code == status.HTTP_400_BAD_REQUEST, bad

    def test_another_organizations_cursor_opens_none_of_its_rows(
        self, client: TestClient, db_session: Session, warehouse: _Warehouse
    ) -> None:
        mine = _Warehouse(db_session, 'b')
        for minutes in range(5):
            warehouse.move(_NOON - timedelta(minutes=minutes))
            mine.move(_NOON - timedelta(minutes=minutes))
        foreign = _get(client, warehouse, limit=2)['next_cursor']

        page = _get(client, mine, limit=10, cursor=foreign)

        assert page['items']
        theirs = {row['id'] for row in _get(client, warehouse, limit=100)['items']}
        assert not theirs & {row['id'] for row in page['items']}


@pytest.mark.integration
class TestTheOldOffsetStillAnswers:
    def test_offset_without_a_cursor_pages_as_it_did(
        self, client: TestClient, warehouse: _Warehouse
    ) -> None:
        for minutes in range(5):
            warehouse.move(_NOON - timedelta(minutes=minutes))
        everything = _get(client, warehouse, limit=100)['items']

        page = _get(client, warehouse, limit=2, offset=2)

        assert [row['id'] for row in page['items']] == [
            row['id'] for row in everything[2:4]
        ]
        assert page['offset'] == 2
        assert page['total'] == 5
        assert page['has_more'] is True
