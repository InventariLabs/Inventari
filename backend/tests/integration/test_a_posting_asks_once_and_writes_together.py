"""A posting reads its reference data once and writes the rows it appends together.

Posting a 200-line receipt sent twelve thousand statements: the same
organization, unit and shelf were read again for every line, and each line
wrote its movement, cost layer, history row and journal row with a round trip
of its own. The three tools the posting now runs inside are pinned here —
``reference_reads`` (a read of reference data answered once), ``posting_batch``
(appended rows written as sets, and written before anything reads them) and the
transaction's memory of the locks it holds — each against the failure it
exists to prevent.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, RecordPostDTO
from app.core.exceptions import StockUnavailableError
from app.core.posting_batch import posting_batch
from app.core.read_scope import reference_reads
from app.core.testing import ModuleTestHelper, seed_org_storage_types
from app.core.txn_memo import transaction_memo
from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.services._stock_quant_ops import (
    ask_what_each_grain_has_free_once,
    lock_stock_async,
    post_movement_async,
)
from app.services.audit_service import log_action_async
from app.services.valuation_service import ValuationService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@contextmanager
def _statements(db: AsyncSession) -> Iterator[list[str]]:
    """Every statement *db* sends while the block runs, whitespace folded."""
    seen: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        text = re.sub(r'^/\*.*?\*/', '', ' '.join(statement.split()), flags=re.S)
        seen.append(text.strip().lower())

    bind = db.sync_session.get_bind()
    event.listen(bind, 'before_cursor_execute', record)
    try:
        yield seen
    finally:
        event.remove(bind, 'before_cursor_execute', record)


def _on(seen: list[str], table: str, verb: str = 'select') -> list[str]:
    return [s for s in seen if s.startswith(verb) and f' {table} ' in f'{s} ']


async def _warehouse(db: AsyncSession) -> tuple[Organization, Any, StorageLocation]:
    org = Organization(
        name=f'Posting {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations'],
    )
    db.add(org)
    await db.flush()
    org_id = org.id
    await db.run_sync(lambda session: seed_org_storage_types(session, org_id))
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'posting_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    shelf = StorageLocation(organization_id=org.id, created_by=user.id, name='Aisle')
    db.add(shelf)
    await db.flush()
    return org, user, shelf


async def _entry(db: AsyncSession, org: Organization, user: Any, n: int) -> None:
    await log_action_async(
        db,
        organization_id=org.id,
        user_id=user.id,
        action=AuditAction.UPDATE,
        target_type='document',
        target_id=uuid.uuid4(),
        snapshot={'n': n},
    )


class TestReferenceReads:
    async def test_a_repeated_read_is_answered_once(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, _user, _shelf = await _warehouse(db)

        async def read() -> Any:
            return await db.scalar(
                select(Organization.currency).where(Organization.id == org.id)
            )

        with reference_reads(db), _statements(db) as inside:
            first, second = await read(), await read()
        with _statements(db) as outside:
            await read()
            await read()

        assert first == second
        assert len(_on(inside, 'organizations')) == 1
        assert len(_on(outside, 'organizations')) == 2

    async def test_the_answer_does_not_outlive_the_block(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, _user, _shelf = await _warehouse(db)
        statement = select(Organization.currency).where(Organization.id == org.id)
        with reference_reads(db):
            await db.scalar(statement)

        with _statements(db) as after:
            await db.scalar(statement)

        assert len(_on(after, 'organizations')) == 1

    async def test_a_write_to_the_table_drops_what_was_kept(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, _user, shelf = await _warehouse(db)
        statement = select(StorageLocation.name).where(StorageLocation.id == shelf.id)

        with reference_reads(db):
            assert await db.scalar(statement) == 'Aisle'
            shelf.name = 'Dock'
            await db.flush()
            renamed = await db.scalar(statement)

        assert renamed == 'Dock'

    async def test_an_unflushed_edit_is_seen_by_the_next_read(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, _user, _shelf = await _warehouse(db)
        statement = select(Organization.currency).where(Organization.id == org.id)

        with reference_reads(db):
            before = await db.scalar(statement)
            org.currency = 'EUR' if before != 'EUR' else 'PLN'
            edited = org.currency
            # No flush by hand: the read must flush the edit first, as it
            # does outside the block.
            assert await db.scalar(statement) == edited

    async def test_a_locking_read_always_reaches_the_database(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        _org, _user, shelf = await _warehouse(db)
        locking = (
            select(StorageLocation.id)
            .where(StorageLocation.id == shelf.id)
            .with_for_update()
        )

        with reference_reads(db), _statements(db) as seen:
            await db.scalar(locking)
            await db.scalar(locking)

        assert len(_on(seen, 'storage_locations')) == 2

    async def test_a_rollback_drops_what_was_kept(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        _org, _user, shelf = await _warehouse(db)
        statement = select(StorageLocation.name).where(StorageLocation.id == shelf.id)

        with reference_reads(db):
            async with db.begin_nested() as savepoint:
                shelf.name = 'Dock'
                await db.flush()
                assert await db.scalar(statement) == 'Dock'
                await savepoint.rollback()
            db.expire(shelf)
            assert await db.scalar(statement) == 'Aisle'


class TestPostingBatch:
    async def test_the_appended_rows_are_written_together_at_the_end(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, user, _shelf = await _warehouse(db)

        with _statements(db) as seen:
            async with posting_batch(db):
                for n in range(5):
                    await _entry(db, org, user, n)
                waiting = len(_on(seen, 'audit_log', 'insert'))
        written = len(_on(seen, 'audit_log', 'insert'))

        assert waiting == 0
        assert written == 1
        count = await db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.user_id == user.id)
        )
        assert count == 5

    async def test_outside_a_posting_each_row_is_written_as_it_is_appended(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, user, _shelf = await _warehouse(db)

        with _statements(db) as seen:
            for n in range(3):
                await _entry(db, org, user, n)

        assert len(_on(seen, 'audit_log', 'insert')) == 3

    async def test_a_read_of_the_table_finds_the_rows_still_waiting(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, user, _shelf = await _warehouse(db)

        async with posting_batch(db):
            await _entry(db, org, user, 1)
            await _entry(db, org, user, 2)
            seen = await db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.user_id == user.id)
            )

        assert seen == 2

    async def test_a_savepoint_that_is_rolled_back_takes_its_rows_with_it(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, user, _shelf = await _warehouse(db)

        async with posting_batch(db):
            await _entry(db, org, user, 1)
            savepoint = await db.begin_nested()
            await _entry(db, org, user, 2)
            await savepoint.rollback()
            await _entry(db, org, user, 3)

        snapshots = (
            await db.scalars(
                select(AuditLog.snapshot).where(AuditLog.user_id == user.id)
            )
        ).all()
        assert sorted(s['n'] for s in snapshots) == [1, 3]

    async def test_a_read_inside_a_savepoint_does_not_take_earlier_rows_down_with_it(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, user, _shelf = await _warehouse(db)

        async with posting_batch(db):
            await _entry(db, org, user, 1)
            savepoint = await db.begin_nested()
            await _entry(db, org, user, 2)
            # The read writes the waiting rows, the first of which belongs to
            # the transaction outside the savepoint, inside the savepoint.
            inside = (
                await db.scalars(
                    select(AuditLog.snapshot).where(AuditLog.user_id == user.id)
                )
            ).all()
            await savepoint.rollback()
            await _entry(db, org, user, 3)

        assert sorted(s['n'] for s in inside) == [1, 2]
        snapshots = (
            await db.scalars(
                select(AuditLog.snapshot).where(AuditLog.user_id == user.id)
            )
        ).all()
        assert sorted(s['n'] for s in snapshots) == [1, 3]

    async def test_two_nested_savepoints_rolled_back_owe_an_earlier_row_once(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, user, _shelf = await _warehouse(db)

        async with posting_batch(db):
            await _entry(db, org, user, 1)
            outer = await db.begin_nested()
            await _entry(db, org, user, 2)
            inner = await db.begin_nested()
            await _entry(db, org, user, 3)
            # Writes all three inside the inner savepoint; the first two were
            # waiting before it, and before the outer one for the first.
            await db.scalars(
                select(AuditLog.snapshot).where(AuditLog.user_id == user.id)
            )
            await inner.rollback()
            await outer.rollback()
            await _entry(db, org, user, 4)

        snapshots = (
            await db.scalars(
                select(AuditLog.snapshot).where(AuditLog.user_id == user.id)
            )
        ).all()
        assert sorted(s['n'] for s in snapshots) == [1, 4]

    async def test_a_savepoint_open_before_the_block_takes_the_blocks_rows_with_it(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, user, _shelf = await _warehouse(db)

        # A caller that wraps the posting in its own savepoint: the batch never
        # saw it begin, but everything the block appended happened inside it.
        savepoint = await db.begin_nested()
        async with posting_batch(db):
            await _entry(db, org, user, 1)
            inner = await db.begin_nested()
            await _entry(db, org, user, 2)
            await inner.rollback()
            await _entry(db, org, user, 3)
            await savepoint.rollback()
            await _entry(db, org, user, 4)

        snapshots = (
            await db.scalars(
                select(AuditLog.snapshot).where(AuditLog.user_id == user.id)
            )
        ).all()
        assert sorted(s['n'] for s in snapshots) == [4]

    async def test_a_rollback_of_the_transaction_takes_the_waiting_rows_with_it(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, user, _shelf = await _warehouse(db)
        await db.commit()

        # The caller owns the transaction and may roll it back while the block
        # is open: whatever the block held for it goes back with it, so the
        # block's end must not write the rows into the next transaction.
        async with posting_batch(db):
            await db.scalar(select(func.count()).select_from(AuditLog))
            await _entry(db, org, user, 1)
            await db.rollback()
            await db.refresh(org)
            await db.refresh(user)
            await _entry(db, org, user, 2)

        snapshots = (
            await db.scalars(
                select(AuditLog.snapshot).where(AuditLog.user_id == user.id)
            )
        ).all()
        assert sorted(s['n'] for s in snapshots) == [2]

    async def test_a_block_that_raises_writes_nothing(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, user, _shelf = await _warehouse(db)

        with pytest.raises(RuntimeError):
            async with posting_batch(db):
                await _entry(db, org, user, 1)
                raise RuntimeError('refused')

        count = await db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.user_id == user.id)
        )
        assert count == 0

    async def test_the_caches_are_staled_once_not_once_per_row(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, user, _shelf = await _warehouse(db)

        with patch(
            'app.core.cache.cache_invalidate_org_queries', autospec=True
        ) as invalidate:
            async with posting_batch(db):
                for n in range(5):
                    await _entry(db, org, user, n)

        invalidate.assert_awaited_once_with(org.id)


class TestLocksAreAskedForOnce:
    async def test_a_group_already_locked_is_not_locked_again(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, user, shelf = await _warehouse(db)
        product = ProductTemplate(organization_id=org.id, name='Rye')
        db.add(product)
        await db.flush()

        with _statements(db) as first:
            held = await lock_stock_async(db, org.id, keys=[(product.id, shelf.id)])
        with _statements(db) as again:
            held_again = await lock_stock_async(
                db, org.id, keys=[(product.id, shelf.id)]
            )

        assert held == held_again == {(product.id, shelf.id)}
        assert first
        assert not again

    async def test_a_new_transaction_locks_again(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, user, shelf = await _warehouse(db)
        product = ProductTemplate(organization_id=org.id, name='Rye')
        db.add(product)
        await db.flush()
        await db.commit()
        await lock_stock_async(db, org.id, keys=[(product.id, shelf.id)])
        await db.commit()

        with _statements(db) as seen:
            await lock_stock_async(db, org.id, keys=[(product.id, shelf.id)])

        assert seen

    async def test_a_rolled_back_savepoint_gives_its_locks_up(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, user, shelf = await _warehouse(db)
        product = ProductTemplate(organization_id=org.id, name='Rye')
        db.add(product)
        await db.flush()

        savepoint = await db.begin_nested()
        await lock_stock_async(db, org.id, keys=[(product.id, shelf.id)])
        await savepoint.rollback()

        with _statements(db) as seen:
            await lock_stock_async(db, org.id, keys=[(product.id, shelf.id)])

        assert seen

    async def test_the_memory_is_the_transactions_own(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        await db.commit()
        remembered = transaction_memo(db, 'seen', set)
        remembered.add(1)
        assert transaction_memo(db, 'seen', set) == {1}

        await db.commit()

        assert transaction_memo(db, 'seen', set) == set()


async def _stocked(
    db: AsyncSession, org: Organization, *quantities: str
) -> tuple[ProductTemplate, list[StockValuationLayer]]:
    """A product with one cost layer per quantity, oldest first."""
    product = ProductTemplate(organization_id=org.id, name=f'Layers {uuid.uuid4().hex}')
    db.add(product)
    await db.flush()
    layers = []
    for quantity in quantities:
        layer = await ValuationService._record_receipt_async(
            db, product, Decimal(quantity), Decimal('2.00'), org.id
        )
        assert layer is not None
        layers.append(layer)
    await db.flush()
    return product, layers


def _layer_locks(seen: list[str]) -> list[str]:
    return [s for s in _on(seen, 'stock_valuation_layers') if ' for update' in s]


class TestCostLayersAreLockedOnce:
    async def test_deliveries_drain_the_queue_read_once(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, _user, _shelf = await _warehouse(db)
        product, (first, second) = await _stocked(db, org, '5', '10')

        async with posting_batch(db):
            with _statements(db) as seen:
                await ValuationService.lock_open_layers_async(db, org.id, [product.id])
                for _ in range(2):
                    await ValuationService.post_delivery_by_id_async(
                        db, org.id, product.id, Decimal('3')
                    )

        assert len(_layer_locks(seen)) == 1
        assert (first.remaining_qty, second.remaining_qty) == (0, 9)

    async def test_a_layer_written_after_the_read_is_drained_too(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, _user, _shelf = await _warehouse(db)
        product, (old,) = await _stocked(db, org, '2')

        async with posting_batch(db):
            await ValuationService.lock_open_layers_async(db, org.id, [product.id])
            arrived = await ValuationService._record_receipt_async(
                db, product, Decimal('10'), Decimal('2.00'), org.id
            )
            assert arrived is not None
            await ValuationService.post_delivery_by_id_async(
                db, org.id, product.id, Decimal('5')
            )

        # The arrival was written as a row, not tracked as an object: what is
        # left of it is read back.
        left = await db.scalar(
            select(StockValuationLayer.remaining_qty)
            .where(StockValuationLayer.id == arrived.id)
            .execution_options(populate_existing=True)
        )
        assert old.remaining_qty == 0
        assert left == 7

    async def test_a_rollback_drops_the_queue(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, _user, _shelf = await _warehouse(db)
        product, _layers = await _stocked(db, org, '5')

        async with posting_batch(db) as batch:
            savepoint = await db.begin_nested()
            await ValuationService.lock_open_layers_async(db, org.id, [product.id])
            assert batch.open_layers
            await savepoint.rollback()

            assert not batch.open_layers


class TestALongListOfGroupsIsLockedByIndex:
    async def test_the_same_groups_come_back_as_for_a_short_list(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, _user, shelf = await _warehouse(db)
        products = [
            ProductTemplate(organization_id=org.id, name=f'Rye {n}') for n in range(30)
        ]
        db.add_all(products)
        await db.flush()
        # Thirty shelves' groups named one by one, and five more products named
        # as a whole, three of them stocked on the shelf already.
        named = [(p.id, shelf.id) for p in products[:25]]
        whole = [(p.id, None) for p in products[25:]]
        await lock_stock_async(
            db, org.id, keys=[(p.id, shelf.id) for p in products[25:28]]
        )
        await db.commit()

        with _statements(db) as seen:
            held = await lock_stock_async(db, org.id, keys=[*named, *whole])

        assert held == {(p.id, shelf.id) for p in products[:28]}
        # The anchors created for the named shelves, the ids found, the rows
        # locked: a handful of statements however long the list.
        assert len(seen) <= 4

    async def test_an_order_for_a_document_adds_the_groups_its_reservations_hold(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, _user, shelf = await _warehouse(db)
        products = [
            ProductTemplate(organization_id=org.id, name=f'Oats {n}') for n in range(26)
        ]
        db.add_all(products)
        await db.flush()
        keys = [(p.id, shelf.id) for p in products]

        held = await lock_stock_async(
            db, org.id, keys=keys, reserved_for_document_id=uuid.uuid4()
        )

        assert held == set(keys)


class TestTheShortageQuestionIsAskedOnce:
    """Each movement off a shelf used to be followed by a read of what the grain has free.

    A correction of two hundred lines asked it two hundred times. Inside
    ``ask_what_each_grain_has_free_once`` the movements are written as before
    and the question is put once, for every grain they left, when the block
    ends — the refusal the same, raised from the end of the block.
    """

    async def _shelf_of(
        self, db: AsyncSession, org_id: uuid.UUID, location_id: uuid.UUID, held: int
    ) -> tuple[Any, Any, Any]:
        from tests.integration._shelf import (
            put_on_shelf,
            reserve_for_an_order,
            shelf_keeper,
        )

        template = ProductTemplate(
            organization_id=org_id, name='Bananas', sku=f'BAN-{uuid.uuid4().hex[:8]}'
        )
        db.add(template)
        await db.flush()
        keeper = await shelf_keeper(db, org_id)
        record = await put_on_shelf(db, keeper, template, location_id, 5)
        await reserve_for_an_order(db, template, location_id, held)
        return template, record, keeper

    async def _take(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        template: Any,
        record: Any,
        location_id: uuid.UUID,
        *,
        leaving: int,
        record_left: int,
    ) -> None:
        await post_movement_async(
            db,
            org_id,
            template.id,
            Decimal(leaving),
            from_location_id=location_id,
            reference_type='item',
            reference_id=record.id,
            records=[
                RecordPostDTO(item_id=record.id, new_quantity=Decimal(record_left))
            ],
        )

    async def test_the_refusal_comes_when_the_block_ends_not_before(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Any,
        async_test_storage_location: Any,
    ) -> None:
        db, org_id = real_async_db_session, async_test_household.id
        where = async_test_storage_location.id
        template, record, _ = await self._shelf_of(db, org_id, where, held=4)

        with pytest.raises(StockUnavailableError) as refusal:
            async with ask_what_each_grain_has_free_once(db, org_id):
                # Five on the shelf, four promised: taking three leaves two.
                await self._take(
                    db, org_id, template, record, where, leaving=3, record_left=2
                )
                reached_the_end_of_the_lines = True

        assert reached_the_end_of_the_lines
        assert refusal.value.code == StockUnavailableError.NOT_ENOUGH

    async def test_a_grain_a_later_line_brought_back_is_not_refused(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Any,
        async_test_storage_location: Any,
    ) -> None:
        db, org_id = real_async_db_session, async_test_household.id
        where = async_test_storage_location.id
        template, record, _ = await self._shelf_of(db, org_id, where, held=4)

        async with ask_what_each_grain_has_free_once(db, org_id):
            await self._take(
                db, org_id, template, record, where, leaving=3, record_left=2
            )
            # The next line puts three back: the shelf ends where it began.
            await post_movement_async(
                db,
                org_id,
                template.id,
                Decimal(3),
                to_location_id=where,
                reference_type='item',
                reference_id=record.id,
                records=[RecordPostDTO(item_id=record.id, new_quantity=Decimal(5))],
            )

    async def test_the_question_is_one_statement_however_many_movements(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Any,
        async_test_storage_location: Any,
    ) -> None:
        db, org_id = real_async_db_session, async_test_household.id
        where = async_test_storage_location.id
        template, record, _ = await self._shelf_of(db, org_id, where, held=0)

        with _statements(db) as seen:
            async with ask_what_each_grain_has_free_once(db, org_id):
                for left in (4, 3, 2):
                    await self._take(
                        db, org_id, template, record, where, leaving=1, record_left=left
                    )

        asked = [s for s in seen if ' from items ' in s and ' sum(' in s]
        assert len(asked) == 1
