"""A change to a record comes off the record's own grain, under the group's anchor.

The bridge used to take a decrease off the quant of the record's batch and
owner, and when that quant could not cover it — because the rest was promised
to an order — it fell back to the removal strategy, which found the change in
another batch. The record lost its stock, the quant of a batch nobody touched
lost it too, and the order's hold stood on stock no longer there.

A record's grain is its shelf, batch and owner. What the grain has free is
what its records hold less what its reservation rows hold, read under the
group's anchor, and a change that asks for more is refused by name. The
anchor is taken before the record's number is read, so two hands on two
records of one grain do not both see the same free part.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.contracts import UserContextDTO
from app.core.exceptions import StockUnavailableError
from app.core.testing import ModuleTestHelper, ShelfRow, seed_org_storage_types
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.schemas.item import ItemConsumeRequest, ItemQuantityUpdate
from app.services.items import _stock_quant
from app.services.items._update import update_quantity
from app.services.items.move_service import consume_item
from tests.integration._holds import hold_async
from tests.integration._shelf import put_on_shelf

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: Which of the two hands the running task is.
_WHO: contextvars.ContextVar[str] = contextvars.ContextVar('who')


class _Shelf:
    """One product on one shelf, two batches of it, and a person to act."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def build(self) -> _Shelf:
        db = self.db
        self.org = Organization(
            name=f'Grain {uuid.uuid4().hex[:6]}',
            enabled_modules=['core', 'items', 'locations'],
        )
        db.add(self.org)
        await db.flush()
        # A record taken to nothing moves to the consumed-goods location,
        # which is created from the organization's storage types.
        org_id = self.org.id
        await db.run_sync(lambda session: seed_org_storage_types(session, org_id))
        user = await ModuleTestHelper.create_user_async(
            db, self.org, email=f'grain_{uuid.uuid4().hex[:8]}@test.com', role='admin'
        )
        self.user = UserContextDTO(id=user.id, organization_id=self.org.id)
        self.shelf = StorageLocation(
            organization_id=self.org.id, created_by=user.id, name='Aisle 1'
        )
        self.product = ProductTemplate(
            organization_id=self.org.id, name='Rice', sku=f'RI-{uuid.uuid4().hex[:8]}'
        )
        db.add_all([self.shelf, self.product])
        await db.flush()
        self.early, self.late = (
            StockLot(
                organization_id=self.org.id,
                product_template_id=self.product.id,
                name=name,
            )
            for name in ('B-01', 'B-02')
        )
        db.add_all([self.early, self.late])
        await db.flush()
        return self

    async def record(
        self, quantity: str, lot: StockLot, owner: Partner | None = None
    ) -> Item:
        return await put_on_shelf(
            self.db,
            self.user,
            self.product,
            self.shelf.id,
            quantity,
            lot_id=lot.id,
            owner_id=owner.id if owner else None,
        )

    async def hold(
        self, quantity: str, lot: StockLot, owner: Partner | None = None
    ) -> None:
        grain = await self.db.scalar(
            select(ShelfRow).where(
                ShelfRow.product_template_id == self.product.id,
                ShelfRow.storage_location_id == self.shelf.id,
                ShelfRow.lot_id == lot.id,
                ShelfRow.owner_id.is_(None)
                if owner is None
                else ShelfRow.owner_id == owner.id,
            )
        )
        assert grain is not None
        await hold_async(self.db, grain, Decimal(quantity))
        await self.db.flush()

    async def on_shelf(self, lot: StockLot) -> Decimal:
        """What the batch holds on the shelf, every owner together."""
        total = await self.db.scalar(
            select(func.coalesce(func.sum(ShelfRow.quantity), 0)).where(
                ShelfRow.product_template_id == self.product.id,
                ShelfRow.storage_location_id == self.shelf.id,
                ShelfRow.lot_id == lot.id,
            )
        )
        return Decimal(total or 0)


async def test_a_take_that_eats_the_grains_hold_is_refused(
    real_async_db_session: AsyncSession,
) -> None:
    shelf = await _Shelf(real_async_db_session).build()
    record = await shelf.record('5', shelf.early)
    await shelf.record('5', shelf.late)
    await shelf.hold('3', shelf.early)

    # Two are free in the early batch; four are asked for.
    with pytest.raises(StockUnavailableError) as refused:
        await update_quantity(
            real_async_db_session,
            record,
            ItemQuantityUpdate(quantity=Decimal('1')),
            user_id=shelf.user.id,
        )

    assert refused.value.code == StockUnavailableError.NOT_ENOUGH
    # Nothing reached for the other batch.
    assert await shelf.on_shelf(shelf.late) == Decimal('5')


async def test_a_take_within_the_grains_free_part_comes_off_that_grain(
    real_async_db_session: AsyncSession,
) -> None:
    shelf = await _Shelf(real_async_db_session).build()
    record = await shelf.record('5', shelf.early)
    await shelf.record('5', shelf.late)
    await shelf.hold('3', shelf.early)

    await consume_item(
        real_async_db_session,
        record,
        ItemConsumeRequest(quantity=Decimal('2')),
        shelf.user,
    )

    assert record.quantity == Decimal('3')
    assert await shelf.on_shelf(shelf.early) == Decimal('3')
    assert await shelf.on_shelf(shelf.late) == Decimal('5')


