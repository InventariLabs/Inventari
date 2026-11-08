"""The organization journal: one immutable row per state-changing act.

Two ledgers answer two different questions, and a write belongs in
exactly one of them:

- ``audit_log`` (this service) — *what was done to the organization's
  records, by whom, when, with what values.* One row per act on any record
  an organization owns: items, locations, categories, documents, members,
  settings. The screen reads it, so a row must name its actor and carry a
  snapshot the Detail column can speak — ``before``/``after`` for changes,
  flat fields for creates, a ``reason`` where the caller was asked for one.

- ``item_history`` (``services/items/history.py``) — *the item's own
  movement ledger.* Finer-grained than the journal by design: document
  links, lot breakdowns, same-location no-ops. A state-changing act on an
  item normally writes both — history for the item's story, the journal
  for the organization's — but history alone is never enough for an act
  the organization would want to reconstruct.

 Writing here also invalidates the organization's analytics
query cache: every state-changing act funnels through this journal, so a
journaled act is the signal that the cached overview, rotation and
forecast read-models no longer describe the rows. Writes that do not
journal — bulk item updates — invalidate explicitly.

Not every entry is that signal. The cached read-models are defined over
stock, catalogue and custody facts, and an entry about something none of
them reads — who may access the organization, or somebody's own working
note — invalidates nothing but still pays for the invalidation. Which
targets those are is decided in :data:`_ANALYTICS_NEUTRAL_TARGETS` and
recorded in ``core/public_api/queries.py``, next to the models whose
freshness it trades away.
"""

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import ColumnElement, Row, ScalarSelect, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_actor import ACTOR_KEY, ACTOR_TYPE_API_KEY, current_actor
from app.core.cache import cache_invalidate_org_queries
from app.core.contracts import AuditAction, AuditTargetType
from app.core.keyset import read_page_after
from app.core.logging import get_logger
from app.core.posting_batch import current_batch
from app.core.utils import isoformat_or_none
from app.models.audit_log import AuditLog

logger = get_logger(__name__)

#: Journal targets whose entries cannot move a cached analytics read-model,
#: and therefore do not invalidate it.
#:
#: Every cached read-model is defined over stock, catalogue or custody facts:
#: the overview counts items and their locations, rotation reads the movement
#: ledger, the forecast reads purchase history, and the equipment fleet
#: valuation reads items. An entry about *access* — who may do things in this
#: organization, or which door data leaves by — changes none of those rows,
#: and an entry about somebody's own working note is a deletion of a row no
#: read-model ever reads (see :class:`AuditTargetType`). Both were paying a
#: full invalidation for a cache they cannot have made stale.
#:
#: Deliberately *not* here: ``module`` (a toggle changes which rows the stats
#: count) and ``organization`` (its currency decides what a valuation may sum).
#: Both are access-adjacent and both are read.
_ANALYTICS_NEUTRAL_TARGETS: frozenset[str] = frozenset(
    target.value
    for target in (
        # Access — rights, invitations, keys, delivery channels.
        AuditTargetType.ORG_MEMBER,
        AuditTargetType.ROLE,
        AuditTargetType.INVITATION,
        AuditTargetType.API_KEY,
        AuditTargetType.WEBHOOK_ENDPOINT,
        # Working notes — the only entries these ever write are deletions.
        AuditTargetType.RECIPE,
        AuditTargetType.MEAL_PLAN,
        AuditTargetType.SHOPPING_LIST,
    )
)


def _entry_changes_analytics(target_type: str) -> bool:
    """Whether a journal entry about *target_type* can stale a cached answer.

    Compared against the enum's string values, because ``target_type``
    arrives as a plain ``str`` from call sites older than
    :class:`AuditTargetType` as well as from the enum — both spellings have
    to meet the same list.
    """
    return target_type not in _ANALYTICS_NEUTRAL_TARGETS


