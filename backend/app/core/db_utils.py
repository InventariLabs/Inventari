"""Shared database utilities: pagination, org-scoped 404 lookups, after-commit work.

The pagination and lookup helpers exist in sync (``Session``) and async (``AsyncSession``)
variants. Services that paginate or fetch a single org-owned row should use
these instead of duplicating the count/limit/offset or id+org query pattern.
"""

from collections.abc import Awaitable, Callable, Iterable
from typing import Any, TypeVar, cast
from uuid import UUID

from sqlalchemy import ColumnElement, Select, any_, func, literal, select, text
from sqlalchemy import event as sa_event
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from app.core.exceptions import NotFoundException
from app.core.logging import get_logger
from app.i18n import Language

logger = get_logger(__name__)

T = TypeVar('T')
M = TypeVar('M', bound=Any)

# Table names whose plural does not strip to the i18n resource name via
# ``rstrip('s')`` (e.g. ``'categories'`` -> ``'categorie'``). ``resource``
# still wins when passed explicitly.
_IRREGULAR_RESOURCES: dict[str, str] = {
    'categories': 'category',
}


def _resource_name_from_table(table_name: str) -> str:
    """Derive the i18n ``<resource>_not_found`` key from a table name."""
    return _IRREGULAR_RESOURCES.get(table_name, table_name.rstrip('s'))


def escape_ilike(value: str) -> str:
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


#: Below this a typed fragment is matched at the start of a value.
#:
#: One or two characters say how a name begins, not what it contains: "h" is
#: inside a third of any catalogue, so matching it anywhere read every product
#: to rank ten of them, and no trigram index can answer a fragment that short
#: anywhere but at the start.
SUBSTRING_MIN_LENGTH = 3


def typed_fragment_pattern(text: str) -> str:
    """The ``ILIKE`` pattern for what someone typed into a search.

    Anywhere in the value, or at its start when the fragment is shorter than
    ``SUBSTRING_MIN_LENGTH``.
    """
    escaped = escape_ilike(text)
    return f'{escaped}%' if len(text) < SUBSTRING_MIN_LENGTH else f'%{escaped}%'


def constraint_name_of(exc: IntegrityError) -> str | None:
    """The constraint an ``IntegrityError`` names, as the driver reports it.

    psycopg puts it in ``diag.constraint_name``. SQLAlchemy's asyncpg adapter
    re-raises asyncpg's error as its own, without ``diag``, and chains the
    original: that one carries ``constraint_name``. A driver that gives
    neither leaves ``None`` here and ``hit_constraint`` falls back to the
    message.
    """
    orig = exc.orig
    named = getattr(getattr(orig, 'diag', None), 'constraint_name', None)
    return named or getattr(getattr(orig, '__cause__', None), 'constraint_name', None)


def hit_constraint(exc: IntegrityError, *names: str) -> bool:
    """Whether an ``IntegrityError`` is one of the named constraints.

    the driver's ``constraint_name`` is what decides; the message is read only when
    the driver names no constraint. Anything else stays unmapped:
    a refusal must name the rule it refused, not claim a name clash for a
    foreign key that went missing.
    """
    constraint = constraint_name_of(exc)
    if constraint is not None:
        # The driver named the rule; the message also quotes the row's values,
        # so a value spelling another constraint's name must not match here.
        return constraint in names
    message = str(exc.orig)
    return any(name in message for name in names)


def in_ids(column: Any, ids: Iterable[Any]) -> ColumnElement[bool]:
    """``column IN ids``, sent as one array parameter rather than one per id.

    ``column.in_(ids)`` binds every element on its own, and the driver
    refuses a statement of more than 32 767 parameters: a list built from an
    organization's products or locations crossed that at a hundred thousand
    products and the screen answered 500. ``= ANY(:ids)`` is one parameter
    whatever the list holds, and PostgreSQL plans it as it plans the ``IN``
    list. Use it where the list grows with the organization.
    """
    return cast(
        ColumnElement[bool], column == any_(literal(list(ids), ARRAY(column.type)))
    )


#: How far a list that can grow with the organization counts its rows before
#: it says "more than this". Counting every row of a large organization on
#: every page was most of the page's time; ten thousand rows count in a few
#: milliseconds and are two hundred pages of fifty, more than anyone pages
#: through — past them a reader searches or filters. ``PaginatedResponse``
#: carries the cap as ``total_capped``.
LIST_COUNT_CAP = 10_000


def count_window(offset: int, limit: int, cap: int) -> int:
    """How many rows a capped count covers: the cap, or as far as the page reaches.

    A page past the cap still has to know whether another page follows, so
    the window grows with it.
    """
    return max(cap, offset + limit)


