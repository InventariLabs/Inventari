"""Rows a posting appends, written as sets once it has walked its lines.

A document that moves two hundred lines wrote, for each of them, a movement,
a cost layer, a history row and a journal row — each with its own ``INSERT``
and its own round trip, because each writer flushed as it went. Inside
:func:`posting_batch` those writers hand their row to the batch instead, and
the batch writes them together: one multi-row ``INSERT`` per table, when the
block ends or when a statement is about to read the table they belong to.

Only rows nothing else in the posting depends on belong here — the ledger and
the journals the posting appends to. A row the lines depend on (a record, an
anchor) is written as it was.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import event, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState, Session, SessionTransaction

from app.core.read_scope import tables_of

_KEY = 'posting_batch'


class PostingBatch:
    """The rows waiting to be written, and the caches the journal rows stale."""

    def __init__(self) -> None:
        self.pending: list[Any] = []
        #: Rows that no statement in the posting reads before it ends; a read of
        #: their table does not write them early.
        self.unread: set[int] = set()
        #: How many waiting rows each table has that a read would have to
        #: find; the check made before every statement is a lookup in this.
        self.visible: dict[str, int] = {}
        self.organizations_changed: set[UUID] = set()
        #: The open cost layers of products, read and locked ahead of the
        #: deliveries that drain them, by (organization, product).
        self.open_layers: dict[tuple[UUID, UUID], list[Any]] = {}
        #: What was waiting when each savepoint began, so a savepoint that is
        #: rolled back takes back the rows added inside it and no more.
        self.savepoints: dict[SessionTransaction, set[int]] = {}
        #: Rows that were waiting when a savepoint began and were written while
        #: it was open: its rollback takes their database rows back, so they
        #: go back to waiting.
        self.written_inside: dict[SessionTransaction, list[Any]] = {}

    def add(self, row: Any, *, unread: bool = False) -> None:
        """Hold *row* for the end of the posting.

        *unread* says nothing in the posting looks for it before then, so a
        statement over its table does not call for it early.
        """
        self.pending.append(row)
        if unread:
            self.unread.add(id(row))
        else:
            table = type(row).__table__.name
            self.visible[table] = self.visible.get(table, 0) + 1

    def _forget(self, rows: list[Any]) -> None:
        for row in rows:
            if id(row) not in self.unread:
                table = type(row).__table__.name
                self.visible[table] -= 1
                if not self.visible[table]:
                    del self.visible[table]

    def write_now(self, session: Session, tables: set[str]) -> None:
        """Write the waiting rows of *tables* through the sync session.

        For a statement about to read them.
        """
        rows = [
            row
            for row in self.pending
            if type(row).__table__.name in tables and id(row) not in self.unread
        ]
        if rows:
            taken = {id(row) for row in rows}
            self.pending = [row for row in self.pending if id(row) not in taken]
            self._forget(rows)
            for savepoint, before in self.savepoints.items():
                self.written_inside.setdefault(savepoint, []).extend(
                    row for row in rows if id(row) in before
                )
            for model, values in _by_table(rows).items():
                session.execute(insert(model), values)

    async def flush(self, db: AsyncSession) -> None:
        # Emptied before anything is written, so a writer that reaches here
        # again from inside the flush finds nothing to repeat.
        rows, self.pending = self.pending, []
        self.unread.clear()
        self.visible.clear()
        organizations, self.organizations_changed = self.organizations_changed, set()
        for model, values in _by_table(rows).items():
            await db.execute(insert(model), values)
        if organizations:
            from app.core.cache import cache_invalidate_org_queries

            for organization_id in organizations:
                await cache_invalidate_org_queries(organization_id)


def _by_table(rows: list[Any]) -> dict[Any, list[dict[str, Any]]]:
    """The waiting rows as column values, grouped by the table they go to.

    Written with a bulk insert rather than added to the session: the rows are
    appended and never read back as objects, and tracking each of them in the
    unit of work cost more than writing it.
    """
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        values = {
            key: value
            for key, value in row.__dict__.items()
            if key != '_sa_instance_state'
        }
        grouped.setdefault(type(row), []).append(values)
    return grouped


def current_batch(db: AsyncSession) -> PostingBatch | None:
    """The batch of this session's posting, or ``None`` outside one."""
    session = getattr(db, 'sync_session', None)
    if session is None:
        # A session double with no synchronous half has no posting either.
        return None
    batch: PostingBatch | None = session.info.get(_KEY)
    return batch


@asynccontextmanager
async def posting_batch(db: AsyncSession) -> AsyncIterator[PostingBatch]:
    """Collect the appended rows of the block and write them as sets at its end.

    Nesting joins the outer block. When the block raises nothing is written:
    the caller's transaction is going back anyway.
    """
    info = db.sync_session.info
    existing: PostingBatch | None = info.get(_KEY)
    if existing is not None:
        yield existing
        return
    batch = info[_KEY] = PostingBatch()
    try:
        yield batch
        await batch.flush(db)
    finally:
        info.pop(_KEY, None)


@event.listens_for(Session, 'do_orm_execute')
def _write_what_a_statement_reads(state: ORMExecuteState) -> None:
    """Write the waiting rows of the tables a statement touches before it runs.

    The batch holds rows the database has not seen. Anything in the posting
    that reads or updates those tables — the movements a check sums, the cost
    layers a later line drains — would otherwise miss them, so the rows of
    those tables are written first and the statement finds what it always
    found. Rows of other tables go on waiting.
    """
    batch: PostingBatch | None = state.session.info.get(_KEY)
    if batch is None or not batch.visible:
        return
    touched = tables_of(state)
    if not touched.isdisjoint(batch.visible):
        batch.write_now(state.session, touched)


@event.listens_for(Session, 'after_transaction_create')
def _mark_a_savepoint(session: Session, transaction: SessionTransaction) -> None:
    batch: PostingBatch | None = session.info.get(_KEY)
    if batch is not None and transaction.nested:
        batch.savepoints[transaction] = {id(row) for row in batch.pending}


@event.listens_for(Session, 'after_soft_rollback')
def _take_back_a_savepoints_rows(
    session: Session, previous_transaction: SessionTransaction
) -> None:
    batch: PostingBatch | None = session.info.get(_KEY)
    if batch is not None:
        # Rolled back objects no longer say what the database holds.
        batch.open_layers.clear()
    if batch is not None and previous_transaction.parent is None:
        # The caller's own transaction went back: every row the block held was
        # appended inside it, and none may be written into the next one.
        batch.pending = []
        batch.unread.clear()
        batch.visible.clear()
        batch.savepoints.clear()
        batch.written_inside.clear()
    elif batch is not None and previous_transaction.nested:
        # A savepoint the batch never saw begin was open before the block: every
        # row the block appended happened inside it, so none of them is its
        # own to keep.
        before = batch.savepoints.pop(previous_transaction, set())
        written = batch.written_inside.pop(previous_transaction, [])
        gone = [row for row in batch.pending if id(row) not in before]
        batch._forget(gone)
        batch.pending = [row for row in batch.pending if id(row) in before]
        batch.unread &= before
        # Written inside the savepoint, so gone from the database with it;
        # they were not its own, so they are still owed, ahead of the rest.
        # Only rows a read could look for are ever written early.
        # A row written, taken back and written again is listed twice, and
        # one an inner savepoint's rollback already put back is waiting.
        waiting = {id(row) for row in batch.pending}
        written = list(
            {id(row): row for row in written if id(row) not in waiting}.values()
        )
        batch.pending = [*written, *batch.pending]
        for row in written:
            table = type(row).__table__.name
            batch.visible[table] = batch.visible.get(table, 0) + 1
