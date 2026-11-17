"""Purchase patterns read the records that were bought, and only those.

A record comes to exist in more ways than a purchase: opening one unit of a
package splits a record, a split transfer leaves a remainder, a stock count
finds a surplus. None of them is something somebody bought, so none adds to
the number of purchases, and the price spread of a product is measured over
the same records the count reads — the window, the internal storage and the
hidden modules included.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.item_history import ItemAction, ItemHistory
from app.models.storage_location import StorageLocation
from app.models.user import User

pytestmark = pytest.mark.integration

URL = '/api/v1/stats/purchase-patterns'


def _born(
    db: Session,
    user: User,
    shelf: StorageLocation,
    name: str,
    price: str,
    *,
    why: dict[str, Any] | None = None,
    days_ago: int = 5,
) -> Item:
    """A record born *days_ago*, with the history row its birth writes."""
    born_at = datetime.now(UTC) - timedelta(days=days_ago)
    item = Item(
        organization_id=user.organization_id,
        storage_location_id=shelf.id,
        name=name,
        quantity=Decimal('1'),
        purchase_price=Decimal(price),
        currency='USD',
        created_at=born_at,
    )
    db.add(item)
    db.flush()
    db.add(
        ItemHistory(
            organization_id=user.organization_id,
            item_id=item.id,
            user_id=user.id,
            action=ItemAction.CREATED.value,
            changes={'created': True, **(why or {})},
            created_at=born_at,
        )
    )
    db.commit()
    return item


def _row(client: TestClient, headers: dict[str, str], name: str) -> dict[str, Any]:
    response = client.get(URL, headers=headers)
    assert response.status_code == status.HTTP_200_OK, response.text
    rows = {r['name']: r for r in response.json()['top_recurring_products']}
    row: dict[str, Any] = rows.get(name, {})
    return row


def test_births_that_are_not_purchases_are_not_counted(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_user: User,
    test_storage_location: StorageLocation,
) -> None:
    args = (db_session, test_user, test_storage_location, 'Olive oil', '30.00')
    _born(*args)
    _born(*args, why={'reason': 'package_opened'})
    _born(
        *args,
        why={
            'reason': 'document_execution',
            'document_type': 'INT',
            'document_number': 'INT/2026/001',
        },
    )
    _born(*args, why={'reason': 'stock_take_adjustment'})
    _born(*args, why={'reason': 'production_run_reversed'})
    # Bought on a receipt (the warehouse writes the document type IN) or
    # added by an AI agent: purchases like the one entered by hand.
    _born(
        *args,
        why={
            'reason': 'document_execution',
            'document_type': 'IN',
            'document_number': 'IN/2026/001',
        },
    )
    _born(*args, why={'reason': 'mcp_create'})
    # Typed in a unit other than the card's and confirmed: the history row
    # says which unit was chosen, not that the record is anything but bought.
    _born(
        *args,
        why={
            'reason': 'unit_chosen_over_template',
            'template_uom': 'kg',
            'chosen_uom': 'g',
        },
    )

    row = _row(client, auth_headers, 'Olive oil')

    assert row['total_purchases_last_6_months'] == 4


def test_price_volatility_reads_the_purchases_the_count_reads(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_user: User,
    test_storage_location: StorageLocation,
) -> None:
    for price in ('20.00', '24.00'):
        _born(db_session, test_user, test_storage_location, 'Wine', price)
    # Two runs of the wine at the cost of the grapes, and a purchase from
    # before the window: none of them is a price somebody paid in it.
    for _ in range(2):
        _born(
            db_session,
            test_user,
            test_storage_location,
            'Wine',
            '7.50',
            why={'reason': 'production_run'},
        )
    _born(db_session, test_user, test_storage_location, 'Wine', '2.00', days_ago=300)

    row = _row(client, auth_headers, 'Wine')

    assert row['total_purchases_last_6_months'] == 2
    # 20 and 24 spread 12.9%: medium, not what the runs' cost would make of it.
    assert row['price_volatility'] == 'medium'
