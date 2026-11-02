"""What a transaction has already done, remembered until it ends.

A row lock, once granted, lasts to the end of the transaction, and asking for
it again changes nothing. A caller that must not lock the same thing twice
keeps its answer here: the memo is dropped when the outermost transaction ends
and whenever any part of it is rolled back (a rolled-back savepoint gives its
locks up), so it never claims a lock the database no longer holds.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast
from uuid import UUID

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

_MEMO = 'transaction_memo'


def transaction_memo[T](db: AsyncSession, name: str, factory: Callable[[], T]) -> T:
    """The value kept under *name* for this transaction, made by *factory* the first time."""
    memo: dict[str, Any] = db.sync_session.info.setdefault(_MEMO, {})
    if name not in memo:
        memo[name] = factory()
    return cast(T, memo[name])


@event.listens_for(Session, 'after_transaction_end')
def _forget_at_the_end(session: Session, transaction: SessionTransaction) -> None:
    if transaction.parent is None:
        session.info.pop(_MEMO, None)


@event.listens_for(Session, 'after_soft_rollback')
def _forget_on_rollback(
    session: Session, previous_transaction: SessionTransaction
) -> None:
    session.info.pop(_MEMO, None)


def records_locked(db: AsyncSession) -> set[tuple[UUID, UUID]]:
    """The records ``(organization, id)`` this transaction holds under their row lock."""
    return transaction_memo(db, 'records_locked', set[tuple[UUID, UUID]])
