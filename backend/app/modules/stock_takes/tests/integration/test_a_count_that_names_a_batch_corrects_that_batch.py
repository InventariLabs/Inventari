"""A count that names a batch must correct that batch.

``StockTakeItem`` has carried a ``lot_id`` since counting began, and
finalize threw it away. The write-back went through the generic per-item
bridge, which increments the lot-less quant on principle and decrements
across lots by removal strategy — so a surplus counted on batch B landed on
the batch-less pile, and a shortage counted on B could be taken off A.
The batch column recorded what the counter saw and changed nothing.

The move it produced said ``reference_type='item'`` — a one-off user edit —
for a posting that is a stock-take correction, which is what 'adjustment'
has meant in the vocabulary all along.
"""

from __future__ import annotations

from decimal import Decimal
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
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove
from app.models.stock_quants_from_records import stock_quants_from_records
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.stock_takes.models import StockTake, StockTakeItem, StockTakeStatus
from tests.integration._shelf import put_on_shelf, run_in_async_session


@pytest.fixture
def count_org(db_session: Session) -> Organization:
    h = ModuleTestHelper(db_session)
    return h.create_org(
        'Batch Count Org',
        ['core', 'items', 'locations', 'categories', 'stock_takes'],
    )


@pytest.fixture
def count_user(db_session: Session, count_org: Organization) -> User:
    return ModuleTestHelper(db_session).create_user(
        count_org, email='counter@example.com'
    )


@pytest.fixture
def count_headers(db_session: Session, count_user: User) -> dict[str, str]:
    return ModuleTestHelper(db_session).get_auth_headers(count_user)


@pytest.fixture
def count_location(
    db_session: Session, count_org: Organization, count_user: User
) -> StorageLocation:
    h = ModuleTestHelper(db_session)
    storage_type = h.create_storage_type(
        'Warehouse', 'WAREHOUSE', organization_id=count_org.id
    )
    return h.create_storage_location(
        count_org, storage_type, count_user, name='Counted Warehouse'
    )


@pytest.fixture
def count_template(db_session: Session, count_org: Organization) -> ProductTemplate:
    return ModuleTestHelper(db_session).create_template(count_org, name='Counted Goods')


def _on_shelf(
    db_session: Session,
    engine: AsyncEngine,
    keeper: User,
    template: ProductTemplate,
    location_id: UUID,
    quantity: Decimal,
    lot_id: UUID | None = None,
) -> Item:
    """One record of *quantity* on the shelf, in the batch named, through the items service."""
    db_session.commit()

    async def _put(session: AsyncSession) -> UUID:
        record = await put_on_shelf(
            session, keeper, template, location_id, quantity, lot_id=lot_id
        )
        return record.id

    item_id = run_in_async_session(engine, _put)
    db_session.expire_all()
    item = db_session.get(Item, item_id)
    assert item is not None
    return item


def _on_hand(
    db_session: Session,
    template_id: UUID,
    location_id: UUID,
    lot_id: UUID | None = None,
) -> Decimal:
    """What the records hold for one shelf and batch — the count's own side.

    The count settles the records and never writes the quant table, so what
    the count did is read here, from the view every reader of stock asks.
    """
    db_session.expire_all()
    row = db_session.execute(
        select(stock_quants_from_records.c.quantity).where(
            stock_quants_from_records.c.product_template_id == template_id,
            stock_quants_from_records.c.storage_location_id == location_id,
            stock_quants_from_records.c.lot_id.is_(None)
            if lot_id is None
            else stock_quants_from_records.c.lot_id == lot_id,
        )
    ).one()
    return Decimal(str(row[0]))