def _count_stmt(stmt: Select[Any], window: int | None = None) -> Select[tuple[int]]:
    """Build a total-count statement from a row query.

    The original query is wrapped as a subquery so ORDER BY / LIMIT / OFFSET
    applied on it do not leak into the count. With a *window* the count stops
    one row past it: a count above the window means "more than the window".
    """
    rows = stmt.order_by(None).limit(None).offset(None)
    if window is not None:
        rows = rows.limit(window + 1)
    return select(func.count()).select_from(rows.subquery())


async def acquire_advisory_lock(db: AsyncSession, key: str) -> None:
    """Take a transaction-scoped PostgreSQL advisory lock keyed by *key*.

    The lock is hashed with ``hashtext`` so any string works as a key; it
    releases automatically at COMMIT or ROLLBACK. Use it to serialise a
    read-then-write sequence that a unique index cannot guard (see the
    ``toctou_risk_baseline.txt`` entries for the cases where it is skipped
    deliberately).

    Async only, on purpose. ``db_utils`` already registers two sync/async
    twins in ``app/core/sync_async_twin_baseline.txt``; adding an
    ``acquire_advisory_lock`` / ``_async`` pair here would emit a blocking
    architecture-lint error. Every one of the 23 call sites this replaces was
    already async, so there is nothing to serve.

    ``services/auth_service.py`` still passes a literal integer to
    ``pg_advisory_xact_lock`` directly. That one is a fixed magic number for a
    single critical section, so it is stable across processes; a key derived
    from ``hash()`` is not, and the two call sites that did that no longer
    exist.
    """
    await db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:k))'), {'k': key})


#: Where ``after_commit`` keeps the work it defers, in the session's ``info``.
_AFTER_COMMIT = '_after_commit_callbacks'


def after_commit(db: AsyncSession, callback: Callable[[], Awaitable[None]]) -> None:
    """Run *callback* once the caller's transaction has committed.

    For an effect no rollback can call back -- a mail queued in its own
    transaction, a push to a browser -- raised by a service that flushes and
    leaves the commit to its caller. The request-scoped session runs it right
    after its commit (``dispatch_committed_events``); a rollback drops it, so
    an operation that is refused tells nobody about what it never wrote. A
    savepoint's rollback drops only what was deferred inside the savepoint.

    Best-effort, like the notices it carries: a callback that raises is
    logged and the commit stands.
    """
    db.info.setdefault(_AFTER_COMMIT, []).append(callback)


async def run_after_commit(db: AsyncSession) -> bool:
    """Run the work ``after_commit`` deferred; True when there was any."""
    callbacks: list[Callable[[], Awaitable[None]]] = db.info.pop(_AFTER_COMMIT, [])
    for callback in callbacks:
        try:
            await callback()
        except Exception:  # the commit already stands; a notice cannot undo it
            logger.exception('[db] after-commit callback %r failed', callback)
    return bool(callbacks)


#: The ``session.info`` lists that live and die with the transaction that
#: filled them: ``after_commit`` work and, from the event bus, the TESTING
#: event buffer.
_TRANSACTION_SCOPED_INFO = [_AFTER_COMMIT]

#: Where each open savepoint keeps the lengths those lists had when it began.
_SAVEPOINT_MARKS = '_savepoint_marks'


def transaction_scoped_info(key: str) -> None:
    """Make the list in ``session.info[key]`` follow the transaction.

    A rollback empties it; a savepoint's rollback cuts it back to where it
    stood when the savepoint began, so what the caller queued before asking
    survives a service that undid only its own part.
    """
    _TRANSACTION_SCOPED_INFO.append(key)


def _mark_savepoint(session: Session, transaction: SessionTransaction) -> None:
    if transaction.nested:
        session.info.setdefault(_SAVEPOINT_MARKS, {})[transaction] = {
            key: len(session.info.get(key, ())) for key in _TRANSACTION_SCOPED_INFO
        }


def _forget_savepoint(session: Session, transaction: SessionTransaction) -> None:
    if transaction.nested:
        session.info.get(_SAVEPOINT_MARKS, {}).pop(transaction, None)


def _forget_rolled_back(session: Session) -> None:
    # During the event the savepoint being rolled back is still the session's
    # innermost one; with none, the whole transaction went.
    savepoint = session.get_nested_transaction()
    marks = session.info.get(_SAVEPOINT_MARKS, {}).get(savepoint)
    for key in _TRANSACTION_SCOPED_INFO:
        if marks is None:
            session.info.pop(key, None)
        else:
            del session.info.get(key, [])[marks[key] :]


