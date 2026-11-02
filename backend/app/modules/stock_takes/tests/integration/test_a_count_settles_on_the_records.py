"""The count settles the shelf on its records.

Closing a count measures the difference on the records of each batch and
writes it to the records, under the anchor lock the write needs: the
finalization completes, the record lands on the counted number, and the
records' view of the shelf follows it.

The ledger keeps its line too: the movement that names the count comes from
the bridge carrying each record's own delta, beside the record.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.stock_quants_from_records import stock_quants_from_records
from app.models.storage_location import StorageLocation
from app.models.user import User
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration


@pytest.fixture
def records_org(db_session: Session) -> Organization:
    return ModuleTestHelper(db_session).create_org(
        'Records Count Org',
        ['core', 'items', 'locations', 'categories', 'stock_takes', 'stats'],
    )


@pytest.fixture
def records_user(db_session: Session, records_org: Organization) -> User:
    return ModuleTestHelper(db_session).create_user(
        records_org, email='records-counter@example.com'
    )


@pytest.fixture
def records_headers(db_session: Session, records_user: User) -> dict[str, str]:
    return ModuleTestHelper(db_session).get_auth_headers(records_user)


@pytest.fixture
def records_location(
    db_session: Session, records_org: Organization, records_user: User
) -> StorageLocation:
    h = ModuleTestHelper(db_session)
    storage_type = h.create_storage_type(
        'Warehouse', 'WAREHOUSE', organization_id=records_org.id
    )
    return h.create_storage_location(
        records_org, storage_type, records_user, name='Records Warehouse'
    )


@pytest.fixture
def records_template(db_session: Session, records_org: Organization) -> ProductTemplate:
    return ModuleTestHelper(db_session).create_template(
        records_org, name='Counted Goods'
    )


def _one_count_of(
    client: TestClient,
    headers: dict[str, str],
    db_session: Session,
    record: dict[str, Any],
    counted: str,
) -> None:
    """Open a count over the shelf, count one row, and close it."""
    db_session.expire_all()
    item = db_session.get(Item, UUID(record['id']))
    assert item is not None

    created = client.post(
        '/api/v1/stock-takes',
        headers=headers,
        json={
            'name': 'Records settlement',
            'location_id': str(item.storage_location_id),
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    rows = client.get(
        f'/api/v1/stock-takes/{created.json()["id"]}/items', headers=headers
    )
    assert rows.status_code == status.HTTP_200_OK, rows.text
    [row] = rows.json()['items']

    counted_row = client.patch(
        f'/api/v1/stock-takes/{created.json()["id"]}/items/{row["id"]}/count',
        headers=headers,
        json={'counted_quantity': counted},
    )
    assert counted_row.status_code == status.HTTP_200_OK, counted_row.text

    done = client.post(
        f'/api/v1/stock-takes/{created.json()["id"]}/complete',
        headers=headers,
        json={'apply_adjustments': True},
    )
    assert done.status_code == status.HTTP_200_OK, done.text


def _quantity_in_the_view(
    db_session: Session, template_id: UUID, location_id: UUID
) -> Decimal:
    total = db_session.execute(
        select(stock_quants_from_records.c.quantity).where(
            stock_quants_from_records.c.product_template_id == template_id,
            stock_quants_from_records.c.storage_location_id == location_id,
        )
    ).all()
    return sum((Decimal(str(row[0])) for row in total), Decimal('0'))


@pytest.mark.integration
class TestTheCountSettlesOnTheRecords:
    def test_the_finalization_settles_the_record_and_the_shelf(
        self,
        client: TestClient,
        db_session: Session,
        records_org: Organization,
        records_user: User,
        records_headers: dict[str, str],
        records_location: StorageLocation,
        records_template: ProductTemplate,
    ) -> None:
        record = post_on_shelf(
            client, records_headers, records_template, records_location.id, 10
        )
        _one_count_of(client, records_headers, db_session, record, '8')

        db_session.expire_all()
        item = db_session.get(Item, UUID(record['id']))
        assert item is not None
        assert item.quantity == Decimal('8.000')
        # The records' view of the shelf follows the records — that view is
        # what every reader of stock asks.
        assert _quantity_in_the_view(
            db_session, records_template.id, records_location.id
        ) == Decimal('8.000')

    def test_the_movement_names_the_count(
        self,
        client: TestClient,
        db_session: Session,
        records_org: Organization,
        records_user: User,
        records_headers: dict[str, str],
        records_location: StorageLocation,
        records_template: ProductTemplate,
    ) -> None:
        record = post_on_shelf(
            client, records_headers, records_template, records_location.id, 10
        )
        _one_count_of(client, records_headers, db_session, record, '8')

        db_session.expire_all()
        movements = db_session.scalars(
            select(StockMove).where(
                StockMove.organization_id == records_org.id,
                StockMove.from_location_id.is_not(None),
            )
        ).all()
        assert len(movements) == 1
        assert movements[0].reference_type == 'adjustment'
        assert movements[0].quantity == Decimal('2')
