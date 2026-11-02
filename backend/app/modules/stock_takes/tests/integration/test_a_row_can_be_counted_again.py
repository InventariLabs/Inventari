"""Counting a row a second time, without losing the first answer.

A stock take knew two answers to a difference: post it, or (past the hard
growth cap) have a supervisor wave it through. The one the trade reaches for
first was missing — count it again. SAP raises a recount document against
the original, Dynamics hangs a second recording off the same inventory
order, and a WMS issues a second count task on its own once a variance
crosses the threshold. All three keep both numbers, because two people
arriving at the same figure is what makes the correction believable, and a
disagreement between them is information of its own.

So a pass is a row of its own, a recount is a deliberate second look rather
than a re-save, and the stock take will not post a row it has been asked to
check again.
"""

from __future__ import annotations

from decimal import Decimal
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
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.stock_takes.models import (
    StockTake,
    StockTakeCount,
    StockTakeItem,
    StockTakeStatus,
)
from tests.integration._shelf import post_on_shelf


@pytest.fixture
def again_org(db_session: Session) -> Organization:
    return ModuleTestHelper(db_session).create_org(
        'Recount Org', ['core', 'items', 'locations', 'categories', 'stock_takes']
    )


@pytest.fixture
def again_user(db_session: Session, again_org: Organization) -> User:
    return ModuleTestHelper(db_session).create_user(
        again_org, email='again@example.com'
    )


@pytest.fixture
def again_headers(db_session: Session, again_user: User) -> dict[str, str]:
    return ModuleTestHelper(db_session).get_auth_headers(again_user)


@pytest.fixture
def again_location(
    db_session: Session, again_org: Organization, again_user: User
) -> StorageLocation:
    h = ModuleTestHelper(db_session)
    storage_type = h.create_storage_type(
        'Warehouse', 'WAREHOUSE', organization_id=again_org.id
    )
    return h.create_storage_location(
        again_org, storage_type, again_user, name='Disputed shelf'
    )


@pytest.fixture
def again_item(
    client: TestClient,
    again_headers: dict[str, str],
    db_session: Session,
    again_org: Organization,
    again_location: StorageLocation,
) -> Item:
    template: ProductTemplate = ModuleTestHelper(db_session).create_template(
        again_org, name='Disputed Goods'
    )
    db_session.commit()
    record = post_on_shelf(client, again_headers, template, again_location.id, 10)
    db_session.expire_all()
    item = db_session.get(Item, UUID(record['id']))
    assert item is not None
    return item


@pytest.fixture
def again_take(
    db_session: Session,
    again_org: Organization,
    again_user: User,
    again_location: StorageLocation,
    again_item: Item,
) -> StockTake:
    stock_take = StockTake(
        user_id=again_user.id,
        organization_id=again_org.id,
        storage_location_id=again_location.id,
        name='Disputed count',
        status=StockTakeStatus.IN_PROGRESS,
    )
    db_session.add(stock_take)
    db_session.flush()
    db_session.add(
        StockTakeItem(
            stock_take_id=stock_take.id,
            item_id=again_item.id,
            item_name=again_item.name,
            system_quantity=Decimal('10'),
        )
    )
    db_session.commit()
    db_session.refresh(stock_take)
    return stock_take


def _line_id(db_session: Session, take_id: UUID) -> UUID:
    return db_session.execute(
        select(StockTakeItem.id).where(StockTakeItem.stock_take_id == take_id)
    ).scalar_one()


def _passes(db_session: Session, line_id: UUID) -> list[StockTakeCount]:
    db_session.expire_all()
    return list(
        db_session.execute(
            select(StockTakeCount)
            .where(StockTakeCount.stock_take_item_id == line_id)
            .order_by(StockTakeCount.sequence)
        )
        .scalars()
        .all()
    )


