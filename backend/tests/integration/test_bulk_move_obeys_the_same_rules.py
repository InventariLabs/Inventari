"""Moving fifty records at once is the same operation as moving one.

The single move refuses when the source shelf still holds reservations —
draining the quant used to release ``reserved_quantity`` while the
``StockReservation`` rows went on pointing at it, so a later per-document
release would take the same goods off the shelf twice; the rows stand for
themselves now, and the guard stays so that none of them is left without the
goods it holds. It also carries lots across, so a delivery's batch travels
with the goods.

The bulk edit did neither. Selecting the records and setting their location
ran a flat decrement-then-increment: no guard, and every lot merged into one
nameless heap on arrival. Same intent, two different operations, and the
quiet one was the one people reach for when there is a lot to move.
"""

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session

from app.core.testing import ShelfRow, seed_org_storage_types
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash
from tests.integration._shelf import (
    put_on_shelf,
    reserve_for_an_order,
    run_in_async_session,
)


@pytest.fixture
def bm_org(db_session: Session) -> Organization:
    org = Organization(
        name='Bulk Move Test Org',
        enabled_modules=['core', 'items', 'locations', 'categories'],
    )
    db_session.add(org)
    db_session.flush()
    seed_org_storage_types(db_session, org.id)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def bm_user(db_session: Session, bm_org: Organization) -> User:
    user = User(
        email='bulk-move@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Bulk Move User',
        organization_id=bm_org.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def bm_headers(bm_user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(bm_user.id)})}'
    }


@pytest.fixture
def bm_type(db_session: Session) -> StorageType:
    st = StorageType(name='Bulk Warehouse', type_code='WAREHOUSE', behavior_mode='NONE')
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)
    return st


def _location(
    db_session: Session, org: Organization, st: StorageType, user: User, name: str
) -> StorageLocation:
    loc = StorageLocation(
        name=name,
        organization_id=org.id,
        storage_type_id=st.id,
        created_by=user.id,
    )
    db_session.add(loc)
    db_session.commit()
    db_session.refresh(loc)
    return loc


@pytest.fixture
def bm_source(
    db_session: Session, bm_org: Organization, bm_type: StorageType, bm_user: User
) -> StorageLocation:
    return _location(db_session, bm_org, bm_type, bm_user, 'Source Shelf')


@pytest.fixture
def bm_target(
    db_session: Session, bm_org: Organization, bm_type: StorageType, bm_user: User
) -> StorageLocation:
    return _location(db_session, bm_org, bm_type, bm_user, 'Target Shelf')


@pytest.fixture
def bm_template(db_session: Session, bm_org: Organization) -> ProductTemplate:
    t = ProductTemplate(
        name='Bulk Move Product',
        organization_id=bm_org.id,
        barcode='BULKMOVE001',
    )
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t


def _seed(
    db_session: Session,
    engine: AsyncEngine,
    user: User,
    template: ProductTemplate,
    location: StorageLocation,
    quantity: Decimal,
    *,
    on_shelf: Decimal | None = None,
    reserved: Decimal = Decimal('0'),
    lot: StockLot | None = None,
) -> Item:
    """One record on a shelf, put there through the items service.

    ``on_shelf`` is what the shelf holds when more than this one record stands
    there — the ordinary case for a product that arrived twice — and the rest
    arrives as a record of its own. ``reserved`` is held for an order.
    """
    db_session.commit()

    async def _put(session: AsyncSession) -> UUID:
        lot_id = lot.id if lot else None
        record = await put_on_shelf(
            session, user, template, location.id, quantity, lot_id=lot_id
        )
        if on_shelf is not None and on_shelf > quantity:
            await put_on_shelf(
                session, user, template, location.id, on_shelf - quantity, lot_id=lot_id
            )
        if reserved:
            await reserve_for_an_order(session, template, location.id, reserved)
        return record.id

    item_id = run_in_async_session(engine, _put)
    db_session.expire_all()
    item = db_session.get(Item, item_id)
    assert item is not None
    return item


def _groups(db: Session, org, template, location) -> list[ShelfRow]:
    """The groups the records hold on *location*; a shelf left empty has none."""
    return list(
        db.scalars(
            select(ShelfRow).where(
                ShelfRow.organization_id == org.id,
                ShelfRow.product_template_id == template.id,
                ShelfRow.storage_location_id == location.id,
            )
        ).all()
    )