async def log_action_async(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID | None,
    action: AuditAction,
    target_type: str,
    target_id: uuid.UUID,
    snapshot: dict | None = None,
    reason: str | None = None,
    meta_data: dict | None = None,
) -> AuditLog:
    """Persist a single AuditLog row inside the caller's transaction.

    The caller owns the transaction: ``db.add()`` + ``db.flush()`` push the
    row to the DB but commit is the caller's responsibility (typically the
    outer FastAPI ``get_async_db`` dependency that commits at request end).
    Keeping the commit with the caller is what makes
    ``approve_stage`` + ``confirm_after_approval`` atomic.

    For UPDATE actions the convention is to pass a ``snapshot`` with keys
    ``before`` and ``after`` (each a dict of the changed fields). For
    SOFT_DELETE the convention is to capture a ``snapshot`` of the row
    and put the deletion ``reason`` in the ``reason`` column.

    When the request authenticated with an API key, the entry gains
    ``meta_data['actor'] = {'type': 'api_key', 'key_prefix': …}`` — the key,
    not only its owner, is what the journal must be able to name. The rest of
    ``meta_data`` is the caller's and is kept: the actor is added to it, never
    in place of it.

    The snapshot is passed through :func:`audit_value`, so a ``Decimal`` in it
    is written as its exact digits whatever the caller built it from; a
    caller that wants to *compare* two shapes first keeps the ``Decimal``s
    and lets this function write them down.
    """
    actor = current_actor()
    if actor is not None:
        meta_data = {**(meta_data or {}), ACTOR_KEY: actor}
    entry = AuditLog(
        organization_id=organization_id,
        user_id=user_id,
        action=action.value,
        target_type=target_type,
        target_id=target_id,
        snapshot=audit_value(snapshot),
        reason=reason,
        meta_data=meta_data,
    )
    # A journaled act is a state change, so the analytics read-models the
    # org's cached queries answer from may be stale now — unless the entry is
    # about a target those models do not read. Fired before the caller
    # commits: a rolled-back transaction only cost one recomputation, never a
    # wrong answer. The function swallows its own failures — a cache problem
    # must never fail a write.
    batch = current_batch(db)
    if batch is not None:
        # A posting writes its journal rows together when it ends, and
        # stales the caches once, not once per row.
        entry.id = uuid.uuid4()
        batch.add(entry)
        if _entry_changes_analytics(target_type):
            batch.organizations_changed.add(organization_id)
    else:
        db.add(entry)
        await db.flush()
        if _entry_changes_analytics(target_type):
            await cache_invalidate_org_queries(organization_id)
    logger.info(
        'AuditLog: action=%s target=%s/%s org=%s user=%s reason=%s',
        entry.action,
        entry.target_type,
        entry.target_id,
        entry.organization_id,
        entry.user_id,
        entry.reason,
    )
    return entry


async def log_purge_async(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID | None,
    target_type: str,
    target_id: uuid.UUID,
    snapshot: dict | None = None,
    reason: str | None = None,
    meta_data: dict | None = None,
) -> AuditLog:
    """Backward-compat wrapper for the legacy PURGE-only audit writer.

    Deprecated: prefer ``log_action_async`` with ``action=AuditAction.PURGE``.
    Kept so existing callers (item._lifecycle.purge_item, the audit-log
    integration tests) do not need to change.
    """
    return await log_action_async(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action=AuditAction.PURGE,
        target_type=target_type,
        target_id=target_id,
        snapshot=snapshot,
        reason=reason,
        meta_data=meta_data,
    )


def audit_value(value):
    """Serialise a field value **for the record**.

    Snapshots live in a JSONB column and are rendered by the Detail column,
    so a UUID becomes its string, a date its ISO form, an enum its value,
    and a container is walked rather than handed over as a Python object
    the encoder would refuse.

    A ``Decimal`` -- and a ``float``, by its shortest round-trip digits --
    becomes its **exact digits as a string**, in plain notation: ``1E-7``
    is not a shape anybody typed or the screen reads. The journal is
    the account of what the numbers were, and a float is a less precise copy
    of the data it describes -- the same rule the quantity path and
    ``docs/subsystems/AUDIT.md`` state. Use :func:`audit_key` to decide
    whether a value moved; this one only says what it became.
    """
    return _render(value, decimal=lambda d: format(d, 'f'))


def audit_walk(value):
    """Render a value like :func:`audit_value`, but leave every number a number.

    For a reading that is still to be compared before it is written: a
    ``float`` becomes the ``Decimal`` of its shortest digits, a ``Decimal``
    stays, at any depth. ``audit_key`` then answers whether it moved and
    ``audit_value`` says what it became, as for any other entry.
    """
    return _render(value, decimal=lambda d: d)