def _count(
    client: TestClient, headers: dict[str, str], take_id: UUID, line_id: UUID, qty: int
) -> None:
    resp = client.patch(
        f'/api/v1/stock-takes/{take_id}/items/{line_id}/count',
        headers=headers,
        json={'counted_quantity': qty},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text


@pytest.mark.integration
class TestARowCanBeCountedAgain:
    def test_the_second_answer_does_not_replace_the_first(
        self,
        client: TestClient,
        again_headers: dict[str, str],
        db_session: Session,
        again_take: StockTake,
        again_user: User,
    ) -> None:
        line_id = _line_id(db_session, again_take.id)
        _count(client, again_headers, again_take.id, line_id, 4)

        resp = client.post(
            f'/api/v1/stock-takes/{again_take.id}/items/{line_id}/recount',
            headers=again_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['recount_requested'] is True

        _count(client, again_headers, again_take.id, line_id, 9)

        passes = _passes(db_session, line_id)
        assert [p.sequence for p in passes] == [1, 2]
        assert [p.quantity for p in passes] == [Decimal('4.000'), Decimal('9.000')]
        # Who gave each number, so a disagreement has two names behind it.
        assert all(p.counted_by == again_user.id for p in passes)

    def test_saving_the_same_row_twice_is_one_pass(
        self,
        client: TestClient,
        again_headers: dict[str, str],
        db_session: Session,
        again_take: StockTake,
    ) -> None:
        # The control. Fixing a typed number is not a second opinion; if it
        # were, "counted twice and they agreed" would be true of every row
        # anybody double-tapped and would mean nothing.
        line_id = _line_id(db_session, again_take.id)
        _count(client, again_headers, again_take.id, line_id, 4)
        _count(client, again_headers, again_take.id, line_id, 5)

        passes = _passes(db_session, line_id)
        assert len(passes) == 1
        assert passes[0].quantity == Decimal('5.000')

    def test_the_count_will_not_close_over_a_row_it_asked_about(
        self,
        client: TestClient,
        again_headers: dict[str, str],
        db_session: Session,
        again_take: StockTake,
        again_item: Item,
    ) -> None:
        line_id = _line_id(db_session, again_take.id)
        _count(client, again_headers, again_take.id, line_id, 4)
        client.post(
            f'/api/v1/stock-takes/{again_take.id}/items/{line_id}/recount',
            headers=again_headers,
        )

        resp = client.post(
            f'/api/v1/stock-takes/{again_take.id}/complete',
            headers=again_headers,
            json={'apply_adjustments': True},
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        assert 'awaiting_recount_items' in str(resp.json())

        # Posting it would make the recount pointless: the stock would
        # already hold the number somebody asked to have checked.
        db_session.expire_all()
        assert db_session.execute(
            select(Item.quantity).where(Item.id == again_item.id)
        ).scalar_one() == Decimal('10')

    def test_counting_it_again_clears_the_way(
        self,
        client: TestClient,
        again_headers: dict[str, str],
        db_session: Session,
        again_take: StockTake,
        again_item: Item,
    ) -> None:
        line_id = _line_id(db_session, again_take.id)
        _count(client, again_headers, again_take.id, line_id, 4)
        client.post(
            f'/api/v1/stock-takes/{again_take.id}/items/{line_id}/recount',
            headers=again_headers,
        )
        _count(client, again_headers, again_take.id, line_id, 9)

        resp = client.post(
            f'/api/v1/stock-takes/{again_take.id}/complete',
            headers=again_headers,
            json={'apply_adjustments': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.expire_all()
        # The recount is the count of record: it is the second look, and the
        # one the stock follows.
        assert db_session.execute(
            select(Item.quantity).where(Item.id == again_item.id)
        ).scalar_one() == Decimal('9')

    def test_the_row_reports_both_passes(
        self,
        client: TestClient,
        again_headers: dict[str, str],
        db_session: Session,
        again_take: StockTake,
    ) -> None:
        line_id = _line_id(db_session, again_take.id)
        _count(client, again_headers, again_take.id, line_id, 4)
        client.post(
            f'/api/v1/stock-takes/{again_take.id}/items/{line_id}/recount',
            headers=again_headers,
        )
        _count(client, again_headers, again_take.id, line_id, 9)

        detail = client.get(
            f'/api/v1/stock-takes/{again_take.id}', headers=again_headers
        )
        assert detail.status_code == status.HTTP_200_OK, detail.text
        row = detail.json()['items'][0]
        assert [c['sequence'] for c in row['counts']] == [1, 2]
        assert [Decimal(c['quantity']) for c in row['counts']] == [4, 9]
        assert row['counts'][0]['counted_by_name'] is not None