async def test_another_owners_hold_is_another_grain(
    real_async_db_session: AsyncSession,
) -> None:
    """The organization's own goods and a consignor's are two grains of one batch."""
    shelf = await _Shelf(real_async_db_session).build()
    consignor = Partner(organization_id=shelf.org.id, name='Consignor', type='SUPPLIER')
    real_async_db_session.add(consignor)
    await real_async_db_session.flush()
    own = await shelf.record('5', shelf.early)
    await shelf.record('5', shelf.early, owner=consignor)
    await shelf.hold('5', shelf.early, owner=consignor)

    # The consignor's five are all promised; none of the organization's are.
    await consume_item(
        real_async_db_session,
        own,
        ItemConsumeRequest(quantity=Decimal('5')),
        shelf.user,
    )
    assert own.quantity == Decimal('0')

    consigned = await real_async_db_session.scalar(
        select(Item).where(Item.owner_id == consignor.id)
    )
    assert consigned is not None
    with pytest.raises(StockUnavailableError):
        await consume_item(
            real_async_db_session,
            consigned,
            ItemConsumeRequest(quantity=Decimal('1')),
            shelf.user,
        )


def _async_test_url() -> str:
    return settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


async def _two_hands(
    monkeypatch: pytest.MonkeyPatch,
    org_id: uuid.UUID,
    user: UserContextDTO,
    takes: list[tuple[uuid.UUID, Decimal]],
) -> list[Any]:
    """Consume each (record, quantity) on its own connection, both past the check at once.

    Each hand is held at the lock until the other has got there too, or for
    two seconds — the interleaving in which both would read the same number.
    """
    arrived = {'first': asyncio.Event(), 'second': asyncio.Event()}
    lock = _stock_quant.lock_record_stock_async

    async def wait_for_the_other_then_lock(*args: Any, **kwargs: Any) -> Any:
        me = _WHO.get(None)
        if me is not None and not arrived[me].is_set():
            arrived[me].set()
            other = 'second' if me == 'first' else 'first'
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(arrived[other].wait(), timeout=2)
        return await lock(*args, **kwargs)

    monkeypatch.setattr(
        _stock_quant, 'lock_record_stock_async', wait_for_the_other_then_lock
    )

    engine = create_async_engine(_async_test_url(), echo=False, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def take(name: str, record_id: uuid.UUID, quantity: Decimal) -> None:
        _WHO.set(name)
        async with factory() as session:
            record = await session.get(Item, record_id)
            assert record is not None
            await consume_item(
                session, record, ItemConsumeRequest(quantity=quantity), user
            )
            await session.commit()

    try:
        return await asyncio.gather(
            *(
                take(name, record_id, quantity)
                for name, (record_id, quantity) in zip(
                    ('first', 'second'), takes, strict=True
                )
            ),
            return_exceptions=True,
        )
    finally:
        await engine.dispose()


async def test_two_hands_on_one_grain_do_not_both_take_its_free_part(
    real_async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = real_async_db_session
    shelf = await _Shelf(db).build()
    one = await shelf.record('5', shelf.early)
    two = await shelf.record('5', shelf.early)
    await shelf.hold('6', shelf.early)
    records = [one.id, two.id]
    await db.commit()

    # Four are free in the grain; each hand asks for three.
    outcomes = await _two_hands(
        monkeypatch,
        shelf.org.id,
        shelf.user,
        [(record_id, Decimal('3')) for record_id in records],
    )

    db.expire_all()
    left = await db.scalar(select(func.sum(Item.quantity)).where(Item.id.in_(records)))
    assert Decimal(left) == Decimal('7'), outcomes
    assert sum(outcome is None for outcome in outcomes) == 1, outcomes
    assert any(isinstance(o, StockUnavailableError) for o in outcomes), outcomes


async def test_two_hands_on_a_record_without_a_card_read_it_under_its_lock(
    real_async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A record with no card has no anchor; its own row is the lock."""
    db = real_async_db_session
    shelf = await _Shelf(db).build()
    record = Item(
        organization_id=shelf.org.id,
        storage_location_id=shelf.shelf.id,
        name='Loose oats',
        quantity=Decimal('5'),
    )
    db.add(record)
    await db.flush()
    record_id = record.id
    await db.commit()

    outcomes = await _two_hands(
        monkeypatch,
        shelf.org.id,
        shelf.user,
        [(record_id, Decimal('3')), (record_id, Decimal('3'))],
    )

    db.expire_all()
    left = await db.scalar(select(Item.quantity).where(Item.id == record_id))
    assert left == Decimal('2'), outcomes
    assert sum(outcome is None for outcome in outcomes) == 1, outcomes
    assert all(o is None or isinstance(o, ValueError) for o in outcomes), outcomes
