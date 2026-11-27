"""The ingredient dictionary reads the CSV a spreadsheet actually writes.

Excel in Polish, German, French and Spanish locales separates columns with a
semicolon and writes the text in the local codepage. This door had a reader
of its own — comma-separated, decoded as utf-8 with ``errors='replace'`` —
so a semicolon sheet was refused as unreadable whatever its rows held, and a
cp1250 sheet was accepted under a 200 with replacement characters where the
Polish letters were: a dictionary that no longer says what the file says.

The door now reads through the shared reader every other import uses, so
what the spreadsheet saved is what the rows become.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration

RECIPE_URL = '/api/v1/recipes'

SEMICOLON = b'name;calories_kcal\nKasza gryczana;343\n'
CP1250 = 'name,calories_kcal\nKasza gryczana żółta,343\n'.encode('cp1250')
DECIMAL_COMMA = b'name;calories_kcal;protein_g\nKasza gryczana;343;12,5\n'
THOUSANDS = b'name;calories_kcal;protein_g\nKasza gryczana;1 289,5;1.234,5\n'


def _import(
    client: TestClient,
    auth_headers: dict[str, str],
    filename: str,
    payload: bytes,
) -> dict[str, int]:
    from io import BytesIO

    response = client.post(
        f'{RECIPE_URL}/ingredient-defaults/import',
        files={'file': (filename, BytesIO(payload), 'text/csv')},
        headers=auth_headers,
    )

    assert response.status_code == status.HTTP_200_OK, response.text
    body: dict[str, int] = response.json()
    return body


def _stored(
    client: TestClient, auth_headers: dict[str, str], name: str
) -> dict[str, Any]:
    listing = client.get(
        f'{RECIPE_URL}/ingredient-defaults',
        params={'lang': 'en', 'q': name},
        headers=auth_headers,
    ).json()

    assert listing['total'] == 1, listing
    item: dict[str, Any] = listing['items'][0]
    return item


def test_a_semicolon_sheet_imports_its_rows(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """The default separator is the semicolon in most of Europe."""
    body = _import(client, auth_headers, 'defaults.csv', SEMICOLON)

    assert body['created'] == 1
    assert body['errors'] == 0
    assert _stored(client, auth_headers, 'Kasza gryczana')['calories_kcal'] == '343.00'


def test_a_cp1250_sheet_keeps_its_polish_letters(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """A letter the codepage holds is read, never replaced by '�'."""
    body = _import(client, auth_headers, 'defaults.csv', CP1250)

    assert body['created'] == 1
    assert body['errors'] == 0
    assert _stored(client, auth_headers, 'Kasza gryczana żółta')['name'] == (
        'Kasza gryczana żółta'
    )


def test_a_decimal_comma_reads_as_the_decimal_it_names(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """In a semicolon sheet a comma inside a cell is never a separator.

    Excel writes 368,5 where a comma-separated sheet writes 368.5; left as
    text it fails the numeric validation and every row with a fractional
    value would be a counted error.
    """
    body = _import(client, auth_headers, 'defaults.csv', DECIMAL_COMMA)

    assert body['created'] == 1
    assert body['errors'] == 0
    lookup = client.get(
        f'{RECIPE_URL}/ingredient-defaults/lookup',
        params={'name': 'Kasza gryczana', 'lang': 'en'},
        headers=auth_headers,
    ).json()
    assert lookup['found'] is True
    assert Decimal(lookup['protein_g']) == Decimal('12.5')


def test_the_nutrient_columns_read_numbers_the_way_every_door_does(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """A space groups thousands and the last separator is the decimal one.

    The nutrition sheet kept a rule of its own — a comma replaced by a dot —
    so a value grouped with a space or written "1.234,5" was not read the way
    the same value is read in every other import.
    """
    body = _import(client, auth_headers, 'defaults.csv', THOUSANDS)

    assert body['created'] == 1
    assert body['errors'] == 0
    lookup = client.get(
        f'{RECIPE_URL}/ingredient-defaults/lookup',
        params={'name': 'Kasza gryczana', 'lang': 'en'},
        headers=auth_headers,
    ).json()
    assert Decimal(lookup['calories_kcal']) == Decimal('1289.5')
    assert Decimal(lookup['protein_g']) == Decimal('1234.5')
