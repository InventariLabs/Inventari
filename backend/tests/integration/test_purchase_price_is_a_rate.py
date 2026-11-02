"""The number typed into "purchase price" is the price of one, not of the lot.

Everything downstream already treats it that way: creating an item opens a
valuation layer at ``unit_cost=purchase_price``, AVCO is computed off those
layers, and a production cost is rate × quantity. Nothing on the form said so.
The field sits under "quantity 10" and a unit button reading "kg", so somebody
holding an invoice for ten kilos of wax at 45 types 45 — and every candle made
from 0.2 kg is then costed at 9.00 instead of 0.90.

Measured that way once: four raw materials entered as invoice totals produced a
unit cost of $759.00 against a real material cost of $3.45, because the error
multiplies by the pack size — 200× for an oil bought in 500 ml bottles.

The label now says which one it is. This holds the arithmetic to that label, so
the two cannot drift apart again.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.stock_valuation_layer import StockValuationLayer

pytestmark = pytest.mark.integration


def test_ten_units_at_forty_five_are_priced_at_forty_five_each(
    client: TestClient,
    auth_headers: dict[str, str],
    test_storage_location,
    db_session: Session,
) -> None:
    response = client.post(
        '/api/v1/items',
        json={
            'name': f'Wax {uuid.uuid4().hex[:6]}',
            'quantity': 10,
            'purchase_price': 45,
            'location_id': str(test_storage_location.id),
        },
        headers=auth_headers,
    )
    assert response.status_code == status.HTTP_201_CREATED
    item_id = response.json()['id']

    item = db_session.get(Item, uuid.UUID(item_id))
    assert item is not None
    assert item.template_id is not None

    layer = db_session.execute(
        select(StockValuationLayer).where(
            StockValuationLayer.product_template_id == item.template_id,
            StockValuationLayer.direction == 'IN',
        )
    ).scalar_one()

    # The rate for one, and the value of the ten — not 45 split across them.
    assert layer.unit_cost == Decimal('45.00')
    assert layer.quantity == Decimal('10')
    assert layer.total_value == Decimal('450.00')


def test_the_column_that_was_never_filled_in_is_gone(db_session: Session) -> None:
    """`price_per_unit` was the twin that made the naming a trap.

    It sat beside `purchase_price` commented "price per kg/L", was written by
    nothing, read by nothing, and returned null on every row since the initial
    schema — while the field *not* named per-unit was the per-unit one.
    """
    assert not hasattr(Item, 'price_per_unit')