# Ten on the shelf, four of them spoken for by a confirmed document, and the
# record being moved holds six. A draw by strategy alone would not catch
# this: six is exactly what is free, so it would go through, and the source
# would be left holding four reserved units no record stands behind any more.
# That is the state the guard exists to prevent, and the one the bulk path
# reached without a word.
ON_SHELF = Decimal('10')
RESERVED = Decimal('4')
MOVED = Decimal('6')


@pytest.mark.integration
class TestReservedStockRefusesBothWays:
    def test_the_single_move_refuses_a_reserved_shelf(
        self,
        client,
        db_session,
        async_engine_fixture,
        bm_user,
        bm_headers,
        bm_org,
        bm_template,
        bm_source,
        bm_target,
    ):
        # The behaviour the bulk path is measured against.
        item = _seed(
            db_session,
            async_engine_fixture,
            bm_user,
            bm_template,
            bm_source,
            MOVED,
            on_shelf=ON_SHELF,
            reserved=RESERVED,
        )

        resp = client.patch(
            f'/api/v1/items/{item.id}/move',
            headers=bm_headers,
            json={'to_location_id': str(bm_target.id)},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text

    def test_the_bulk_edit_refuses_it_too(
        self,
        client,
        db_session,
        async_engine_fixture,
        bm_user,
        bm_headers,
        bm_org,
        bm_template,
        bm_source,
        bm_target,
    ):
        item = _seed(
            db_session,
            async_engine_fixture,
            bm_user,
            bm_template,
            bm_source,
            MOVED,
            on_shelf=ON_SHELF,
            reserved=RESERVED,
        )

        resp = client.patch(
            '/api/v1/items/bulk',
            headers=bm_headers,
            json={
                'item_ids': [str(item.id)],
                'update_data': {'location_id': str(bm_target.id)},
            },
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text

        # And nothing moved: the goods are still where the reservation rows
        # say they are.
        db_session.expire_all()
        source = _groups(db_session, bm_org, bm_template, bm_source)
        assert len(source) == 1
        assert source[0].quantity == ON_SHELF
        assert source[0].reserved_quantity == RESERVED
        assert _groups(db_session, bm_org, bm_template, bm_target) == []


@pytest.mark.integration
class TestLotsTravelWithTheGoods:
    def test_the_bulk_edit_keeps_the_batch_it_moved(
        self,
        client,
        db_session,
        async_engine_fixture,
        bm_user,
        bm_headers,
        bm_org,
        bm_template,
        bm_source,
        bm_target,
    ):
        # A delivery arrives as a lot. Moved in bulk, it used to land at the
        # destination on a lot-less quant, and the batch stopped existing.
        lot = StockLot(
            organization_id=bm_org.id,
            product_template_id=bm_template.id,
            name='LOT-2026-03',
        )
        db_session.add(lot)
        db_session.commit()
        db_session.refresh(lot)

        item = _seed(
            db_session,
            async_engine_fixture,
            bm_user,
            bm_template,
            bm_source,
            Decimal('6'),
            lot=lot,
        )

        resp = client.patch(
            '/api/v1/items/bulk',
            headers=bm_headers,
            json={
                'item_ids': [str(item.id)],
                'update_data': {'location_id': str(bm_target.id)},
            },
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.expire_all()
        arrived = _groups(db_session, bm_org, bm_template, bm_target)
        assert len(arrived) == 1
        assert arrived[0].quantity == Decimal('6')
        assert arrived[0].lot_id == lot.id

        left = [
            group
            for group in _groups(db_session, bm_org, bm_template, bm_source)
            if group.quantity > 0
        ]
        assert left == [], 'the source still holds the moved stock'

    def test_an_unlotted_move_still_works(
        self,
        client,
        db_session,
        async_engine_fixture,
        bm_user,
        bm_headers,
        bm_org,
        bm_template,
        bm_source,
        bm_target,
    ):
        item = _seed(
            db_session,
            async_engine_fixture,
            bm_user,
            bm_template,
            bm_source,
            Decimal('3'),
        )

        resp = client.patch(
            '/api/v1/items/bulk',
            headers=bm_headers,
            json={
                'item_ids': [str(item.id)],
                'update_data': {'location_id': str(bm_target.id)},
            },
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.expire_all()
        arrived = _groups(db_session, bm_org, bm_template, bm_target)
        assert len(arrived) == 1
        assert arrived[0].quantity == Decimal('3')
        assert arrived[0].lot_id is None
