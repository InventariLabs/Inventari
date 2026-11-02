"""What the purchase report says was spent is what the ledger says it cost.

The report summed price × quantity in SQL, cast the Decimal to a float and
called ``round`` on it. The valuation engine rounds the same product half
away from zero. On 2.275 — a half, but a hair under it in binary — the two
disagreed by a cent, on the one screen a person opens to compare them.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation

pytestmark = pytest.mark.integration


def _buy(
    client: TestClient,
    auth_headers: dict[str, str],
    storage_id: UUID,
    *,
    quantity: str,
    price: str,
    uom_id: str,
) -> None:
    response = client.post(
        '/api/v1/items',
        headers=auth_headers,
        json={
            'name': 'Milk',
            'quantity': quantity,
            'uom_id': uom_id,
            'purchase_price': price,
            'location_id': str(storage_id),
        },
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text


def test_total_spent_equals_the_sum_of_the_receipt_layers(
    client: TestClient,
    auth_headers: dict[str, str],
    test_storage_location: StorageLocation,
    db_session: Session,
) -> None:
    # 0.5 × 2.55 = 1.275 and 1 × 1.00: together 2.275, a half the float
    # cannot see. Half away from zero says 2.28; round(float) said 2.27.
    # Half a litre is a quantity — a record that names no unit is measured in
    # pieces, and pieces count whole.
    from app.models.uom import Uom

    litre = db_session.scalars(select(Uom).where(Uom.symbol == 'l')).first()
    assert litre is not None, "'l' is not in the seeded catalogue"
    _buy(
        client,
        auth_headers,
        test_storage_location.id,
        quantity='0.5',
        price='2.55',
        uom_id=str(litre.id),
    )
    _buy(
        client,
        auth_headers,
        test_storage_location.id,
        quantity='1',
        price='1.00',
        uom_id=str(litre.id),
    )

    ledger = db_session.scalars(
        select(StockValuationLayer.total_value).where(
            StockValuationLayer.organization_id
            == test_storage_location.organization_id,
            StockValuationLayer.direction == 'IN',
        )
    ).all()
    assert len(ledger) == 2, 'each priced record opens one receipt layer'
    what_it_cost = sum(ledger, Decimal('0'))
    assert what_it_cost == Decimal('2.28')

    response = client.get('/api/v1/stats/purchase-patterns', headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK
    milk = next(
        p for p in response.json()['top_recurring_products'] if p['name'] == 'Milk'
    )

    assert Decimal(str(milk['total_spent'])) == what_it_cost
