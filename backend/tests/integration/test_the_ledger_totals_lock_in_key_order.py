"""Taking a movement away locks the ledger's totals in key order, as adding one does.

The triggers on ``stock_moves`` keep ``stock_ledger_totals``: one row per
product and shelf, moved in the statement that writes the movement. Their
adding half has always taken those rows in key order, so two statements over
the same groups queue rather than deadlock. Their subtracting half — a
movement deleted, or rewritten because the shelf, batch, partner or user it
names was deleted and its key set to NULL — took the rows in whatever order
the join produced, so two such statements could each hold a row the other
was waiting for.

The test holds the highest-keyed total of a product from one transaction,
removes the product's movements from a second, and asks a third which rows
the second has taken while it waits. Taken in key order, every lower row is
already its own; in the order the rows lie on disk, which here is the
reverse, it waits with none of them.

Measured: against the old function, with the planner kept from the sorted
plan it picks for a handful of rows, the removal waits holding none of the
lower rows.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_SHELVES = 8
_LOCK_NOT_AVAILABLE = '55P03'
# Only for a statement stuck on something else: nothing here takes this long.
_NEVER_ARRIVES_AFTER = 60.0


def _async_test_url() -> str:
    return settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


def _sqlstate(exc: BaseException) -> str | None:
    seen: BaseException | None = exc
    while seen is not None:
        code = getattr(seen, 'sqlstate', None) or getattr(seen, 'pgcode', None)
        if isinstance(code, str):
            return code
        seen = getattr(seen, 'orig', None) or seen.__cause__
    return None


@pytest.fixture
async def engine():
    engine = create_async_engine(
        _async_test_url(),
        echo=False,
        poolclass=NullPool,
        connect_args={
            'server_settings': {'lock_timeout': f'{int(_NEVER_ARRIVES_AFTER)}s'}
        },
    )
    yield engine
    await engine.dispose()


async def _stocked_shelves(
    db: AsyncSession, org_id: uuid.UUID, created_by: uuid.UUID
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """A product received onto eight shelves, the totals' rows laid down in
    descending key order: one statement per shelf, highest key first."""
    template = ProductTemplate(
        organization_id=org_id,
        name='Locked in order',
        sku=f'SKU-ORDER-{uuid.uuid4().hex[:8]}',
    )
    db.add(template)
    shelves = [
        StorageLocation(
            organization_id=org_id, created_by=created_by, name=f'Order shelf {n}'
        )
        for n in range(_SHELVES)
    ]
    db.add_all(shelves)
    await db.flush()
    keys = sorted(shelf.id for shelf in shelves)
    for shelf_id in reversed(keys):
        await db.execute(
            insert(StockMove).values(
                organization_id=org_id,
                product_template_id=template.id,
                to_location_id=shelf_id,
                quantity=Decimal('1'),
                state='done',
            )
        )
    await db.commit()
    return template.id, keys


async def _wait_until_blocked(
    engine: AsyncEngine, pid: int, racer: asyncio.Task[object]
) -> None:
    deadline = time.monotonic() + _NEVER_ARRIVES_AFTER
    async with engine.connect() as conn:
        while not racer.done() and time.monotonic() < deadline:
            waiting = await conn.scalar(
                text('SELECT count(*) FROM pg_locks WHERE pid = :pid AND NOT granted'),
                {'pid': pid},
            )
            if waiting:
                return
            await asyncio.sleep(0.05)
    if racer.done():
        racer.result()
    raise AssertionError('the removal never waited on the held total')


async def _taken(
    engine: AsyncEngine, org_id: uuid.UUID, template_id: uuid.UUID, shelf: uuid.UUID
) -> bool:
    """Whether another transaction holds this total's row right now."""
    async with engine.connect() as conn:
        try:
            await conn.execute(
                text(
                    'SELECT 1 FROM stock_ledger_totals '
                    'WHERE organization_id = :org AND product_template_id = :t '
                    'AND storage_location_id = :shelf FOR UPDATE NOWAIT'
                ),
                {'org': org_id, 't': template_id, 'shelf': shelf},
            )
        except DBAPIError as exc:
            if _sqlstate(exc) == _LOCK_NOT_AVAILABLE:
                return True
            raise
        finally:
            await conn.rollback()
    return False


async def test_a_removal_takes_every_lower_total_before_it_waits(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_user,
    engine: AsyncEngine,
) -> None:
    org_id = async_test_household.id
    template_id, keys = await _stocked_shelves(
        real_async_db_session, org_id, async_test_user.id
    )

    factory = async_sessionmaker(engine, class_=AsyncSession)
    async with factory() as holder, factory() as remover:
        await holder.execute(
            text(
                'SELECT 1 FROM stock_ledger_totals '
                'WHERE organization_id = :org AND product_template_id = :t '
                'AND storage_location_id = :shelf FOR UPDATE'
            ),
            {'org': org_id, 't': template_id, 'shelf': keys[-1]},
        )
        pid = int(await remover.scalar(text('SELECT pg_backend_pid()')))
        # Eight rows are few enough that the planner sorts them for the
        # grouping and reaches the totals through their key, which visits
        # them in key order whether the statement asks for it or not. A large
        # removal hashes instead, and visits them in no order; these settings
        # make the small one plan the same way. A sort the statement asks for
        # still happens.
        for setting in ('enable_sort', 'enable_indexscan', 'enable_bitmapscan'):
            await remover.execute(text(f'SET LOCAL {setting} = off'))
        removal = asyncio.create_task(
            remover.execute(
                text('DELETE FROM stock_moves WHERE product_template_id = :t'),
                {'t': template_id},
            )
        )
        try:
            await _wait_until_blocked(engine, pid, removal)
            taken = [
                await _taken(engine, org_id, template_id, shelf) for shelf in keys[:-1]
            ]
        finally:
            await holder.rollback()
            await removal
            await remover.rollback()

    assert taken == [True] * (_SHELVES - 1)
