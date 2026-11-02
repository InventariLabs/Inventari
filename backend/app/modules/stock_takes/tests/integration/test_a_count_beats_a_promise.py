"""A count is the truth about the shelf, and two rules used to outrank it.

A shortage on goods somebody had reserved could not be posted at all. The
shelf refuses to be taken below what is held — right for a dispatch, which
must not eat into another document's claim — and the count went through the
same door, so the whole finalization came back as a 400. Nothing was
recorded, the shelf kept a number the counter had just disproved, and the
reservation kept protecting stock that is not there. Odoo and ERPNext both
give way here: a physical count releases what it cannot back.

And accepting a count far above the system quantity — the guard against a
typed 200 for 20 — asked for nothing beyond the permission to count. Its
neighbour, accepting a difference beyond the organization's tolerance, asks
for the approval permission, and the cap is the larger claim of the two.
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

from app.core.testing import ModuleTestHelper, ShelfRow
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_quants_from_records import stock_quants_from_records
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.stock_takes.models import StockTake, StockTakeItem, StockTakeStatus
from tests.integration._shelf import (
    put_on_shelf,
    reserve_for_an_order,
    run_in_async_session,
)


@pytest.fixture
def cnt_org(db_session: Session) -> Organization:
    return ModuleTestHelper(db_session).create_org(
        'Counting Org', ['core', 'items', 'locations', 'categories', 'stock_takes']
    )


@pytest.fixture
def cnt_manager(db_session: Session, cnt_org: Organization) -> User:
    return ModuleTestHelper(db_session).create_user(
        cnt_org, email='cnt-manager@example.com', role='manager'
    )


@pytest.fixture
def cnt_counter(db_session: Session, cnt_org: Organization) -> User:
    return ModuleTestHelper(db_session).create_user(
        cnt_org, email='cnt-counter@example.com', role='user'
    )


@pytest.fixture
def cnt_manager_headers(db_session: Session, cnt_manager: User) -> dict[str, str]:
    return ModuleTestHelper(db_session).get_auth_headers(cnt_manager)


@pytest.fixture
def cnt_counter_headers(db_session: Session, cnt_counter: User) -> dict[str, str]:
    return ModuleTestHelper(db_session).get_auth_headers(cnt_counter)


@pytest.fixture
def cnt_location(
    db_session: Session, cnt_org: Organization, cnt_manager: User
) -> StorageLocation:
    h = ModuleTestHelper(db_session)
    storage_type = h.create_storage_type(
        'Warehouse', 'WAREHOUSE', organization_id=cnt_org.id
    )
    return h.create_storage_location(
        cnt_org, storage_type, cnt_manager, name='Counted shelf'
    )


@pytest.fixture
def cnt_item(
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    cnt_org: Organization,
    cnt_manager: User,
    cnt_location: StorageLocation,
) -> Item:
    """Ten on the shelf, six of them promised to a document."""
    template: ProductTemplate = ModuleTestHelper(db_session).create_template(
        cnt_org, name='Promised Goods'
    )
    db_session.commit()

    async def _stock(session: AsyncSession) -> UUID:
        record = await put_on_shelf(session, cnt_manager, template, cnt_location.id, 10)
        await reserve_for_an_order(session, template, cnt_location.id, 6)
        return record.id

    item_id = run_in_async_session(async_engine_fixture, _stock)
    db_session.expire_all()
    item = db_session.get(Item, item_id)
    assert item is not None
    return item


def _counted(
    db_session: Session,
    org: Organization,
    user: User,
    location: StorageLocation,
    item: Item,
    *,
    system: Decimal,
    counted: Decimal,
) -> StockTake:
    stock_take = StockTake(
        user_id=user.id,
        organization_id=org.id,
        storage_location_id=location.id,
        name='Shelf count',
        status=StockTakeStatus.IN_PROGRESS,
    )
    db_session.add(stock_take)
    db_session.flush()
    db_session.add(
        StockTakeItem(
            stock_take_id=stock_take.id,
            item_id=item.id,
            item_name=item.name,
            system_quantity=system,
            counted_quantity=counted,
            is_discrepancy=1 if counted != system else 0,
        )
    )
    db_session.commit()
    db_session.refresh(stock_take)
    return stock_take


def _on_hand_records(db_session: Session, template_id: UUID | None) -> Decimal:
    """What the records say stands for one product — the side the count is on."""
    rows = db_session.execute(
        select(stock_quants_from_records.c.quantity).where(
            stock_quants_from_records.c.product_template_id == template_id
        )
    ).all()
    return sum((Decimal(str(row[0])) for row in rows), Decimal('0'))


@pytest.mark.integration
class TestAShortageOnPromisedStockCanBePosted:
    def test_the_count_posts_and_the_hold_gives_way(
        self,
        client: TestClient,
        cnt_manager_headers: dict[str, str],
        db_session: Session,
        cnt_org: Organization,
        cnt_manager: User,
        cnt_location: StorageLocation,
        cnt_item: Item,
    ) -> None:
        """Ten held for six, three actually there."""
        take = _counted(
            db_session,
            cnt_org,
            cnt_manager,
            cnt_location,
            cnt_item,
            system=Decimal('10'),
            counted=Decimal('3'),
        )
        resp = client.post(
            f'/api/v1/stock-takes/{take.id}/complete',
            headers=cnt_manager_headers,
            json={'apply_adjustments': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.expire_all()
        db_session.refresh(cnt_item)
        assert cnt_item.quantity == Decimal('3')
        # What the records say the shelf holds: the counted figure, and the
        # side every reader of stock asks from now on.
        on_hand = _on_hand_records(db_session, cnt_item.template_id)
        assert on_hand == Decimal('3')
        shelf = db_session.scalars(
            select(ShelfRow).where(ShelfRow.product_template_id == cnt_item.template_id)
        ).one()
        # What is held — the group's reservation rows — can never exceed
        # what is there.
        assert shelf.reserved_quantity <= on_hand

    def test_a_shortage_that_the_shelf_still_covers_leaves_the_hold_alone(
        self,
        client: TestClient,
        cnt_manager_headers: dict[str, str],
        db_session: Session,
        cnt_org: Organization,
        cnt_manager: User,
        cnt_location: StorageLocation,
        cnt_item: Item,
    ) -> None:
        """The control: eight still covers six, so nobody's claim is touched."""
        take = _counted(
            db_session,
            cnt_org,
            cnt_manager,
            cnt_location,
            cnt_item,
            system=Decimal('10'),
            counted=Decimal('8'),
        )
        resp = client.post(
            f'/api/v1/stock-takes/{take.id}/complete',
            headers=cnt_manager_headers,
            json={'apply_adjustments': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.expire_all()
        # The counted figure lands on the records — the side the count reads.
        on_hand = _on_hand_records(db_session, cnt_item.template_id)
        assert on_hand == Decimal('8')
        shelf = db_session.scalars(
            select(ShelfRow).where(ShelfRow.product_template_id == cnt_item.template_id)
        ).one()
        # Nobody's claim was touched: six still held.
        assert shelf.reserved_quantity == Decimal('6.000')


@pytest.mark.integration
class TestAcceptingTheCapIsADecisionLikeAnyOther:
    def test_a_counter_cannot_wave_a_count_past_the_cap(
        self,
        client: TestClient,
        cnt_counter_headers: dict[str, str],
        db_session: Session,
        cnt_org: Organization,
        cnt_counter: User,
        cnt_location: StorageLocation,
        cnt_item: Item,
    ) -> None:
        take = _counted(
            db_session,
            cnt_org,
            cnt_counter,
            cnt_location,
            cnt_item,
            system=Decimal('10'),
            counted=Decimal('2000'),
        )
        resp = client.post(
            f'/api/v1/stock-takes/{take.id}/complete',
            headers=cnt_counter_headers,
            json={'apply_adjustments': True, 'force_over_cap': True},
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text

        db_session.expire_all()
        db_session.refresh(cnt_item)
        assert cnt_item.quantity == Decimal('10')

    def test_a_manager_still_can(
        self,
        client: TestClient,
        cnt_manager_headers: dict[str, str],
        db_session: Session,
        cnt_org: Organization,
        cnt_manager: User,
        cnt_location: StorageLocation,
        cnt_item: Item,
    ) -> None:
        """The control: the permission is the point, not a new refusal."""
        take = _counted(
            db_session,
            cnt_org,
            cnt_manager,
            cnt_location,
            cnt_item,
            system=Decimal('10'),
            counted=Decimal('2000'),
        )
        resp = client.post(
            f'/api/v1/stock-takes/{take.id}/complete',
            headers=cnt_manager_headers,
            json={'apply_adjustments': True, 'force_over_cap': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        db_session.expire_all()
        db_session.refresh(cnt_item)
        assert cnt_item.quantity == Decimal('2000')
