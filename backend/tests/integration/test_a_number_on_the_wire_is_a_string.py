"""A quantity or an amount crosses the wire as a string, never as a float.

Decimal columns serialise as strings — the one JSON shape that carries every
digit the column holds. An explicit ``Decimal -> float`` serializer undoes
that for one endpoint, and the tests that compare through ``Decimal(...)``
cannot tell: ``Decimal('12.5')`` and ``Decimal(12.5)`` are equal. So this
test looks at the shape, not the value. A serializer that comes back turns
it red.

The endpoints here are the core ones a client reads quantities from; the
purchase-order surface has its own copy of the same assertion next to the
schema that once carried the serializer.
"""

from __future__ import annotations

import pytest
from fastapi import status

pytestmark = pytest.mark.integration


def _is_decimal_string(value: object) -> bool:
    return isinstance(value, str) and value.replace('.', '', 1).isdigit()


def _kg_id(db) -> str:
    """The unit these records name, and the reason they can hold a decimal.

    A record that names no unit is measured in pieces, and pieces count
    whole — 2.5 of them is refused on the way in. The shape under
    test here is the decimal, so the request names a unit that keeps one.
    """
    from sqlalchemy import select

    from app.models.uom import Uom

    return str(db.scalars(select(Uom).where(Uom.symbol == 'kg')).first().id)


class TestTheCoreSpeaksInStrings:
    def test_a_record_reads_back_its_quantity_and_price_as_strings(
        self, client, auth_headers, test_storage_location, db_session
    ) -> None:
        created = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Rice',
                'quantity': '2.5',
                'uom_id': _kg_id(db_session),
                'purchase_price': '4.5',
                'location_id': str(test_storage_location.id),
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        body = created.json()
        assert _is_decimal_string(body['quantity']), body['quantity']
        assert _is_decimal_string(body['purchase_price']), body['purchase_price']

        listed = client.get('/api/v1/items', headers=auth_headers)
        assert listed.status_code == status.HTTP_200_OK
        row = next(r for r in listed.json()['items'] if r['id'] == body['id'])
        assert _is_decimal_string(row['quantity'])
        assert _is_decimal_string(row['purchase_price'])

        quants = client.get('/api/v1/stock-quants', headers=auth_headers)
        assert quants.status_code == status.HTTP_200_OK
        assert quants.json()['items'], 'the record should have opened a quant'
        assert all(_is_decimal_string(q['quantity']) for q in quants.json()['items'])

    def test_the_archive_speaks_the_same_language(
        self, client, auth_headers, test_storage_location, db_session
    ) -> None:
        created = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Rice',
                'quantity': '2.5',
                'uom_id': _kg_id(db_session),
                'purchase_price': '4.5',
                'location_id': str(test_storage_location.id),
            },
        )
        item_id = created.json()['id']
        deleted = client.request(
            'DELETE',
            f'/api/v1/items/{item_id}',
            headers=auth_headers,
            json={'reason': 'USED'},
        )
        assert deleted.status_code in (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT)

        archived = client.get('/api/v1/items/archived', headers=auth_headers)
        assert archived.status_code == status.HTTP_200_OK
        row = next(r for r in archived.json()['items'] if r['id'] == item_id)
        assert _is_decimal_string(row['quantity']), row['quantity']
        assert _is_decimal_string(row['purchase_price']), row['purchase_price']
