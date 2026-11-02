"""Every value report says what it is made of, and the ledger ones ignore the card.

The cost ledger knows products and dates; it does not know shelves or
categories — a layer carries a product template and nothing else. So a
report that breaks value down by location or category cannot read the
ledger, and one that does not can. Both kinds are honest about it here:
the figure carries ``value_source``, a per-category row counts the records
it could not price, and the overview says whom its figure is about — the
ledger branch used to take the storage filter and drop it, counting one
population and valuing another on the same card.

The differencing test: a price corrected on the card, with no movement
behind it, does not move a figure that reads the ledger.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item

pytestmark = pytest.mark.integration


def _buy(
    client: TestClient,
    headers: dict[str, str],
    storage_id: Any,
    *,
    name: str,
    quantity: str,
    price: str | None,
    category_id: Any = None,
) -> str:
    payload: dict[str, Any] = {
        'name': name,
        'quantity': quantity,
        'location_id': str(storage_id),
    }
    if price is not None:
        payload['purchase_price'] = price
    if category_id is not None:
        payload['category_id'] = str(category_id)
    response = client.post('/api/v1/items', headers=headers, json=payload)
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return str(response.json()['id'])


def _reprice_on_the_card(db: Session, item_id: str, price: str) -> None:
    """A correction typed on the card: no document, no layer, no movement."""
    item = db.get(Item, item_id)
    assert item is not None
    item.purchase_price = Decimal(price)
    db.commit()


def _get(client: TestClient, headers: dict[str, str], path: str) -> Any:
    response = client.get(f'/api/v1/stats/{path}', headers=headers)
    assert response.status_code == status.HTTP_200_OK, response.text
    return response.json()


class TestTheOverviewReadsTheLedger:
    def test_a_price_corrected_on_the_card_does_not_move_the_stock_value(
        self, client, auth_headers, test_storage_location, db_session
    ) -> None:
        item_id = _buy(
            client,
            auth_headers,
            test_storage_location.id,
            name='Rice',
            quantity='2',
            price='10.00',
        )
        before = _get(client, auth_headers, 'overview')
        assert before['value_source'] == 'valuation_layers'
        assert before['total_value'] == 20.0

        _reprice_on_the_card(db_session, item_id, '1000.00')

        after = _get(client, auth_headers, 'overview')
        assert after['total_value'] == 20.0

    def test_the_ledger_figure_says_it_is_the_organizations(
        self, client, auth_headers, test_storage_location
    ) -> None:
        _buy(
            client,
            auth_headers,
            test_storage_location.id,
            name='Rice',
            quantity='2',
            price='10.00',
        )
        overview = _get(client, auth_headers, 'overview')
        assert overview['value_scope'] == 'organization'


class TestAPerCategoryFigureSaysItIsOffTheRecords:
    def test_by_category_declares_its_source_and_counts_the_unpriced(
        self, client, auth_headers, test_storage_location, test_category
    ) -> None:
        _buy(
            client,
            auth_headers,
            test_storage_location.id,
            name='Rice',
            quantity='2',
            price='10.00',
            category_id=test_category.id,
        )
        _buy(
            client,
            auth_headers,
            test_storage_location.id,
            name='Gift rice',
            quantity='1',
            price=None,
            category_id=test_category.id,
        )
        rows = _get(client, auth_headers, 'by-category')['items']
        row = next(r for r in rows if r['category_id'] == str(test_category.id))

        assert row['value_source'] == 'purchase_price'
        assert row['total_value'] == 20.0
        assert row['items_count'] == 2
        assert row['unpriced_count'] == 1

    def test_the_cost_summary_totals_read_the_ledger_and_its_categories_say_they_do_not(
        self, client, auth_headers, test_storage_location, test_category, db_session
    ) -> None:
        item_id = _buy(
            client,
            auth_headers,
            test_storage_location.id,
            name='Rice',
            quantity='2',
            price='10.00',
            category_id=test_category.id,
        )
        summary = _get(client, auth_headers, 'cost-analysis')
        assert summary['value_source'] == 'valuation_layers'
        assert summary['total_spent'] == 20.0
        this_month = date.today().strftime('%Y-%m')
        trend = {row['month']: row for row in summary['monthly_trend']}
        assert trend[this_month]['spent'] == 20.0
        category = next(
            r
            for r in summary['top_expensive_categories']
            if r['category_name'] == test_category.name
        )
        assert category['value_source'] == 'purchase_price'
        assert category['total_spent'] == 20.0

        _reprice_on_the_card(db_session, item_id, '1000.00')

        again = _get(client, auth_headers, 'cost-analysis')
        assert again['total_spent'] == 20.0
        assert {r['month']: r for r in again['monthly_trend']}[this_month][
            'spent'
        ] == 20.0
        # The per-category figure follows the card, and said it would.
        category = next(
            r
            for r in again['top_expensive_categories']
            if r['category_name'] == test_category.name
        )
        assert category['total_spent'] == 2000.0


class TestRotationValuesAreWhatIsStandingThere:
    def test_slow_stock_is_worth_price_times_quantity(
        self, client, auth_headers, test_storage_location, db_session
    ) -> None:
        """A pallet of a thousand at 1.00 is not worth 1.00 of dead stock."""
        db_session.add(
            Item(
                name='Pallet of washers',
                organization_id=test_storage_location.organization_id,
                storage_location_id=test_storage_location.id,
                quantity=Decimal('1000'),
                purchase_price=Decimal('1.00'),
                added_date=date.today() - timedelta(days=45),
            )
        )
        db_session.commit()

        rotation = _get(client, auth_headers, 'rotation-analysis')

        assert rotation['value_source'] == 'purchase_price'
        assert rotation['slow_movers_value'] == 1000.0
        (row,) = rotation['slow_movers']
        assert row['value'] == 1000.0