def _count_and_finalize(
    client: TestClient,
    headers: dict[str, str],
    db_session: Session,
    *,
    org_id: UUID,
    location_id: UUID,
    user_id: UUID,
    item: Item,
    counted: Decimal,
    lot_id: UUID,
) -> None:
    stock_take = StockTake(
        user_id=user_id,
        organization_id=org_id,
        storage_location_id=location_id,
        name='Batch count',
        status=StockTakeStatus.IN_PROGRESS,
    )
    db_session.add(stock_take)
    db_session.flush()
    db_session.add(
        StockTakeItem(
            stock_take_id=stock_take.id,
            item_id=item.id,
            item_name=item.name,
            system_quantity=item.quantity,
            counted_quantity=counted,
            lot_id=lot_id,
        )
    )
    db_session.commit()

    resp = client.post(
        f'/api/v1/stock-takes/{stock_take.id}/complete',
        headers=headers,
        json={'apply_adjustments': True},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text


@pytest.mark.integration
class TestACountThatNamesABatch:
    def test_a_surplus_lands_on_the_counted_batch(
        self,
        client: TestClient,
        count_headers: dict[str, str],
        db_session: Session,
        count_org: Organization,
        count_user: User,
        count_location: StorageLocation,
        count_template: ProductTemplate,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        lot = StockLot(
            organization_id=count_org.id,
            product_template_id=count_template.id,
            name='LOT-COUNTED',
        )
        db_session.add(lot)
        db_session.flush()

        _on_shelf(
            db_session,
            async_engine_fixture,
            count_user,
            count_template,
            count_location.id,
            Decimal('4'),
        )
        item = _on_shelf(
            db_session,
            async_engine_fixture,
            count_user,
            count_template,
            count_location.id,
            Decimal('6'),
            lot_id=lot.id,
        )

        _count_and_finalize(
            client,
            count_headers,
            db_session,
            org_id=count_org.id,
            location_id=count_location.id,
            user_id=count_user.id,
            item=item,
            counted=Decimal('8'),
            lot_id=lot.id,
        )

        batch = _on_hand(db_session, count_template.id, count_location.id, lot.id)
        loose = _on_hand(db_session, count_template.id, count_location.id)
        assert batch == Decimal('8')
        assert loose == Decimal('4')

    def test_a_shortage_comes_off_the_counted_batch(
        self,
        client: TestClient,
        count_headers: dict[str, str],
        db_session: Session,
        count_org: Organization,
        count_user: User,
        count_location: StorageLocation,
        count_template: ProductTemplate,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        lot = StockLot(
            organization_id=count_org.id,
            product_template_id=count_template.id,
            name='LOT-COUNTED',
        )
        db_session.add(lot)
        db_session.flush()

        # The batch-less quant is created first, so a strategy decrement in
        # FIFO order would reach for it — which is exactly the mistake.
        _on_shelf(
            db_session,
            async_engine_fixture,
            count_user,
            count_template,
            count_location.id,
            Decimal('4'),
        )
        item = _on_shelf(
            db_session,
            async_engine_fixture,
            count_user,
            count_template,
            count_location.id,
            Decimal('6'),
            lot_id=lot.id,
        )

        _count_and_finalize(
            client,
            count_headers,
            db_session,
            org_id=count_org.id,
            location_id=count_location.id,
            user_id=count_user.id,
            item=item,
            counted=Decimal('4'),
            lot_id=lot.id,
        )

        batch = _on_hand(db_session, count_template.id, count_location.id, lot.id)
        loose = _on_hand(db_session, count_template.id, count_location.id)
        assert batch == Decimal('4')
        assert loose == Decimal('4')

    def test_the_move_says_it_was_a_stock_take_correction(
        self,
        client: TestClient,
        count_headers: dict[str, str],
        db_session: Session,
        count_org: Organization,
        count_user: User,
        count_location: StorageLocation,
        count_template: ProductTemplate,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        lot = StockLot(
            organization_id=count_org.id,
            product_template_id=count_template.id,
            name='LOT-COUNTED',
        )
        db_session.add(lot)
        db_session.flush()
        item = _on_shelf(
            db_session,
            async_engine_fixture,
            count_user,
            count_template,
            count_location.id,
            Decimal('6'),
            lot_id=lot.id,
        )
        arrived = set(
            db_session.scalars(
                select(StockMove.id).where(StockMove.organization_id == count_org.id)
            )
        )

        _count_and_finalize(
            client,
            count_headers,
            db_session,
            org_id=count_org.id,
            location_id=count_location.id,
            user_id=count_user.id,
            item=item,
            counted=Decimal('9'),
            lot_id=lot.id,
        )

        db_session.expire_all()
        # The record's own arrival is on the books as well; the count's
        # correction is the movement that came after it.
        move = db_session.scalars(
            select(StockMove).where(
                StockMove.organization_id == count_org.id,
                StockMove.product_template_id == count_template.id,
                StockMove.id.not_in(arrived),
            )
        ).one()
        assert move.reference_type == 'adjustment'
        assert move.lot_id == lot.id
