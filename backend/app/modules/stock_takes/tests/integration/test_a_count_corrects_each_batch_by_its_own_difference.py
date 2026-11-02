"""A count corrects every batch on the shelf by that batch's own difference.

A count row counts one record, and the record names its batch and owner
(``Item.lot_id``, ``Item.owner_id``). Closing the count set each record to
what was counted and settled the quants per batch — but only per batch a row
*named*. The count screen names none, so every row's difference went into one
pot for the shelf: two batches counted two up and two down cancelled out and
no quant moved at all, and a shortage on a consignor's record came off the
organization's own quant, the one the removal strategy reached first.

A row's difference now belongs to the batch it names or, naming none, to its
record's own batch and owner. A record that names no batch takes the one the
counter named: that is the count telling the record which batch it holds.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_quants_from_records import stock_quants_from_records
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.stock_takes.models import StockTake, StockTakeItem, StockTakeStatus
from tests.integration._shelf import (
    anchor_pending_records,
    put_on_shelf,
    run_in_async_session,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def org(db_session: Session) -> Organization:
    return ModuleTestHelper(db_session).create_org(
        'Batch Grain Count Org',
        ['core', 'items', 'locations', 'categories', 'stock_takes'],
    )


@pytest.fixture
def user(db_session: Session, org: Organization) -> User:
    return ModuleTestHelper(db_session).create_user(org, email='grain@example.com')


@pytest.fixture
def headers(db_session: Session, user: User) -> dict[str, str]:
    return ModuleTestHelper(db_session).get_auth_headers(user)


class _Shelf:
    """One product on one shelf.

    Stock arrives the way the application puts it there, as a record through
    the items service (``stock``). ``record`` writes one by hand, for the one
    shape no door builds any more: a record that names no batch over stock
    that is in one.
    """

    def __init__(
        self, db: Session, org: Organization, user: User, engine: AsyncEngine
    ) -> None:
        h = ModuleTestHelper(db)
        storage_type = h.create_storage_type(
            'Warehouse', 'WAREHOUSE', organization_id=org.id
        )
        self.db = db
        self.engine = engine
        self.org = org
        self.user = user
        self.location: StorageLocation = h.create_storage_location(
            org, storage_type, user, name='Counted Shelf'
        )
        self.template: ProductTemplate = h.create_template(org, name='Counted Goods')

    def batch(self, name: str) -> StockLot:
        lot = StockLot(
            organization_id=self.org.id,
            product_template_id=self.template.id,
            name=name,
        )
        self.db.add(lot)
        self.db.flush()
        return lot

    def consignor(self) -> Partner:
        partner = Partner(
            organization_id=self.org.id, name='Consignor', type='SUPPLIER'
        )
        self.db.add(partner)
        self.db.flush()
        return partner

    def stock(
        self,
        qty: str,
        *,
        lot: StockLot | None = None,
        owner: Partner | None = None,
    ) -> Item:
        self.db.commit()

        async def _put(session: AsyncSession) -> UUID:
            record = await put_on_shelf(
                session,
                self.user,
                self.template,
                self.location.id,
                qty,
                lot_id=lot.id if lot else None,
                owner_id=owner.id if owner else None,
            )
            return record.id

        item_id = run_in_async_session(self.engine, _put)
        self.db.expire_all()
        item = self.db.get(Item, item_id)
        assert item is not None
        return item

    def record(
        self,
        qty: str,
        *,
        lot: StockLot | None = None,
        owner: Partner | None = None,
    ) -> Item:
        item = Item(
            organization_id=self.org.id,
            name='Counted Goods',
            template_id=self.template.id,
            storage_location_id=self.location.id,
            lot_id=lot.id if lot else None,
            owner_id=owner.id if owner else None,
            quantity=Decimal(qty),
        )
        self.db.add(item)
        anchor_pending_records(self.db)
        self.db.flush()
        return item

    def count(
        self,
        client: TestClient,
        headers: dict[str, str],
        rows: list[tuple[Item, str, StockLot | None]],
    ) -> None:
        stock_take = StockTake(
            user_id=self.user.id,
            organization_id=self.org.id,
            storage_location_id=self.location.id,
            name='Grain count',
            status=StockTakeStatus.IN_PROGRESS,
        )
        self.db.add(stock_take)
        self.db.flush()
        for item, counted, named in rows:
            self.db.add(
                StockTakeItem(
                    stock_take_id=stock_take.id,
                    item_id=item.id,
                    item_name=item.name,
                    system_quantity=item.quantity,
                    counted_quantity=Decimal(counted),
                    lot_id=named.id if named else None,
                )
            )
        self.db.commit()
        resp = client.post(
            f'/api/v1/stock-takes/{stock_take.id}/complete',
            headers=headers,
            json={'apply_adjustments': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

    def records(self) -> dict[tuple[UUID | None, UUID | None], Decimal]:
        """What the records of the shelf hold per batch and owner.

        The count settles on this side, and a test of what the count wrote
        reads the view the readers ask for it.
        """
        return self._by_batch(
            select(
                stock_quants_from_records.c.lot_id,
                stock_quants_from_records.c.owner_id,
                stock_quants_from_records.c.quantity,
            ).where(stock_quants_from_records.c.product_template_id == self.template.id)
        )

    def _by_batch(
        self, statement: Any
    ) -> dict[tuple[UUID | None, UUID | None], Decimal]:
        self.db.expire_all()
        rows = self.db.execute(statement).all()
        return {(lot, owner): qty for lot, owner, qty in rows}


def test_two_batches_counted_up_and_down_each_take_their_own_difference(
    client: TestClient,
    headers: dict[str, str],
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    org: Organization,
    user: User,
) -> None:
    shelf = _Shelf(db_session, org, user, async_engine_fixture)
    first, second = shelf.batch('LOT-A'), shelf.batch('LOT-B')
    on_first = shelf.stock('10', lot=first)
    on_second = shelf.stock('5', lot=second)

    # The count screen names no batch: the rows say only what they counted.
    shelf.count(client, headers, [(on_first, '8', None), (on_second, '7', None)])

    assert shelf.records() == {
        (first.id, None): Decimal('8'),
        (second.id, None): Decimal('7'),
    }


def test_a_shortage_on_a_consignors_record_comes_off_the_consignors_stock(
    client: TestClient,
    headers: dict[str, str],
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    org: Organization,
    user: User,
) -> None:
    shelf = _Shelf(db_session, org, user, async_engine_fixture)
    consignor = shelf.consignor()
    # The organization's own stock arrives first, so the removal strategy
    # would reach for it.
    shelf.stock('5')
    consigned = shelf.stock('5', owner=consignor)

    shelf.count(client, headers, [(consigned, '3', None)])

    assert shelf.records() == {
        (None, None): Decimal('5'),
        (None, consignor.id): Decimal('3'),
    }


def test_a_record_that_names_no_batch_takes_the_one_the_counter_named(
    client: TestClient,
    headers: dict[str, str],
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    org: Organization,
    user: User,
) -> None:
    shelf = _Shelf(db_session, org, user, async_engine_fixture)
    lot = shelf.batch('LOT-SEEN')
    # Written by hand on purpose: a record that does not know the batch its
    # stock is in is what a path that never set the record's batch left
    # behind, and it is the record this rule is for. The count names the
    # batch and the record takes it.
    record = shelf.record('6')
    db_session.commit()

    shelf.count(client, headers, [(record, '9', lot)])

    db_session.expire_all()
    assert db_session.execute(
        select(Item.lot_id, Item.quantity).where(Item.id == record.id)
    ).one() == (lot.id, Decimal('9'))
    assert shelf.records() == {(lot.id, None): Decimal('9')}