def audit_key(value):
    """Normalise a field value **for comparison**, never for the record.

    Two records of the same fact must not read as a change. ``Decimal('1.000')``
    and the ``1`` that came up from the form are the same quantity written
    twice, and comparing their exact digits makes them a change every time
    the form is submitted -- which is how the log filled with rows whose
    every field read ``x -> x``. Numbers compare as numbers here; the value
    written down is still :func:`audit_value`'s.

    A text field standing empty and a text field never filled are the same
    fact. The form posts its whole state, so an untouched description arrives
    as ``""`` beside a column holding NULL, and that comparison wrote a line
    reading ``Description: — →`` -- a change of nothing into nothing, which
    on a location move pushed the parent the reader came for off the row.
    """
    if value is None or value == '':
        return None
    return _render(value, decimal=float)


def _render(value, *, decimal):
    """Shared walk. *decimal* decides what a ``Decimal`` becomes."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, Decimal):
        return decimal(value)
    if isinstance(value, float):
        # A float is a number to the audit screen, which prints it at six
        # significant digits. Its shortest round-trip digits (`repr`) are
        # what was typed, so it is treated as the Decimal of those digits:
        # `min_quantity` is a DOUBLE column and its journal entry still reads
        # `1234.567`. `audit_key` gets the same float back from them.
        return decimal(Decimal(repr(value)))
    if isinstance(value, Enum):
        return _render(value.value, decimal=decimal)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _render(v, decimal=decimal) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_render(v, decimal=decimal) for v in value]
    if isinstance(value, int | float | str):
        return value
    if hasattr(value, 'value'):
        return _render(value.value, decimal=decimal)
    return str(value)


def item_to_snapshot(item) -> dict:
    data = {
        'id': str(item.id),
        'name': item.name,
        'brand': item.brand,
        'barcode': item.barcode,
        'quantity': audit_value(item.quantity) if item.quantity is not None else '0',
        'category_id': str(item.category_id) if item.category_id else None,
        'template_id': str(item.template_id) if item.template_id else None,
        'storage_location_id': str(item.storage_location_id)
        if item.storage_location_id
        else None,
        'organization_id': str(item.organization_id),
        'is_deleted': item.is_deleted,
        'deletion_reason': item.deletion_reason,
        'deleted_at': isoformat_or_none(item.deleted_at),
        'serial_number': item.serial_number,
        'meta_data': item.meta_data,
        'created_at': isoformat_or_none(item.created_at),
    }
    return data


async def list_for_org_async(
    db: AsyncSession,
    organization_id: uuid.UUID,
    *,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    actor: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 500,
    offset: int = 0,
    after: tuple[datetime, uuid.UUID] | None = None,
    known_total: int | None = None,
) -> tuple[list[tuple[AuditLog, str | None]], int]:
    """Return audit entries for one organization, newest first.

    Each row is returned as ``(AuditLog, user_email | None)`` — the
    email is resolved via LEFT JOIN on ``users.id`` so the UI can show
    a human-readable label without a second round-trip. ``user_id`` is
    retained on the AuditLog row for precision (email may change, the
    UUID does not).

    Filters compose with AND semantics. Limit caps result size to keep
    large orgs from materialising the entire history. Returns
    ``(rows, total)`` so callers can build a paginated envelope.

    ``actor`` splits a person's work from a key's: ``'api_key'`` keeps the
    entries a key wrote, ``'human'`` every other one — including the rows
    written before keys were named at all, which is why the test is "no actor
    recorded" rather than "the actor is a person". Any other value is ignored
    (the router refuses it before it gets here).

    Pages are asked for by the last row seen (``after``: its instant and id) rather than by a larger ``offset``, so a page deep in a long
    journal costs what the first one does. The count is the whole answer to
    the filters; a caller that took it on the first page passes it back as
    ``known_total`` and it is not taken again. Ties on the instant (one batch
    writes its rows together) are broken by id, so a page boundary never
    repeats or loses an entry.
    """
    from app.models.user import User

    conditions = [AuditLog.organization_id == organization_id]
    if target_type is not None:
        conditions.append(AuditLog.target_type == target_type)
    if target_id is not None:
        conditions.append(AuditLog.target_id == target_id)
    if user_id is not None:
        conditions.append(AuditLog.user_id == user_id)
    # The actor is a key inside the JSON column, so the comparison happens
    # there — the column has no index and none is worth one: the filter
    # narrows an org's own journal, which the org index already bounds.
    recorded_actor = AuditLog.meta_data[ACTOR_KEY]['type'].as_string()
    if actor == ACTOR_TYPE_API_KEY:
        conditions.append(recorded_actor == ACTOR_TYPE_API_KEY)
    elif actor == 'human':
        conditions.append(func.coalesce(recorded_actor, '') != ACTOR_TYPE_API_KEY)
    if since is not None:
        conditions.append(AuditLog.created_at >= since)
    if until is not None:
        conditions.append(AuditLog.created_at <= until)

    # Hand-rolled rather than paginate_async: the page selects two columns
    # (the row and the joined user e-mail), and that helper takes a select()
    # of a single entity and returns scalars.
    total = (
        known_total
        if known_total is not None
        else await db.scalar(
            select(func.count()).select_from(AuditLog).where(*conditions)
        )
    )

    async def read(
        extra: Sequence[ColumnElement[bool]], order: Sequence[Any], size: int
    ) -> list[Row[Any]]:
        result = await db.execute(
            select(AuditLog, User.email.label('user_email'))
            .outerjoin(User, AuditLog.user_id == User.id)
            .where(*conditions, *extra)
            .order_by(*order)
            .offset(0 if after else offset)
            .limit(size)
        )
        return list(result.all())

    if after is None:
        page = await read([], [AuditLog.created_at.desc(), AuditLog.id], limit)
    else:
        page = await read_page_after(
            read,
            moment=AuditLog.created_at,
            row_id=AuditLog.id,
            after=after,
            limit=limit,
        )
    return [(row[0], row[1]) for row in page], total or 0


async def list_target_types_async(
    db: AsyncSession, organization_id: uuid.UUID
) -> list[str]:
    """Distinct ``target_type`` values this organization's log actually holds.

    The screen's filter used to offer three hand-written values, two of which
    belonged to modules the profile does not install, while the things that
    really changed — locations, users, modules — were not on the list at all.
    A filter built from the log cannot offer a choice that matches nothing.

    Read as a loose index scan: the smallest type, then the smallest one above
    it, and so on until none is left. A plain ``SELECT DISTINCT`` reads every
    row of the organization's journal to find a handful of values, on every
    visit to the screen, and the journal only grows; this reads one index
    entry per type, however long the journal is. It leans on
    ``ix_audit_log_org_type_created_at``, whose leading columns are exactly
    the organization and the type.
    """

    # ``ORDER BY target_type, created_at DESC LIMIT 1`` and not ``min()``:
    # the second term makes the order one only ``ix_audit_log_org_type_created_at``
    # can hand over without a sort. ``min()`` is also satisfied by
    # ``ix_audit_log_target``, which starts at the type and not the
    # organization, and where a neighbour's entries sort after this
    # organization's types the planner can pick it and read all of them.
    def first_kind(*conditions: ColumnElement[bool]) -> ScalarSelect[str]:
        return (
            select(AuditLog.target_type)
            .where(AuditLog.organization_id == organization_id, *conditions)
            .order_by(AuditLog.target_type, AuditLog.created_at.desc())
            .limit(1)
            .scalar_subquery()
        )

    kinds = select(first_kind().label('target_type')).cte('kinds', recursive=True)
    next_kind = first_kind(AuditLog.target_type > kinds.c.target_type)
    kinds = kinds.union_all(select(next_kind).where(kinds.c.target_type.is_not(None)))
    result = await db.execute(
        select(kinds.c.target_type)
        .where(kinds.c.target_type.is_not(None))
        .order_by(kinds.c.target_type)
    )
    return list(result.scalars().all())


async def list_for_target_async(
    db: AsyncSession,
    organization_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
    *,
    limit: int = 200,
) -> list[AuditLog]:
    """Return audit entries for one specific (target_type, target_id)."""
    stmt = (
        select(AuditLog)
        .where(AuditLog.organization_id == organization_id)
        .where(AuditLog.target_type == target_type)
        .where(AuditLog.target_id == target_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
