"""The database refuses, at commit, a reservation its grain cannot cover.

``CHECK (reserved_quantity <= quantity)`` on the quant row was what stopped
a bug from committing a hold of more than a batch holds. With the records the
only count, both sides are sums — the records of a ``(product, shelf, batch,
owner)`` grain and the reservation rows of it — and the guard is a constraint
trigger checked at commit (created by the baseline migration).

Every test here writes past the application on purpose: a hand-written
reservation row, a record changed in the session. The doors refuse these
shapes themselves; the point is that a door that forgot to would be refused
by the database as well.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.db_isolation import isolated_db_url
from app.core.public_api import core_api
from app.core.testing import ShelfRow
from app.main import integrity_error_handler
from app.models.item import Item
from app.models.stock_reservation import StockReservation
from app.models.storage_location import StorageLocation

from ._core_api_helpers import make_template
from ._holds import hold_async, past_the_hold_guard_async
from ._shelf import put_on_shelf

pytestmark = pytest.mark.integration

GUARD = 'ck_stock_holds_within_stock'


class _Shelf:
    """Five of a product in batch A on one shelf, and what a test needs to change it."""

    def __init__(self, db, org_id, user, location, template, lot_a, lot_b, record):
        self.db = db
        self.org_id = org_id
        self.user = user
        self.location = location
        self.template = template
        self.lot_a = lot_a
        self.lot_b = lot_b
        # A plain id: the record object expires with every rollback here.
        self.record_id = record.id

    async def grain(self, lot_id) -> ShelfRow:
        return (
            await self.db.scalars(
                select(ShelfRow).where(
                    ShelfRow.organization_id == self.org_id,
                    ShelfRow.product_template_id == self.template.id,
                    ShelfRow.storage_location_id == self.location.id,
                    ShelfRow.lot_id == lot_id,
                )
            )
        ).one()

    async def hold(self, quantity: str, lot_id=None) -> None:
        grain = await self.grain(lot_id or self.lot_a)
        await hold_async(self.db, grain, Decimal(quantity))

    async def held(self) -> Decimal:
        return await self.db.scalar(
            select(func.coalesce(func.sum(StockReservation.quantity), 0)).where(
                StockReservation.organization_id == self.org_id
            )
        )


@pytest.fixture
async def shelf(
    real_async_db_session,
    async_test_household,
    async_test_storage_location,
    async_test_user,
) -> _Shelf:
    db = real_async_db_session
    org_id = async_test_household.id
    template = await db.run_sync(lambda s: make_template(s, org_id))
    lots = [
        await core_api.stock.get_or_create_lot_async(
            db=db,
            organization_id=org_id,
            product_template_id=template.id,
            name=name,
        )
        for name in ('A', 'B')
    ]
    record = await put_on_shelf(
        db,
        async_test_user,
        template,
        async_test_storage_location.id,
        Decimal('5'),
        lot_id=lots[0],
    )
    await db.commit()
    return _Shelf(
        db,
        org_id,
        async_test_user,
        async_test_storage_location,
        template,
        lots[0],
        lots[1],
        record,
    )


async def _refused_at_commit(db) -> IntegrityError:
    with pytest.raises(IntegrityError) as refused:
        await db.commit()
    await db.rollback()
    assert GUARD in str(refused.value.orig), refused.value.orig
    return refused.value


class TestAHoldPastItsGrain:
    async def test_is_refused_at_commit_and_answered_in_words(self, shelf) -> None:
        await shelf.hold('3')
        await shelf.db.commit()

        await shelf.hold('3')
        refused = await _refused_at_commit(shelf.db)

        assert await shelf.held() == Decimal('3'), 'the refused hold left nothing'
        response = await integrity_error_handler(None, refused)
        assert response.status_code == 409
        detail = json.loads(bytes(response.body))['detail']
        assert detail['code'] == 'STOCK_STATE_IMPOSSIBLE'
        assert 'Internal Server Error' not in detail['message']

    async def test_is_judged_on_its_own_batch_not_the_shelf(self, shelf) -> None:
        """Five of A and five of B on the shelf: six held of A is still too many."""
        await put_on_shelf(
            shelf.db,
            shelf.user,
            shelf.template,
            shelf.location.id,
            Decimal('5'),
            lot_id=shelf.lot_b,
        )
        await shelf.db.commit()

        await shelf.hold('5')
        await shelf.hold('5', lot_id=shelf.lot_b)
        await shelf.db.commit()

        await shelf.hold('1')
        await _refused_at_commit(shelf.db)


async def _another_shelf(shelf: _Shelf) -> StorageLocation:
    other = StorageLocation(
        organization_id=shelf.org_id,
        created_by=shelf.user.id,
        storage_type_id=shelf.location.storage_type_id,
        name='Cellar',
    )
    shelf.db.add(other)
    await shelf.db.flush()
    # The record's new group needs its anchor, as it does at every door.
    await core_api.stock.lock_async(
        shelf.db, shelf.org_id, keys=[(shelf.template.id, other.id)]
    )
    return other


async def _fewer(shelf: _Shelf, record: Item) -> None:
    record.quantity = Decimal('2')


async def _deleted(shelf: _Shelf, record: Item) -> None:
    record.is_deleted = True


async def _other_batch(shelf: _Shelf, record: Item) -> None:
    record.lot_id = shelf.lot_b


async def _other_shelf(shelf: _Shelf, record: Item) -> None:
    record.storage_location_id = (await _another_shelf(shelf)).id


async def _purged(shelf: _Shelf, record: Item) -> None:
    await shelf.db.delete(record)


class TestARecordChangeThatLeavesItsHoldBehind:
    """Five in the grain, four of them held: every way of taking three away is refused."""

    @pytest.mark.parametrize(
        'change',
        [_fewer, _deleted, _other_batch, _other_shelf, _purged],
        ids=['fewer', 'deleted', 'other-batch', 'other-shelf', 'purged'],
    )
    async def test_is_refused_at_commit(
        self, shelf, change: Callable[[_Shelf, Item], Any]
    ) -> None:
        await shelf.hold('4')
        await shelf.db.commit()
        record = await shelf.db.get(Item, shelf.record_id)

        await change(shelf, record)
        await _refused_at_commit(shelf.db)

        record = await shelf.db.get(Item, shelf.record_id, populate_existing=True)
        assert record is not None
        assert record.quantity == Decimal('5')
        assert record.is_deleted is False

    async def test_a_change_the_grain_still_covers_commits(self, shelf) -> None:
        """The control: down to exactly what is held, then up again."""
        await shelf.hold('4')
        await shelf.db.commit()
        record = await shelf.db.get(Item, shelf.record_id)

        record.quantity = Decimal('4')
        await shelf.db.commit()
        record.quantity = Decimal('9')
        await shelf.db.commit()

        assert await shelf.held() == Decimal('4')


async def test_the_check_waits_for_the_commit(shelf) -> None:
    """Taking the stock before letting go of its hold is judged on where it ends.

    A document completes by releasing its own hold and taking the goods; a
    check that ran at each statement would refuse whichever order put the
    take first.
    """
    await shelf.hold('5')
    await shelf.db.commit()
    record = await shelf.db.get(Item, shelf.record_id)

    record.quantity = Decimal('0')
    await shelf.db.flush()
    for row in await shelf.db.scalars(
        select(StockReservation).where(StockReservation.organization_id == shelf.org_id)
    ):
        await shelf.db.delete(row)
    await shelf.db.commit()

    assert await shelf.held() == Decimal('0')


def test_the_migration_puts_the_guard_up_and_takes_it_down(monkeypatch) -> None:
    """The baseline creates the three triggers and the function; going down drops them."""

    def guard(url: str) -> tuple[set[tuple[str, str, bool, bool]], int]:
        engine = create_engine(url)
        try:
            with engine.connect() as conn:
                triggers = {
                    (row[0], row[1], row[2], row[3])
                    for row in conn.execute(
                        text(
                            'SELECT tgrelid::regclass::text, tgname, tgdeferrable,'
                            ' tginitdeferred FROM pg_trigger'
                            " WHERE tgname LIKE 'ck_stock_holds_within_stock%'"
                        )
                    )
                }
                functions = conn.scalar(
                    text(
                        'SELECT count(*) FROM pg_proc'
                        " WHERE proname = 'stock_holds_within_stock'"
                    )
                )
        finally:
            engine.dispose()
        return triggers, functions

    # Deferral is load-bearing: a confirm that takes stock and releases its own
    # hold must be judged at commit, not row by row.
    installed = {
        ('items', 'ck_stock_holds_within_stock', True, True),
        ('items', 'ck_stock_holds_within_stock_on_delete', True, True),
        ('stock_reservations', 'ck_stock_holds_within_stock', True, True),
    }
    with isolated_db_url('holdguard') as url:
        monkeypatch.setenv('DATABASE_URL', url)
        config = Config('alembic.ini')

        command.upgrade(config, 'baseline_002')
        assert guard(url) == (installed, 1)

        command.downgrade(config, 'base')
        assert guard(url) == (set(), 0)

        command.upgrade(config, 'baseline_002')
        assert guard(url) == (installed, 1)


# A deferred check of the test run's own on the records, as test tooling
# may stand one on a table it watches.
_ANOTHER_CHECK = 'a_check_of_the_test_run'
_STAND_ANOTHER_CHECK = (
    f'CREATE FUNCTION {_ANOTHER_CHECK}() RETURNS trigger'
    ' LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$',
    f'CREATE CONSTRAINT TRIGGER {_ANOTHER_CHECK}'
    ' AFTER INSERT OR UPDATE OR DELETE ON items'
    ' DEFERRABLE INITIALLY DEFERRED FOR EACH ROW'
    f' EXECUTE FUNCTION {_ANOTHER_CHECK}()',
)


async def _another_check(db) -> str | None:
    return await db.scalar(
        text('SELECT tgenabled::text FROM pg_trigger WHERE tgname = :name'),
        {'name': _ANOTHER_CHECK},
    )


class TestAHoldWrittenPastTheGuard:
    """What the tests use to write a grain an instance older than the guard holds."""

    async def test_leaves_the_guard_up_behind_it(self, shelf) -> None:
        async with past_the_hold_guard_async(shelf.db):
            await shelf.hold('7')
        await shelf.db.commit()

        await shelf.hold('1')
        await _refused_at_commit(shelf.db)

    async def test_another_deferred_check_on_the_records_does_not_stop_it(
        self, shelf
    ) -> None:
        """A write inside queued no event that would keep the guard from coming back."""
        db = shelf.db
        try:
            for statement in _STAND_ANOTHER_CHECK:
                await db.execute(text(statement))
            record = await db.get(Item, shelf.record_id)

            async with past_the_hold_guard_async(db):
                record.quantity = Decimal('2')

            assert await _another_check(db) == 'O', 'the other check is on again'
        finally:
            # The trigger is DDL of this transaction: rolled back, it does not
            # outlive the test on the worker's database.
            await db.rollback()
        assert await _another_check(db) is None
