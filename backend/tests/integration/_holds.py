"""A hold a test writes by hand, with the grain the reserving path gives it.

The reserving path (``reserve_for_document_async``) writes each reservation
row with the anchor of its group and the batch and owner it drew on, and the
records' view counts the hold by those columns. A test that writes a row
itself, to set up a shape no door leaves, names the grain the same way — any
object carrying a group's key will do, a :class:`~app.core.testing.ShelfRow`
most often — or the view files the hold elsewhere.

A hold that outgrows its grain is refused at commit by the database itself
(``holdguard01``). An instance older than that guard can still hold one, and
the checks that report such a grain are tested on it: ``past_the_hold_guard``
writes it in the caller's transaction with the triggers on the two tables
switched off and back on before the commit — the guard's, and any other a
test stands beside it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import Row, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.stock_anchor import StockAnchor
from app.models.stock_reservation import StockReservation
from app.services._stock_quant_ops import anchor_ids_async


class Grain(Protocol):
    """The key of a group of stock: a product on a shelf, in a batch, of an owner."""

    organization_id: uuid.UUID
    product_template_id: uuid.UUID
    storage_location_id: uuid.UUID
    lot_id: uuid.UUID | None
    owner_id: uuid.UUID | None


def _row(
    grain: Grain,
    anchor_id: uuid.UUID,
    quantity: Decimal,
    document_id: uuid.UUID | None,
) -> StockReservation:
    return StockReservation(
        organization_id=grain.organization_id,
        document_id=document_id or uuid.uuid4(),
        anchor_id=anchor_id,
        lot_id=grain.lot_id,
        owner_id=grain.owner_id,
        quantity=quantity,
    )


async def hold_async(
    db: AsyncSession,
    grain: Grain,
    quantity: Decimal,
    *,
    document_id: uuid.UUID | None = None,
) -> StockReservation:
    """A reservation row on *grain*, added to the session; a document if none is named."""
    group = (grain.product_template_id, grain.storage_location_id)
    anchors = await anchor_ids_async(db, grain.organization_id, [group])
    row = _row(grain, anchors[group], quantity, document_id)
    db.add(row)
    return row


def hold(
    db: Session,
    grain: Grain,
    quantity: Decimal,
    *,
    document_id: uuid.UUID | None = None,
) -> StockReservation:
    """The same row through a sync session."""
    key = {
        'organization_id': grain.organization_id,
        'product_template_id': grain.product_template_id,
        'storage_location_id': grain.storage_location_id,
    }
    db.execute(
        pg_insert(StockAnchor)
        .values(**key)
        .on_conflict_do_nothing(index_elements=list(key))
    )
    anchor_id = db.scalars(
        select(StockAnchor.id).where(
            *(getattr(StockAnchor, column) == value for column, value in key.items())
        )
    ).one()
    row = _row(grain, anchor_id, quantity, document_id)
    db.add(row)
    return row


#: The triggers of ``holdguard01``, by table.
_HOLD_GUARD = (
    ('items', 'ck_stock_holds_within_stock'),
    ('items', 'ck_stock_holds_within_stock_on_delete'),
    ('stock_reservations', 'ck_stock_holds_within_stock'),
)

# Every trigger switched on over the tables the guard watches. The guard's
# need not be the only ones in a test run: another deferred check standing
# on either table, with an event queued inside the block, makes switching
# the guard back on fail — a table with pending trigger events cannot be
# altered.
_STANDING = text(
    'SELECT c.relname, t.tgname FROM pg_trigger t'
    ' JOIN pg_class c ON c.oid = t.tgrelid'
    " WHERE NOT t.tgisinternal AND t.tgenabled <> 'D'"
    " AND c.relnamespace = 'public'::regnamespace"
    " AND c.relname IN ('items', 'stock_reservations')"
    ' ORDER BY 1, 2'
)


def _switched(standing: Sequence[Row[Any]], state: str) -> list[str]:
    triggers = [(table, name) for table, name in standing]
    missing = set(_HOLD_GUARD) - set(triggers)
    assert not missing, f'the hold guard is not up: {sorted(missing)}'
    return [f'ALTER TABLE {table} {state} TRIGGER "{name}"' for table, name in triggers]


@contextmanager
def past_the_hold_guard(db: Session) -> Iterator[None]:
    """Write a hold its grain cannot cover, as an instance older than the guard holds one.

    The writes inside are flushed while the triggers are off, so none of
    them queues a check; the same triggers are on again before the caller
    commits. DDL is transactional: a transaction that fails in between
    takes the switch back with it.
    """
    standing = db.execute(_STANDING).all()
    for statement in _switched(standing, 'DISABLE'):
        db.execute(text(statement))
    yield
    db.flush()
    for statement in _switched(standing, 'ENABLE'):
        db.execute(text(statement))


@asynccontextmanager
async def past_the_hold_guard_async(db: AsyncSession) -> AsyncIterator[None]:
    """The same through an async session."""
    standing = (await db.execute(_STANDING)).all()
    for statement in _switched(standing, 'DISABLE'):
        await db.execute(text(statement))
    yield
    await db.flush()
    for statement in _switched(standing, 'ENABLE'):
        await db.execute(text(statement))
