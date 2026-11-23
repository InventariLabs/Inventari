"""Two receipts of one new batch share its row.

A batch is unique per organization and product name, and the receipt path
looks it up before writing it. Two receipts of different documents that carry
the same batch name, posted at once, both looked and found nothing; the second
insert met the unique key and answered 500. The insert now settles the race —
the second waits for the first and takes the row that stands, with the first
writer's dates.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.services._stock_lot_ops import get_or_create_lot_async


async def _backend_pid(session: AsyncSession) -> int:
    return int(await session.scalar(text('SELECT pg_backend_pid()')))


async def _waits_for(db: AsyncSession, pid: int, other_pid: int) -> bool:
    blocking = await db.scalar(
        text('SELECT :other = ANY(pg_blocking_pids(:pid))'),
        {'other': other_pid, 'pid': pid},
    )
    return bool(blocking)


async def _wait_until_blocked_by(db: AsyncSession, pid: int, other_pid: int) -> None:
    """Wait until the backend *pid* queues behind *other_pid*'s lock."""
    deadline = time.monotonic() + 5
    while not await _waits_for(db, pid, other_pid):
        if time.monotonic() > deadline:
            raise AssertionError('the second receipt never reached the lot insert')
        await asyncio.sleep(0.01)


async def test_two_receipts_of_one_new_batch_write_it_once(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
) -> None:
    db = real_async_db_session
    org_id = async_test_household.id
    template = ProductTemplate(
        organization_id=org_id,
        name='Raced Batch Product',
    )
    db.add(template)
    await db.commit()
    template_id = template.id

    engine = db.bind
    today = datetime.now(UTC).date()
    first_expiry = today + timedelta(days=365)
    second_expiry = today + timedelta(days=730)
    async with (
        AsyncSession(bind=engine, expire_on_commit=False) as first,
        AsyncSession(bind=engine, expire_on_commit=False) as second,
    ):
        lot = await get_or_create_lot_async(
            first,
            org_id,
            template_id,
            'LOT-ONE',
            expiry_date=first_expiry,
        )
        first_pid = await _backend_pid(first)
        second_pid = await _backend_pid(second)

        racing = asyncio.create_task(
            get_or_create_lot_async(
                second,
                async_test_household.id,
                template.id,
                'LOT-ONE',
                expiry_date=second_expiry,
            )
        )
        try:
            await _wait_until_blocked_by(db, second_pid, first_pid)
        except BaseException:
            await first.rollback()
            await asyncio.gather(racing, return_exceptions=True)
            raise
        await first.commit()
        taken = await racing

    assert taken.id == lot.id
    assert taken.expiry_date == first_expiry

    db.expire_all()
    count = await db.scalar(
        select(func.count())
        .select_from(StockLot)
        .where(
            StockLot.organization_id == org_id,
            StockLot.product_template_id == template_id,
            StockLot.name == 'LOT-ONE',
        )
    )
    assert count == 1
