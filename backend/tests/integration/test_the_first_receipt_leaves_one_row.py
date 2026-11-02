"""Racing receipts of the same product land every delivery on the records.

This began as the first-receipt race on the quant table: ``increment_quant_async``
locked nothing when the row did not exist yet, the unique constraint meant to
make the loser retry could not fire for a lotless quant, and two double-clicked
scans left two rows the reconciliation reported forever. The table is gone
(``quantdrop01``), and a first receipt now queues on its group's anchor.

What is left to hold is the records' side of the same race: receipts racing
through the document register must land every delivery on the shelf, and the
movement ledger must explain what the shelf holds afterwards.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.testing import ShelfRow
from app.modules.warehouse.schemas import DocumentComplete

from ._core_api_helpers import make_template


def _async_test_url() -> str:
    return settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheSameRaceThroughTheDocumentPath:
    """The register is the shape the historical drift was found on: not a
    core call, but racing IN documents — each completion landing its line on
    the shelf's record and writing the movement beside it. After the race the
    shelf must hold every document's lines, and the reconciliation report —
    the instrument that kept flagging the old duplicates — must find nothing
    between the shelf and the ledger to flag.

    The race used to be left to the scheduler, and twice went red on a loaded
    full run with nothing kept of why. It is forced now: every register queues
    on the group's anchor — the one lock racing receipts of one product on one
    shelf meet — before any of them is let through, and what each register
    raised, if anything, is the failure's message."""

    async def test_racing_document_receipts_reconcile_clean(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_location,
        async_test_user,
    ):
        from app.models.stock_anchor import StockAnchor
        from app.modules.warehouse._document_workflow_transitions import (
            complete_document,
            confirm_document,
        )
        from app.modules.warehouse.document_profile_service import (
            get_or_create_profile,
        )
        from app.modules.warehouse.models import (
            Document,
            DocumentLine,
            DocumentStatus,
        )
        from app.services.analytics.reconciliation import get_reconciliation_async

        db = real_async_db_session
        org_id = async_test_household.id
        location_id = async_test_storage_location.id
        template = await db.run_sync(lambda s: make_template(s, org_id))
        # Confirming consults the org's document profile; racing workers
        # would otherwise race each other to create it (uq_document_profile_
        # org) instead of racing on the bridge this test is about.
        await get_or_create_profile(db, org_id)

        workers = 4
        per = Decimal('3')
        drafts = []
        for _ in range(workers):
            doc = Document(
                organization_id=org_id,
                type='IN',
                number=f'RK/{uuid.uuid4().hex[:10]}',
                status=DocumentStatus.DRAFT.value,
                target_location_id=location_id,
                created_by=async_test_user.id,
                lines=[
                    DocumentLine(
                        product_template_id=template.id,
                        name=template.name,
                        quantity=per,
                        expected_quantity=per,
                        done_quantity=Decimal('0'),
                    )
                ],
            )
            db.add(doc)
            drafts.append(doc)
        await db.commit()
        doc_ids = [doc.id for doc in drafts]

        engine = create_async_engine(_async_test_url(), echo=False, poolclass=NullPool)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )

        async def run_the_register(doc_id) -> None:
            async with factory() as session:
                await confirm_document(session, org_id, doc_id, async_test_user.id)
                await session.commit()
                await complete_document(
                    session,
                    org_id,
                    doc_id,
                    async_test_user.id,
                    DocumentComplete(complete_as_planned=True),
                )
                await session.commit()

        try:
            # The first receipt of a group writes its anchor. Written here and
            # held, it makes every register wait at that write; let go, one
            # of them writes it and the rest queue behind that one.
            async with factory() as holder:
                await holder.execute(
                    insert(StockAnchor).values(
                        organization_id=org_id,
                        product_template_id=template.id,
                        storage_location_id=location_id,
                    )
                )
                racers = [
                    asyncio.create_task(run_the_register(doc_id)) for doc_id in doc_ids
                ]
                await _wait_for_lock_waiters(factory, expected=workers)
                await holder.rollback()
            outcomes = await asyncio.gather(*racers, return_exceptions=True)
        finally:
            await engine.dispose()

        raised = [repr(outcome) for outcome in outcomes if outcome is not None]
        assert not raised, raised

        async with factory() as verify:
            total = await verify.scalar(
                select(func.coalesce(func.sum(ShelfRow.quantity), 0)).where(
                    ShelfRow.organization_id == org_id,
                    ShelfRow.product_template_id == template.id,
                    ShelfRow.storage_location_id == location_id,
                )
            )
            report = await get_reconciliation_async(verify, org_id)

        assert total == per * workers, (
            f'the shelf holds {total} after {workers} receipts of {per}'
        )
        assert report.quant_move_drift_count == 0, (
            f'the shelf and the ledger disagree after the race: '
            f'{report.quant_move_drift_count} group(s), '
            f'total drift {report.quant_move_drift_total}'
        )


