"""A ledger row has to read as a sentence, not as five identifiers.

``StockMoveDTO`` carries the ids the ledger is keyed by. A screen that showed
them would be useless, and a screen that resolved them one row at a time
would cost a query per name — five per row, on a page of two hundred.

So the ledger reads the names alongside the row, in the query that fetched
it: what moved, in whose unit, from where, to where, which batch, and who
recorded it. What a movement does not have stays empty: a delivery from
outside has no origin, a product with no batch has no batch name, and a row
written by a background path has nobody's name on it.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.uom import Uom, UomCategory
from app.models.user import User
from app.services.stock_moves_service import list_rows_for_org_async
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration


class _QueryCounter:
    def __init__(self) -> None:
        self.count = 0

    def reset(self) -> None:
        self.count = 0


@pytest.fixture
def query_counter() -> _QueryCounter:
    return _QueryCounter()


@pytest.fixture
def track_queries(
    real_async_db_session: AsyncSession, query_counter: _QueryCounter
) -> Iterator[None]:
    bind = real_async_db_session.get_bind()

    def before_cursor_execute(*_args: Any, **_kwargs: Any) -> None:
        query_counter.count += 1

    event.listen(bind, 'before_cursor_execute', before_cursor_execute)
    try:
        yield
    finally:
        event.remove(bind, 'before_cursor_execute', before_cursor_execute)


class _Scene:
    org: Organization
    user: User
    kilogram: Uom
    flour: ProductTemplate
    aisle_one: StorageLocation
    aisle_two: StorageLocation
    lot: StockLot


@pytest.fixture
async def scene(real_async_db_session: AsyncSession) -> _Scene:
    db = real_async_db_session
    s = _Scene()

    s.org = Organization(
        name=f'Sentence Org {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations'],
    )
    db.add(s.org)
    await db.commit()
    await db.refresh(s.org)

    s.user = await ModuleTestHelper.create_user_async(
        db, s.org, email=f'keeper_{uuid4().hex[:8]}@test.com'
    )
    s.user.full_name = 'Hanna Kowal'
    await db.commit()

    category = UomCategory(name=f'Weight {uuid4().hex[:6]}', organization_id=s.org.id)
    db.add(category)
    await db.flush()
    s.kilogram = Uom(
        name='Kilogram',
        symbol='kg',
        category_id=category.id,
        organization_id=s.org.id,
        factor=1.0,
        is_reference=True,
    )
    db.add(s.kilogram)
    await db.flush()

    s.flour = ProductTemplate(
        name='Rye flour', organization_id=s.org.id, uom_id=s.kilogram.id
    )
    db.add(s.flour)
    await db.flush()

    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    s.aisle_one = StorageLocation(
        name='Aisle 1',
        organization_id=s.org.id,
        storage_type_id=storage_type.id,
        created_by=s.user.id,
    )
    s.aisle_two = StorageLocation(
        name='Aisle 2',
        organization_id=s.org.id,
        storage_type_id=storage_type.id,
        created_by=s.user.id,
    )
    db.add_all([s.aisle_one, s.aisle_two])
    await db.flush()

    s.lot = StockLot(
        organization_id=s.org.id, product_template_id=s.flour.id, name='L-7'
    )
    db.add(s.lot)
    await db.commit()
    return s


async def _transfer(db: AsyncSession, s: _Scene) -> StockMove:
    move = StockMove(
        organization_id=s.org.id,
        product_template_id=s.flour.id,
        from_location_id=s.aisle_one.id,
        to_location_id=s.aisle_two.id,
        quantity=Decimal('4.000'),
        lot_id=s.lot.id,
        created_by=s.user.id,
        reference_type='transfer',
    )
    db.add(move)
    await db.commit()
    return move


@pytest.mark.asyncio
class TestAMovementReadsAsASentence:
    async def test_a_row_names_what_moved_and_where(
        self, real_async_db_session: AsyncSession, scene: _Scene
    ) -> None:
        await _transfer(real_async_db_session, scene)

        rows, total = await list_rows_for_org_async(real_async_db_session, scene.org.id)

        assert total == 1
        row = rows[0]
        assert row.product_name == 'Rye flour'
        assert row.uom_symbol == 'kg'
        assert row.from_location_name == 'Aisle 1'
        assert row.to_location_name == 'Aisle 2'
        assert row.lot_name == 'L-7'
        assert row.user_name == 'Hanna Kowal'
        # The ids the ledger is keyed by are still there.
        assert row.product_template_id == scene.flour.id
        assert row.quantity == Decimal('4.000')

    async def test_what_a_movement_does_not_have_stays_empty(
        self, real_async_db_session: AsyncSession, scene: _Scene
    ) -> None:
        """A delivery from outside has no origin, no batch and no author."""
        db = real_async_db_session
        db.add(
            StockMove(
                organization_id=scene.org.id,
                product_template_id=scene.flour.id,
                to_location_id=scene.aisle_one.id,
                quantity=Decimal('10.000'),
                reference_type='document',
            )
        )
        await db.commit()

        rows, _ = await list_rows_for_org_async(db, scene.org.id)

        row = rows[0]
        assert row.from_location_name is None
        assert row.lot_name is None
        assert row.user_name is None
        assert row.to_location_name == 'Aisle 1'

    async def test_a_person_without_a_name_is_read_by_their_address(
        self, real_async_db_session: AsyncSession, scene: _Scene
    ) -> None:
        """An account that never filled in a name still has to be nameable."""
        db = real_async_db_session
        nameless = await ModuleTestHelper.create_user_async(
            db, scene.org, email=f'nameless_{uuid4().hex[:8]}@test.com'
        )
        nameless.full_name = None
        await db.commit()
        db.add(
            StockMove(
                organization_id=scene.org.id,
                product_template_id=scene.flour.id,
                to_location_id=scene.aisle_one.id,
                quantity=Decimal('1.000'),
                created_by=nameless.id,
                reference_type='item',
            )
        )
        await db.commit()

        rows, _ = await list_rows_for_org_async(db, scene.org.id)

        assert rows[0].user_name == nameless.email

    async def test_a_longer_page_does_not_cost_more_queries(
        self,
        real_async_db_session: AsyncSession,
        scene: _Scene,
        query_counter: _QueryCounter,
        track_queries: None,
    ) -> None:
        """The names come with the rows, not one lookup at a time."""
        db = real_async_db_session
        for _ in range(3):
            await _transfer(db, scene)

        query_counter.reset()
        await list_rows_for_org_async(db, scene.org.id)
        for_three = query_counter.count

        for _ in range(9):
            await _transfer(db, scene)

        query_counter.reset()
        rows, total = await list_rows_for_org_async(db, scene.org.id)
        for_twelve = query_counter.count

        assert total == 12
        assert len(rows) == 12
        assert for_twelve == for_three


@pytest.mark.asyncio
class TestTheLedgerKnowsWhoDidIt:
    """The one question a movement history exists to answer.

    The item paths wrote every StockMove with ``created_by`` empty, so a
    ledger built from them read as nobody's work — the Who column came back
    a dash on every row of a real warehouse. Only the document receipt path
    ever named an author.
    """

    async def test_a_quantity_change_carries_the_person_who_made_it(
        self, real_async_db_session: AsyncSession, scene: _Scene
    ) -> None:
        from app.models.item import Item
        from app.schemas.item import ItemQuantityUpdate
        from app.services.items._update import update_quantity

        db = real_async_db_session
        # The bridge only records movements for organizations whose
        # modules consume StockQuant (ADR-004).
        scene.org.enabled_modules = ['core', 'items', 'locations', 'warehouse']
        await db.commit()
        item = Item(
            name='Rye flour',
            organization_id=scene.org.id,
            storage_location_id=scene.aisle_one.id,
            template_id=scene.flour.id,
            quantity=Decimal('5.000'),
            uom_id=scene.kilogram.id,
        )
        db.add(item)
        await db.run_sync(anchor_pending_records)
        await db.commit()

        await update_quantity(
            db,
            item,
            ItemQuantityUpdate(quantity=Decimal('9.000')),
            user_id=scene.user.id,
        )
        await db.commit()

        rows, _ = await list_rows_for_org_async(db, scene.org.id)

        assert rows, 'the change recorded no movement at all'
        assert rows[0].created_by == scene.user.id
        assert rows[0].user_name == 'Hanna Kowal'
