"""The stock on a date answers for one product when a reader names it.

The stock list narrows by a typed search; the report of a day beside it had
only a date and a place, so a reader who had narrowed the list to a product
lost it on the way. The text reaches the same fields the list reads, and the
figures beside the rows (the count, the total, the files) speak about the
products that matched — not about a shelf the reader did not ask for.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO

import pytest
from fastapi import status
from openpyxl import load_workbook
from sqlalchemy import update

from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation

from ._shelf import post_on_shelf

pytestmark = pytest.mark.integration

_A_MONTH_AGO = datetime.now(UTC) - timedelta(days=30)


@pytest.fixture
def shelf_of_three(client, auth_headers, db_session, test_user):
    shelf = StorageLocation(
        organization_id=test_user.organization_id,
        created_by=test_user.id,
        name='Shelf A',
        usage='internal',
    )
    db_session.add(shelf)
    products = {}
    for name, brand in (('Rye flour', 'Mill'), ('Sugar', 'Sweet Co'), ('Salt', None)):
        template = ProductTemplate(
            organization_id=test_user.organization_id,
            name=name,
            brand=brand,
            sku=f'SKU-{name[:3].upper()}',
        )
        db_session.add(template)
        products[name] = template
    db_session.commit()
    for template in products.values():
        post_on_shelf(client, auth_headers, template, shelf.id, Decimal('2'))
    db_session.execute(
        update(StockMove)
        .where(StockMove.organization_id == test_user.organization_id)
        .values(completed_at=_A_MONTH_AGO)
    )
    db_session.commit()
    return products


def _names(client, auth_headers, **params) -> tuple[list[str], int]:
    response = client.get(
        '/api/v1/stock-as-of',
        headers=auth_headers,
        params={'as_of': datetime.now(UTC).isoformat(), **params},
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    body = response.json()
    return [row['product_name'] for row in body['items']], body['total']


def test_the_report_without_a_search_carries_every_product(
    client, auth_headers, shelf_of_three
):
    names, total = _names(client, auth_headers)

    assert names == ['Rye flour', 'Salt', 'Sugar']
    assert total == 3


def test_a_search_narrows_the_rows_and_the_count_to_the_product(
    client, auth_headers, shelf_of_three
):
    names, total = _names(client, auth_headers, search='flour')

    assert names == ['Rye flour']
    assert total == 1


def test_a_search_reaches_the_brand_and_the_catalogue_number_too(
    client, auth_headers, shelf_of_three
):
    assert _names(client, auth_headers, search='sweet')[0] == ['Sugar']
    assert _names(client, auth_headers, search='SKU-SAL')[0] == ['Salt']


def test_a_percent_sign_is_text_not_a_wildcard(client, auth_headers, shelf_of_three):
    assert _names(client, auth_headers, search='%') == ([], 0)


def test_the_spreadsheet_carries_the_narrowed_report(
    client, auth_headers, shelf_of_three
):
    response = client.get(
        '/api/v1/stock-as-of/export/xlsx',
        headers=auth_headers,
        params={'as_of': datetime.now(UTC).isoformat(), 'search': 'sugar'},
    )
    assert response.status_code == status.HTTP_200_OK, response.text

    sheet = load_workbook(BytesIO(response.content)).active
    cells = [str(cell.value) for row in sheet.iter_rows() for cell in row]
    assert 'Sugar' in cells
    assert 'Rye flour' not in cells