async def _wait_for_lock_waiters(factory, expected: int, timeout: float = 15.0) -> None:
    """Block until *expected* backends of this database are waiting on a lock.

    Scoped to the current database: each xdist worker has its own, so another
    worker's contention cannot satisfy the count.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    async with factory() as probe:
        while True:
            waiting = await probe.scalar(
                text(
                    'SELECT count(*) FROM pg_stat_activity '
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            )
            # pg_stat_activity is a snapshot per transaction: without ending
            # it, the loop would reread the moment of its first query forever.
            await probe.rollback()
            if waiting >= expected:
                return
            if asyncio.get_running_loop().time() > deadline:
                activity = (
                    await probe.execute(
                        text(
                            'SELECT current_database(), datname, state, '
                            'wait_event_type, wait_event, left(query, 60) '
                            'FROM pg_stat_activity WHERE datname = current_database()'
                        )
                    )
                ).all()
                raise AssertionError(
                    f'{waiting} backend(s) waiting on a lock, expected {expected}: '
                    f'the interleaving this test forces never happened. {activity}'
                )
            await asyncio.sleep(0.05)


@pytest.mark.integration
@pytest.mark.asyncio
class TestAReceiptThatWaitedForTheRecord:
    """The shelf record is the stock the reconciliation holds to the ledger.

    A receipt found the record without a lock, added its quantity to what it
    read, and handed the sum to an update that locked the row only then. Two
    receipts that read the record before either wrote it both wrote the same
    sum: the quant, raised by increment under its own lock, held every
    delivery, and the record held one fewer. The racing-register test above
    caught it twice, under load, as a drift of exactly one line's quantity;
    the ledger, which holds every delivery's movement, would show it now.

    Here the interleaving is forced instead of hoped for: the record's row is
    held, both receipts read it and queue behind the hold, and only then is it
    let go.
    """

    async def test_both_receipts_land_on_the_record_not_just_the_last(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_location,
        async_test_user,
    ):
        from app.models.item import Item
        from app.modules.warehouse._document_workflow_transitions import (
            complete_document,
            confirm_document,
        )
        from app.modules.warehouse.document_profile_service import (
            get_or_create_profile,
        )
        from app.modules.warehouse.models import (
            Document,
            DocumentLine,
            DocumentStatus,
        )
        from app.services.analytics.reconciliation import get_reconciliation_async

        db = real_async_db_session
        org_id = async_test_household.id
        location_id = async_test_storage_location.id
        template = await db.run_sync(lambda s: make_template(s, org_id))
        await get_or_create_profile(db, org_id)

        per = Decimal('3')
        docs = [
            Document(
                organization_id=org_id,
                type='IN',
                number=f'LU/{uuid.uuid4().hex[:10]}',
                status=DocumentStatus.DRAFT.value,
                target_location_id=location_id,
                created_by=async_test_user.id,
                lines=[
                    DocumentLine(
                        product_template_id=template.id,
                        name=template.name,
                        quantity=per,
                        expected_quantity=per,
                        done_quantity=Decimal('0'),
                    )
                ],
            )
            for _ in range(3)
        ]
        db.add_all(docs)
        await db.commit()
        first, racing = docs[0].id, [docs[1].id, docs[2].id]

        engine = create_async_engine(_async_test_url(), echo=False, poolclass=NullPool)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )

        async def register(doc_id) -> None:
            async with factory() as session:
                await confirm_document(session, org_id, doc_id, async_test_user.id)
                await session.commit()
                await complete_document(
                    session,
                    org_id,
                    doc_id,
                    async_test_user.id,
                    DocumentComplete(complete_as_planned=True),
                )
                await session.commit()

        try:
            # The first delivery opens the record; the race is over topping it up.
            await register(first)
            async with factory() as lookup:
                record_id = await lookup.scalar(
                    select(Item.id).where(
                        Item.organization_id == org_id,
                        Item.template_id == template.id,
                        Item.storage_location_id == location_id,
                    )
                )
            assert record_id is not None

            async with factory() as holder:
                await holder.execute(
                    select(Item.id).where(Item.id == record_id).with_for_update()
                )
                racers = [asyncio.create_task(register(d)) for d in racing]
                await _wait_for_lock_waiters(factory, expected=len(racers))
                await holder.rollback()
            await asyncio.gather(*racers)

            async with factory() as verify:
                on_record = await verify.scalar(
                    select(Item.quantity).where(Item.id == record_id)
                )
                report = await get_reconciliation_async(verify, org_id)
        finally:
            await engine.dispose()

        assert on_record == per * 3, (
            f'the record holds {on_record} after three receipts of {per} — '
            'a receipt wrote a sum it had read before the other one landed'
        )
        assert report.quant_move_drift_count == 0, report
