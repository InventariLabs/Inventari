"""Reference data read once while a document posts, not once per line.

Posting a 200-line receipt asked the database for the same organization row,
the same unit of measure and the same shelf's type again for every line: the
database answered in microseconds, and the round trips and the ORM's work
around each took the other twelve seconds. Inside :func:`reference_reads` a
``SELECT`` over the tables below is answered once per distinct statement and
parameters; every later identical one is served from what the first returned.

Only tables a posting reads and does not write are listed, and the cache is
dropped the moment the session writes one of them (a flush that carries a
row of a listed table, or a bulk ``UPDATE`` / ``DELETE`` on it), when the
transaction ends, and when the block does. A ``SELECT ... FOR UPDATE`` and a
refresh always reach the database. The scope speaks for one session, which is
one request's unit of work, so what it hands out are that session's own
instances.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, SessionTransaction
from sqlalchemy.sql import ClauseElement, TableClause, visitors

#: The tables whose rows a document posting reads over and over and never
#: changes: who the organization is, what a unit converts to, what a shelf
#: and its type are, what a product card says.
_REFERENCE_TABLES: frozenset[str] = frozenset(
    {
        'organizations',
        'uoms',
        'uom_categories',
        'storage_types',
        'storage_locations',
        'product_templates',
        'categories',
        'inventory_periods',
    }
)

_KEY = 'reference_reads'
_HELD = 'reference_reads_held'


@contextmanager
def reference_reads(db: Any) -> Iterator[None]:
    """Serve repeated reads of reference data from the first answer, in this block.

    *db* is the request's session (sync or async). Nesting joins the outer
    block.
    """
    info = (db.sync_session if hasattr(db, 'sync_session') else db).info
    if _KEY in info:
        yield
        return
    info[_KEY] = {}
    try:
        yield
    finally:
        info.pop(_KEY, None)
        info.pop(_HELD, None)


def keep_loaded(db: Any, rows: Iterable[Any]) -> None:
    """Keep *rows* alive until the block ends, so ``db.get`` finds them without a query.

    The session's identity map holds its instances weakly: a row loaded for
    its id and dropped is forgotten, and the next ``get`` asks the database
    again. A posting that loads the products of all its lines at once keeps
    them here, and each line's lookup of its own product is then answered by
    the session. Outside a block this does nothing.
    """
    info = (db.sync_session if hasattr(db, 'sync_session') else db).info
    if _KEY in info:
        info.setdefault(_HELD, []).extend(rows)


_LAST_TABLES = 'tables_of_the_last_statement'


def tables_of(state: ORMExecuteState) -> set[str]:
    """The names of every table the statement touches, subqueries included.

    Asked by two listeners about the same statement, one after the other, so
    the answer is kept, with the session, for the statement that is current.
    """
    last: tuple[ORMExecuteState, set[str]] | None = state.session.info.get(_LAST_TABLES)
    if last is not None and last[0] is state:
        return last[1]
    names = {table.name for mapper in state.all_mappers for table in mapper.tables}
    statement = state.statement
    if isinstance(statement, ClauseElement):
        names.update(
            element.name
            for element in visitors.iterate(statement)
            if isinstance(element, TableClause) and element.name
        )
    state.session.info[_LAST_TABLES] = (state, names)
    return names


def _cache_key(state: ORMExecuteState) -> tuple[Any, ...]:
    statement: Any = state.statement
    cache_key = statement._generate_cache_key()
    if cache_key is None:
        return ()
    values = tuple(repr(bind.effective_value) for bind in cache_key.bindparams)
    return (cache_key.key, values, repr(state.parameters))


@event.listens_for(Session, 'do_orm_execute')
def _serve_repeated_reads(state: ORMExecuteState) -> Any:
    cache: dict[Any, Any] | None = state.session.info.get(_KEY)
    if cache is None:
        return None
    tables = tables_of(state)
    if not tables & _REFERENCE_TABLES:
        return None
    if not state.is_select:
        cache.clear()
        return None
    if (
        not tables <= _REFERENCE_TABLES
        or getattr(state.load_options, '_refresh_state', None) is not None
        or state.is_column_load
        or (
            state.execution_options.get('populate_existing')
            and not state.is_relationship_load
        )
        or getattr(state.statement, '_for_update_arg', None) is not None
    ):
        return None
    key = _cache_key(state)
    if not key:
        return None
    # A cached answer is returned before the session's own autoflush would
    # write a pending edit, so the edit has to drop it here.
    if _holds_a_reference_edit(state.session):
        cache.clear()
    frozen = cache.get(key)
    if frozen is None:
        cache[key] = frozen = state.invoke_statement().freeze()
    return frozen()


def _holds_a_reference_edit(session: Session) -> bool:
    """Whether the session has a new, changed or deleted row of a listed table."""
    for obj in (*session.new, *session.dirty, *session.deleted):
        table = getattr(obj, '__table__', None)
        if table is not None and table.name in _REFERENCE_TABLES:
            return True
    return False


@event.listens_for(Session, 'before_flush')
def _drop_on_write(session: Session, _flush_context: Any, _instances: Any) -> None:
    cache = session.info.get(_KEY)
    if cache and _holds_a_reference_edit(session):
        cache.clear()


@event.listens_for(Session, 'after_transaction_end')
def _drop_at_transaction_end(session: Session, transaction: SessionTransaction) -> None:
    # A savepoint that is released keeps what it wrote, so only the end of the
    # outermost transaction drops the answers; one that is rolled back is
    # caught by ``_drop_on_rollback``.
    if transaction.parent is None:
        cache = session.info.get(_KEY)
        if cache:
            cache.clear()


@event.listens_for(Session, 'after_soft_rollback')
def _drop_on_rollback(
    session: Session, previous_transaction: SessionTransaction
) -> None:
    cache = session.info.get(_KEY)
    if cache:
        cache.clear()
