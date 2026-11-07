"""A NUL character in a request is refused in words, not answered with a 500.

PostgreSQL holds no U+0000 in text, so a statement that carries one fails in
the database. The search of every list reaches the database as a parameter,
and the screens keep their search in the address: ``?search=%00`` typed into
it ended the request in a 500 on the stock on a date, the stock list, the
products and the partners alike.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation

from ._shelf import post_on_shelf

pytestmark = pytest.mark.integration


@pytest.fixture
def a_shelf_with_a_ledger(client, auth_headers, db_session, test_user) -> None:
    """The stock on a date answers only an organization whose ledger holds a movement."""
    shelf = StorageLocation(
        organization_id=test_user.organization_id,
        created_by=test_user.id,
        name='Shelf A',
        usage='internal',
    )
    flour = ProductTemplate(organization_id=test_user.organization_id, name='Rye flour')
    db_session.add_all([shelf, flour])
    db_session.commit()
    post_on_shelf(client, auth_headers, flour, shelf.id, Decimal('2'))


@pytest.mark.parametrize(
    'path',
    [
        '/api/v1/stock-as-of',
        '/api/v1/stock-as-of/export/xlsx',
        '/api/v1/stock-quants',
        '/api/v1/items',
        '/api/v1/partners',
    ],
)
@pytest.mark.parametrize('search', ['\x00', 'flour\x00'])
def test_a_search_with_a_null_character_is_refused(
    client: TestClient,
    auth_headers: dict[str, str],
    a_shelf_with_a_ledger: None,
    path: str,
    search: str,
) -> None:
    # The day the stock is asked about is today, after the fixture's movement.
    params = {'as_of': datetime.now(UTC).isoformat()} if 'stock-as-of' in path else {}

    response = client.get(
        path, headers=auth_headers, params={**params, 'search': search}
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
    detail = response.json()['detail']
    assert detail['code'] == 'TEXT_HAS_A_NULL_CHARACTER'
    assert 'null character' in detail['message']


def test_the_refusal_speaks_the_readers_language(
    client: TestClient, auth_headers: dict[str, str], a_shelf_with_a_ledger: None
) -> None:
    response = client.get(
        '/api/v1/items',
        headers={**auth_headers, 'Accept-Language': 'pl'},
        params={'search': '\x00'},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
    detail = response.json()['detail']
    assert detail['lang'] == 'pl'
    assert 'znak' in detail['message']


async def test_any_other_database_error_still_ends_as_it_did() -> None:
    """Only the NUL character is a refusal; the rest stay defects, and a
    deadlock still reaches the retry around the request."""
    from starlette.requests import Request

    from app.main import unstorable_text_handler

    class _DeadlockError(Exception):
        sqlstate = '40P01'

    error = DBAPIError('SELECT 1', {}, _DeadlockError())
    request = Request({'type': 'http', 'method': 'GET', 'path': '/', 'headers': []})

    with pytest.raises(DBAPIError):
        await unstorable_text_handler(request, error)
