"""Tax-default writers take their locks in one order: the organization first.

A promotion reads the rate that holds the default before it clears it, and
the organization's default moves under one advisory lock. Taking that lock
*after* the edited rate's own row let two writers hold what the other needed —
B's promotion held the organization's lock and waited for A's row while A's
re-save held A's row and waited for that lock — and PostgreSQL answered one of
them with a deadlock that the retry middleware existed only to hide. A writer
now waits for the organization before it holds any rate's row.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.modules.warehouse import tax_rate_service
from app.modules.warehouse.models.profile import TaxRate
from app.modules.warehouse.tax_rate_service import update_tax_rate


async def _defaults(db: AsyncSession) -> list[str]:
    db.expire_all()
    return list(
        (await db.execute(select(TaxRate.name).where(TaxRate.is_default))).scalars()
    )


async def test_a_writer_waiting_for_the_organization_holds_no_rate_row(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The re-save of the default waits first; the promotion finishes while it does.

    The pause stands where a writer is about to take the organization's lock.
    With the lock first, the writer holds no row; the promotion goes through.
    With the row first, the writer holds A and the promotion waits for it —
    the shape that deadlocks as soon as the re-save resumes.
    """
    db = real_async_db_session
    org_id = async_test_household.id
    first = TaxRate(
        organization_id=org_id, name='A', rate=Decimal('5.00'), is_default=True
    )
    second = TaxRate(organization_id=org_id, name='B', rate=Decimal('10.00'))
    db.add_all([first, second])
    await db.commit()
    first_id, second_id = first.id, second.id

    paused = asyncio.Event()
    resume = asyncio.Event()
    real_lock = tax_rate_service.acquire_advisory_lock

    async def pausing_lock(session: AsyncSession, key: str) -> None:
        if not paused.is_set():
            paused.set()
            await resume.wait()
        await real_lock(session, key)

    monkeypatch.setattr(tax_rate_service, 'acquire_advisory_lock', pausing_lock)

    engine = db.bind
    async with (
        AsyncSession(bind=engine, expire_on_commit=False) as promoting,
        AsyncSession(bind=engine, expire_on_commit=False) as resaving,
    ):

        async def _promote() -> None:
            await update_tax_rate(promoting, org_id, second_id, is_default=True)
            await promoting.commit()

        async def _resave() -> None:
            await update_tax_rate(resaving, org_id, first_id, is_default=True)
            await resaving.commit()

        resaved = asyncio.create_task(_resave())
        await asyncio.wait_for(paused.wait(), timeout=5)

        promoted = asyncio.create_task(_promote())
        try:
            await asyncio.wait_for(promoted, timeout=5)
        except TimeoutError:
            raise AssertionError(
                'the promotion waited for the row the re-save holds, so the two '
                'writers deadlock when the re-save takes the organization lock'
            ) from None
        finally:
            resume.set()

        await asyncio.gather(promoted, resaved)

    # Both committed, and the flag still moved only from A to B and back.
    assert await _defaults(db) == ['A']
