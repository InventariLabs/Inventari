"""The value reports agree with the ledger, and the ledger agrees with itself.

Three figures describe what the stock is worth: the overview tile, the
stock-as-of report for today, and the sum of the receipt layers still on
the shelf. They are one number, read three ways — and each says which
source it read, so a report off the records' prices is never mistaken for
one off the ledger.

The equation of stock is the stronger claim: what was bought, less what
left at the cost it actually carried, is what is standing there. It holds
only because an outflow is priced by the layers it drained; valued at an
average of what remained, ten bought at 1.00 and ten at 3.00 with ten gone
left 40.00 in, 20.00 out and 30.00 standing — ten from nowhere.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.stock_valuation_layer import StockValuationLayer

pytestmark = pytest.mark.integration


def _buy(
    client: TestClient,
    headers: dict[str, str],
    storage_id: Any,
    *,
    name: str,
    quantity: str,
    price: str,
) -> str:
    response = client.post(
        '/api/v1/items',
        headers=headers,
        json={
            'name': name,
            'quantity': quantity,
            'purchase_price': price,
            'location_id': str(storage_id),
        },
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return str(response.json()['id'])


def _use(
    client: TestClient, headers: dict[str, str], item_id: str, quantity: str
) -> None:
    response = client.patch(
        f'/api/v1/items/{item_id}/consume', headers=headers, json={'quantity': quantity}
    )
    assert response.status_code == status.HTTP_200_OK, response.text


def _get(client: TestClient, headers: dict[str, str], path: str, **params: Any) -> Any:
    response = client.get(path, headers=headers, params=params)
    assert response.status_code == status.HTTP_200_OK, response.text
    return response.json()


def _ledger(db: Session, org_id: Any) -> dict[str, Decimal]:
    layers = db.scalars(
        select(StockValuationLayer).where(StockValuationLayer.organization_id == org_id)
    ).all()
    zero = Decimal('0')
    return {
        'bought': sum((r.total_value for r in layers if r.direction == 'IN'), zero),
        'left': sum((r.total_value for r in layers if r.direction == 'OUT'), zero),
        'standing': sum(
            (r.remaining_qty * r.unit_cost for r in layers if r.direction == 'IN'), zero
        ),
    }


@pytest.fixture
def two_deliveries_and_one_issue(client, auth_headers, test_storage_location):
    """Ten at 1.00, ten at 3.00, then ten of the first used — the worked example."""
    cheap = _buy(
        client,
        auth_headers,
        test_storage_location.id,
        name='Cheap batch',
        quantity='10',
        price='1.00',
    )
    _buy(
        client,
        auth_headers,
        test_storage_location.id,
        name='Dear batch',
        quantity='10',
        price='3.00',
    )
    _use(client, auth_headers, cheap, '10')
    return test_storage_location.organization_id


class TestTheEquationOfStock:
    def test_bought_less_left_is_what_is_standing(
        self, two_deliveries_and_one_issue, db_session
    ) -> None:
        ledger = _ledger(db_session, two_deliveries_and_one_issue)

        assert ledger['bought'] == Decimal('40.00')
        assert ledger['left'] == Decimal('10.00')
        assert (
            ledger['bought'] - ledger['left'] == ledger['standing'] == Decimal('30.00')
        )


class TestTheReportsReadOneNumber:
    def test_the_overview_and_the_as_of_report_say_what_the_ledger_says(
        self, client, auth_headers, two_deliveries_and_one_issue, db_session
    ) -> None:
        standing = _ledger(db_session, two_deliveries_and_one_issue)['standing']

        overview = _get(client, auth_headers, '/api/v1/stats/overview')
        assert overview['value_source'] == 'valuation_layers'
        assert Decimal(str(overview['total_value'])) == standing

        today = _get(
            client,
            auth_headers,
            '/api/v1/stock-as-of',
            as_of=datetime.now(UTC).isoformat(),
        )
        assert today['value_source'] == 'valuation_layers'
        assert Decimal(today['total_value']) == standing

    def test_what_was_spent_is_what_the_receipts_cost(
        self, client, auth_headers, two_deliveries_and_one_issue, db_session
    ) -> None:
        bought = _ledger(db_session, two_deliveries_and_one_issue)['bought']

        summary = _get(client, auth_headers, '/api/v1/stats/cost-analysis')
        assert summary['value_source'] == 'valuation_layers'
        assert Decimal(str(summary['total_spent'])) == bought

    def test_every_value_report_names_its_source(
        self, client, auth_headers, two_deliveries_and_one_issue
    ) -> None:
        """A figure whose source cannot be named is a figure nobody can check."""
        off_the_ledger = {
            '/api/v1/stats/overview',
            '/api/v1/stats/cost-analysis',
            '/api/v1/stats/expense-forecast',
        }
        off_the_records = {
            '/api/v1/stats/rotation-analysis',
            '/api/v1/stats/purchase-patterns',
        }
        for path in off_the_ledger:
            assert (
                _get(client, auth_headers, path)['value_source'] == 'valuation_layers'
            ), path
        for path in off_the_records:
            assert (
                _get(client, auth_headers, path)['value_source'] == 'purchase_price'
            ), path
        for row in _get(client, auth_headers, '/api/v1/stats/by-category')['items']:
            assert row['value_source'] == 'purchase_price'
