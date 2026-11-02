"""Goods nobody had a record of reach the shelf when the count closes, once.

The counting screen opens a record for a product found on the shelf, then
records the find as a surplus row of the count. It used to open the record
holding the counted quantity: the goods were on the shelf before anyone
closed the count, a cancelled count left them there, the row's baseline read
the same number as its count, and the correction document closing the count
had no line for them — the shelf grew with only an opening movement behind
it and the count reporting nothing found.

The record is now opened holding nothing, the way the screen asks for it
here: the count holds the find until it closes, and closing it posts the
surplus once — in the report, the correction document and the movements.
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
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.stock_takes.models import StockTake, StockTakeStatus
from app.modules.warehouse.models import Document


def _shop(db_session: Session) -> tuple[Organization, User, StorageLocation]:
    helper = ModuleTestHelper(db_session)
    org = helper.create_org(
        'Found Goods Shop',
        ['core', 'items', 'locations', 'categories', 'stock_takes', 'warehouse'],
    )
    user = helper.create_user(org, email='finder@example.com')
    storage_type = helper.create_storage_type('Shelf', 'SHELF', organization_id=org.id)
    shelf = helper.create_storage_location(org, storage_type, user, name='Shelf A')
    return org, user, shelf


def _count_of(
    db_session: Session, org: Organization, user: User, shelf: StorageLocation
) -> UUID:
    stock_take = StockTake(
        user_id=user.id,
        organization_id=org.id,
        storage_location_id=shelf.id,
        name='Shelf A, Monday',
        status=StockTakeStatus.IN_PROGRESS,
    )
    db_session.add(stock_take)
    db_session.commit()
    return stock_take.id


def _found(
    client: TestClient,
    headers: dict[str, str],
    take_id: UUID,
    shelf: StorageLocation,
    counted: int,
) -> dict[str, Any]:
    """What the counting screen sends for a product nobody had a record of."""
    created = client.post(
        '/api/v1/items',
        headers=headers,
        json={
            'name': 'Found product',
            'quantity': 0,
            'unit_confirmed_over_template': False,
            'location_id': str(shelf.id),
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    row = client.post(
        f'/api/v1/stock-takes/{take_id}/items',
        headers=headers,
        json={'item_id': created.json()['id'], 'counted_quantity': counted},
    )
    assert row.status_code == status.HTTP_201_CREATED, row.text
    return dict(row.json())


def _moves_of(db_session: Session, item_id: UUID) -> list[StockMove]:
    """The ledger of the product the record stands for."""
    db_session.expire_all()
    record = db_session.get(Item, item_id)
    assert record is not None
    return list(
        db_session.execute(
            select(StockMove).where(StockMove.product_template_id == record.template_id)
        )
        .scalars()
        .all()
    )


def _held(db_session: Session, item_id: UUID) -> Decimal:
    db_session.expire_all()
    record = db_session.get(Item, item_id)
    assert record is not None
    return Decimal(record.quantity)


@pytest.mark.integration
class TestAProductFoundDuringACountWaitsForItsClose:
    def test_the_find_is_not_on_the_shelf_before_the_count_closes(
        self, client: TestClient, db_session: Session
    ) -> None:
        org, user, shelf = _shop(db_session)
        headers = ModuleTestHelper(db_session).get_auth_headers(user)
        take_id = _count_of(db_session, org, user, shelf)

        row = _found(client, headers, take_id, shelf, 2)

        item_id = UUID(row['item_id'])
        assert Decimal(row['system_quantity']) == 0
        assert Decimal(row['counted_quantity']) == 2
        assert row['is_discrepancy'] == 1
        assert _held(db_session, item_id) == 0
        assert _moves_of(db_session, item_id) == []

        cancelled = client.patch(
            f'/api/v1/stock-takes/{take_id}/status',
            headers=headers,
            json={'status': 'cancelled'},
        )
        assert cancelled.status_code == status.HTTP_200_OK, cancelled.text

        assert _held(db_session, item_id) == 0
        assert _moves_of(db_session, item_id) == []

    def test_closing_the_count_posts_the_find_once_everywhere(
        self, client: TestClient, db_session: Session
    ) -> None:
        org, user, shelf = _shop(db_session)
        headers = ModuleTestHelper(db_session).get_auth_headers(user)
        take_id = _count_of(db_session, org, user, shelf)
        item_id = UUID(_found(client, headers, take_id, shelf, 2)['item_id'])

        closed = client.post(
            f'/api/v1/stock-takes/{take_id}/complete',
            headers=headers,
            json={'apply_adjustments': True, 'force_over_tolerance': True},
        )
        assert closed.status_code == status.HTTP_200_OK, closed.text
        report = closed.json()

        assert _held(db_session, item_id) == 2
        [found] = [
            r for r in report['discrepancy_items'] if r['item_id'] == str(item_id)
        ]
        assert Decimal(found['difference']) == 2

        [document] = (
            db_session.execute(
                select(Document).where(Document.organization_id == org.id)
            )
            .scalars()
            .all()
        )
        assert report['adjustment_document_id'] == str(document.id)
        assert [(line.name, line.done_quantity) for line in document.lines] == [
            ('Found product', Decimal('2'))
        ]

        moves = _moves_of(db_session, item_id)
        assert [
            (
                move.quantity,
                move.from_location_id,
                move.to_location_id,
                move.reference_id,
            )
            for move in moves
        ] == [(Decimal('2'), None, shelf.id, document.id)]