sa_event.listen(Session, 'after_transaction_create', _mark_savepoint)
sa_event.listen(Session, 'after_transaction_end', _forget_savepoint)
sa_event.listen(Session, 'after_rollback', _forget_rolled_back)


async def paginate_async(  # noqa: UP047
    db: AsyncSession,
    stmt: Select[tuple[T]],
    *,
    limit: int = 100,
    offset: int = 0,
    count_cap: int | None = None,
) -> tuple[list[T], int]:
    """Execute a paginated query: returns (items, total_count).

    ``stmt`` must be a SQLAlchemy ``select()`` of a single entity/column;
    ``total_count`` is computed independently of ``limit``/``offset``.

    With ``count_cap`` the count stops past ``count_window``: a total above
    the window means the list holds more, and ``PaginatedResponse.from_slice``
    given the same cap reports it that way.

    A hand-written ``.offset()`` beside this is one of four things: a keyset
    page (``after``), a literal ``offset`` the planner must see as a constant,
    a list that returns rows only (its caller counts elsewhere or not at all),
    or a multi-column select this single-entity wrapper does not fit.
    """
    window = count_window(offset, limit, count_cap) if count_cap else None
    total = (await db.scalar(_count_stmt(stmt, window))) or 0
    result = await db.execute(stmt.offset(offset).limit(limit))
    return list(result.scalars().all()), total


def paginate(  # noqa: UP047
    db: Session,
    stmt: Select[tuple[T]],
    *,
    limit: int = 100,
    offset: int = 0,
    count_cap: int | None = None,
) -> tuple[list[T], int]:
    """Sync variant of ``paginate_async``."""
    window = count_window(offset, limit, count_cap) if count_cap else None
    total = db.scalar(_count_stmt(stmt, window)) or 0
    result = db.execute(stmt.offset(offset).limit(limit))
    return list(result.scalars().all()), total


def _require_org_id(org_id: UUID | None) -> UUID:
    """Reject a missing organization instead of querying for org-less rows.

    ``organization_id == None`` renders as ``IS NULL`` in SQL, so a caller
    that lost its tenant on the way here would read system/global rows
    instead of being refused. The helper is documented in
    ``backend/AGENTS.md`` as the canonical org-owned fetch; its contract is
    "no organization, no resource". Distinct from ``require_org()``, which
    answers a different question (is there a tenant in the request context)
    with a 403.
    """
    if org_id is None:
        raise RuntimeError(
            'get_org_owned_or_404 requires an organization id; None would '
            'query for rows with organization_id IS NULL. Resolve the tenant '
            'first (require_org), or query global rows explicitly.'
        )
    return org_id


async def get_org_owned_or_404_async(  # noqa: UP047
    db: AsyncSession,
    model_cls: type[M],
    item_id: UUID,
    org_id: UUID,
    *,
    resource: str | None = None,
    lang: Language | None = None,
) -> M:
    """Fetch a row by ``(id, organization_id)`` or raise ``NotFoundException``.

    ``resource`` names the i18n key ``<resource>_not_found`` used for the
    error message. When omitted it is derived from the table name
    (``'partners'`` -> ``'partner'``); known irregular plurals such as
    ``'categories'`` -> ``'category'`` are mapped automatically.
    ``lang`` selects the error-message language; left out, the refusal
    speaks the request's (see ``NotFoundException``).

    Raises ``RuntimeError`` when ``org_id`` is ``None`` -- see
    :func:`_require_org_id`.
    """
    org_id = _require_org_id(org_id)
    result = await db.execute(
        select(model_cls).where(
            model_cls.id == item_id,
            model_cls.organization_id == org_id,
        )
    )
    obj = result.scalar_one_or_none()
    if obj is None:
        raise NotFoundException(
            resource or _resource_name_from_table(model_cls.__tablename__), lang
        )
    return cast(M, obj)


def get_org_owned_or_404(  # noqa: UP047
    db: Session,
    model_cls: type[M],
    item_id: UUID,
    org_id: UUID,
    *,
    resource: str | None = None,
    lang: Language | None = None,
) -> M:
    """Sync variant of ``get_org_owned_or_404_async``."""
    org_id = _require_org_id(org_id)
    result = db.execute(
        select(model_cls).where(
            model_cls.id == item_id,
            model_cls.organization_id == org_id,
        )
    )
    obj = result.scalar_one_or_none()
    if obj is None:
        raise NotFoundException(
            resource or _resource_name_from_table(model_cls.__tablename__), lang
        )
    return cast(M, obj)
