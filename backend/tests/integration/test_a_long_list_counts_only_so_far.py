"""A list that grows with the organization counts only so far.

The product list, the stock list and the movement journal counted every row
of the answer on every first page: at a hundred thousand products that count
was most of the page, and it grew with the warehouse. They now stop counting
one row past ``LIST_COUNT_CAP`` and say so — ``total`` is where the count
stopped and ``total_capped`` that there are more — while a page beyond the
cap still knows whether another follows. Below the cap nothing changes: the
total is exact and ``total_capped`` false.

The cap is lowered to three here, so five rows are past it.

``PaginatedResponse.from_slice`` re-caps whatever total it is given, so the
envelope alone cannot tell a count that stopped at the cap from one that
read every row and was clamped afterwards. The last class looks at the
statements instead: the count carries its ``LIMIT``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Engine

import app.api.items as items_api
import app.api.stock_moves as stock_moves_api
import app.api.stock_quants as stock_quants_api

pytestmark = pytest.mark.integration

_CAP = 3
_ROWS = 5


@pytest.fixture
def five_products(
    client: TestClient,
    auth_headers: dict[str, str],
    test_storage_location: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Five products on one shelf: five records, five groups, five moves."""
    for module in (items_api, stock_moves_api, stock_quants_api):
        monkeypatch.setattr(module, 'LIST_COUNT_CAP', _CAP)
    for n in range(_ROWS):
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': f'Counted product {n}',
                'quantity': '2',
                'location_id': str(test_storage_location.id),
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text


@pytest.fixture
def statements() -> Iterator[list[tuple[str, Any]]]:
    """Every statement the database receives while the test runs."""
    seen: list[tuple[str, Any]] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        seen.append((statement, parameters))

    event.listen(Engine, 'before_cursor_execute', _capture)
    try:
        yield seen
    finally:
        event.remove(Engine, 'before_cursor_execute', _capture)


def _page(
    client: TestClient, headers: dict[str, str], path: str, **params: Any
) -> dict[str, Any]:
    response = client.get(path, headers=headers, params=params)
    assert response.status_code == status.HTTP_200_OK, response.text
    return response.json()


def _envelope(page: dict[str, Any]) -> tuple[int, bool, bool, int]:
    return page['total'], page['total_capped'], page['has_more'], len(page['items'])


@pytest.mark.usefixtures('five_products')
class TestTheProductList:
    def test_the_first_page_stops_counting_at_the_cap(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        page = _page(client, auth_headers, '/api/v1/items', limit=2)
        assert _envelope(page) == (_CAP, True, True, 2)

    def test_a_page_past_the_cap_still_knows_another_follows(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        page = _page(client, auth_headers, '/api/v1/items', limit=2, offset=2)
        assert _envelope(page) == (4, True, True, 2)

    def test_the_last_page_counts_to_the_end(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        page = _page(client, auth_headers, '/api/v1/items', limit=2, offset=4)
        assert _envelope(page) == (_ROWS, False, False, 1)

    def test_the_footer_still_counts_every_record(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """The exact number the list no longer gives is the footer's."""
        sums = _page(client, auth_headers, '/api/v1/items/aggregates')
        assert sums['count'] == _ROWS


@pytest.mark.usefixtures('five_products')
class TestTheStockList:
    def test_the_first_page_stops_counting_at_the_cap(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        page = _page(client, auth_headers, '/api/v1/stock-quants', limit=2)
        assert _envelope(page) == (_CAP, True, True, 2)

    def test_the_last_page_counts_to_the_end(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        page = _page(client, auth_headers, '/api/v1/stock-quants', limit=2, offset=4)
        assert _envelope(page) == (_ROWS, False, False, 1)


@pytest.mark.usefixtures('five_products')
class TestTheJournal:
    def test_the_count_stops_at_the_cap_and_rides_the_cursor(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """The first page counts as far as the cap; the pages after it carry
        that figure and that it stopped, and the last one says nothing
        follows."""
        first = _page(client, auth_headers, '/api/v1/stock-moves', limit=2)
        second = _page(
            client,
            auth_headers,
            '/api/v1/stock-moves',
            limit=2,
            cursor=first['next_cursor'],
        )
        third = _page(
            client,
            auth_headers,
            '/api/v1/stock-moves',
            limit=2,
            cursor=second['next_cursor'],
        )

        assert _envelope(first) == (_CAP, True, True, 2)
        assert _envelope(second) == (_CAP, True, True, 2)
        assert (third['has_more'], len(third['items'])) == (False, 1)
        seen = [m['id'] for page in (first, second, third) for m in page['items']]
        assert len(set(seen)) == _ROWS


@pytest.mark.usefixtures('five_products')
class TestTheCountCarriesItsLimit:
    """The count statement stops one row past the window: ``LIMIT cap + 1``."""

    @pytest.mark.parametrize(
        'path', ['/api/v1/items', '/api/v1/stock-quants', '/api/v1/stock-moves']
    )
    def test_the_count_is_limited_to_the_window_and_one_row(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        statements: list[tuple[str, Any]],
        path: str,
    ) -> None:
        _page(client, auth_headers, path, limit=2)

        counts = [
            (sql, params)
            for sql, params in statements
            if 'count(*)' in sql.lower() and 'FROM (' in sql
        ]
        assert counts, 'the list took no count at all'
        for sql, params in counts:
            assert 'LIMIT' in sql, sql
            assert _CAP + 1 in tuple(params), (_CAP + 1, params)


def test_a_list_below_the_cap_is_counted_exactly(
    client: TestClient,
    auth_headers: dict[str, str],
    test_storage_location: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(items_api, 'LIST_COUNT_CAP', _CAP)
    for n in range(_CAP):
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': f'Few {n}',
                'quantity': '1',
                'location_id': str(test_storage_location.id),
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text

    page = _page(client, auth_headers, '/api/v1/items', limit=2)

    assert _envelope(page) == (_CAP, False, True, 2)
