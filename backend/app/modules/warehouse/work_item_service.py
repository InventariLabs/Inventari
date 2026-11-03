"""One source of work for the floor: what needs doing, not what is confirmed.

To do used to be the list of confirmed documents. The work a small warehouse
has is wider than its documents: a delivery that has been ordered but has no
receipt yet, a production run planned for today, a document that waits for
this person's approval, a count that has fallen due, goods waiting in a
receiving area to be put away, and the odd job nobody would write a
document for. Each of those is read here from the record that
asks for it, at request time, as a ``WorkItemSchema``.

A task keeps no state of its own. Starting a session moves its document to
``in_progress``; posting or cancelling the source removes the task; nothing
here is ticked by hand except a custom task, which has no source to ask. What
cannot be derived lives in ``WorkItemOverlay``: the person a task is for, and
the custom tasks themselves.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    AuditAction,
    AuditTargetType,
    UserContextDTO,
    WorkItemDTO,
    WorkItemQueryDTO,
)
from app.core.exceptions import ConflictException, NotFoundException
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message

from . import document_types as dt
from ._schemas_work_items import (
    WorkItemSchema,
    WorkItemsSection,
    WorkItemState,
    WorkItemView,
)
from .backorder_cover_service import StockCover, backorder_cover_async
from .document_todo_service import completed_documents_async, line_tallies_async
from .models import CUSTOM_SOURCE_KIND, Document, WorkItemOverlay
from .putaway_work_service import putaway_items_async
from .work_item_providers import work_item_providers

logger = get_logger(__name__)

#: A custom task ticked off less than this long ago still counts as done today.
_DONE_WINDOW = timedelta(hours=24)

#: The ``assignee`` filter value for tasks that are for nobody.
UNASSIGNED = 'none'


def _partner_name(doc: Document) -> str | None:
    snapshot: dict[str, Any] = doc.partner_snapshot or {}
    return snapshot.get('name')


def _document_item(
    doc: Document,
    *,
    kind: str,
    date_to: date,
    stage: dict[str, Any] | None = None,
    next_action: str | None = None,
    origin_number: str | None = None,
    scheduled: bool = True,
    done: bool = False,
    tally: tuple[int, int] | None = None,
    stock_cover: StockCover | None = None,
) -> WorkItemSchema:
    """A task made of one document, with the stage the queue derived for it.

    A ``done`` one is a document posted lately: it keeps its sentence and asks
    for nothing more. ``tally`` is its lines and the lines done in full,
    counted by the caller (``line_tallies_async``) when the lines were not
    loaded.
    """
    if tally is None:
        tally = (
            len(doc.lines),
            sum(
                1
                for line in doc.lines
                if (line.done_quantity or 0) >= line.expected_quantity
            ),
        )
    stage = stage or {}
    due = (doc.scheduled_date or doc.created_at.date()) if scheduled else None
    inbound = dt.is_receipt(doc.type)
    place = doc.target_location if inbound else doc.source_location
    return WorkItemSchema(
        key=f'document:{doc.id}:{kind}',
        kind=kind,
        state='done'
        if done
        else 'todo'
        if stage.get('work_stage', 'to_start') == 'to_start'
        else 'in_progress',
        source_kind='document',
        source_id=doc.id,
        due_date=due,
        overdue=not done and due is not None and due < date_to,
        next_action=None if done else stage.get('next_action', next_action),
        subject=_partner_name(doc),
        number=doc.number,
        count=tally[0],
        place=place.name if place else None,
        document_type=doc.type,
        document_status=doc.status,
        stage_holder_name=stage.get('stage_holder_name'),
        origin_number=origin_number,
        stock_cover=stock_cover,
        lines_done=tally[1],
        done_at=doc.completed_at if done else None,
    )


def _provided_item(row: WorkItemDTO, date_to: date) -> WorkItemSchema:
    """A task a module contributed, as the list shows it."""
    return WorkItemSchema(
        key=f'{row.source_kind}:{row.source_id}',
        kind=row.kind,
        state=row.state,
        source_kind=row.source_kind,
        source_id=row.source_id,
        due_date=row.due_date,
        overdue=row.state != 'done'
        and row.due_date is not None
        and row.due_date < date_to,
        next_action=row.next_action,
        subject=row.subject,
        number=row.number,
        count=row.count,
        unit=row.unit,
        place=row.place,
        sentence=row.sentence,
        action_label=row.action_label,
        action_href=row.action_href,
        done_at=row.done_at,
    )


def _custom_item(row: WorkItemOverlay, date_to: date) -> WorkItemSchema:
    return WorkItemSchema(
        key=f'{CUSTOM_SOURCE_KIND}:{row.id}',
        kind='custom',
        state='done' if row.done_at else 'todo',
        source_kind='custom',
        source_id=row.id,
        due_date=row.due_date,
        overdue=row.done_at is None
        and row.due_date is not None
        and row.due_date < date_to,
        assignee_id=row.assignee_id,
        subject=row.title,
        done_at=row.done_at,
    )


async def _provided_items_async(
    db: AsyncSession,
    org_id: UUID,
    user: UserContextDTO,
    *,
    date_to: date,
    limit: int,
    done_since: datetime | None,
) -> tuple[list[WorkItemSchema], int]:
    """The tasks the other modules contribute: orders, production, counts, ...

    A provider is asked only while its module is enabled for the reader's
    organization, so a module that is switched off takes its tasks with it.
    One that fails is logged and skipped inside a savepoint, so the rest of
    the list still arrives and the request's transaction stays usable.
    """
    query = WorkItemQueryDTO(
        date_to=date_to, limit=limit, user_id=user.id, done_since=done_since
    )
    items: list[WorkItemSchema] = []
    total = 0
    for module, provider in work_item_providers().items():
        # The organization's own rule: an empty list means every default
        # module, which a raw membership test would read as none.
        if not await core_api.organizations.is_module_enabled_async(db, org_id, module):
            continue
        try:
            async with db.begin_nested():
                rows, count = await provider(db, org_id, query)
        except Exception:  # noqa: BLE001 — a module's bug must not empty To do
            logger.warning('[work-items] provider of %s failed', module, exc_info=True)
            continue
        items += [_provided_item(row, date_to) for row in rows]
        total += count
    return items, total


async def _overlays_async(
    db: AsyncSession,
    org_id: UUID,
    items: Iterable[WorkItemSchema],
    *,
    done_since: datetime | None,
) -> tuple[dict[tuple[str, UUID], WorkItemOverlay], list[WorkItemOverlay]]:
    """The assignees of the derived tasks, and the custom tasks to show."""
    keys = [(item.source_kind, item.source_id) for item in items]
    custom_open: ColumnElement[bool] = WorkItemOverlay.done_at.is_(None)
    if done_since is not None:
        custom_open = or_(custom_open, WorkItemOverlay.done_at >= done_since)
    conditions = [
        and_(
            WorkItemOverlay.source_kind == CUSTOM_SOURCE_KIND,
            custom_open,
        )
    ]
    if keys:
        conditions.append(
            and_(
                WorkItemOverlay.source_kind != CUSTOM_SOURCE_KIND,
                WorkItemOverlay.source_id.in_([source_id for _, source_id in keys]),
            )
        )
    rows = (
        (
            await db.execute(
                select(WorkItemOverlay)
                .where(WorkItemOverlay.organization_id == org_id, or_(*conditions))
                .order_by(WorkItemOverlay.created_at)
            )
        )
        .scalars()
        .all()
    )
    derived = {
        (row.source_kind, row.source_id): row
        for row in rows
        if row.source_kind != CUSTOM_SOURCE_KIND and row.source_id is not None
    }
    return derived, [row for row in rows if row.source_kind == CUSTOM_SOURCE_KIND]


def _in_view(
    item: WorkItemSchema,
    view: WorkItemView,
    user_id: UUID,
    state: WorkItemState | None,
    assignee: str | None,
) -> bool:
    if state is not None and item.state != state:
        return False
    if assignee == UNASSIGNED and item.assignee_id is not None:
        return False
    if assignee not in (None, UNASSIGNED) and str(item.assignee_id) != assignee:
        return False
    if view == 'mine':
        return item.assignee_id == user_id
    return view == 'all' or item.overdue


#: Tasks that wait for somebody's call rather than for a day.
_DECISION_KINDS = frozenset({'approve', 'backorder'})


def _order(item: WorkItemSchema) -> tuple[Any, ...]:
    """Decisions, then the overdue, then by day, then the undated.

    A task with no day has nothing that falls due, so it comes after every
    dated one instead of ahead of the overdue; only a decision, which waits
    for a person, leads without a day. Among the decisions a backorder whose
    stock has arrived goes first: it is the one that can be issued now.
    """
    if item.state == 'done':
        # What was finished lately, the latest first; the sources each hand
        # theirs over newest first, but their lists are merged here.
        done_at = item.done_at.timestamp() if item.done_at else 0.0
        return (True, -done_at, item.key)
    return (
        False,
        item.kind not in _DECISION_KINDS,
        item.stock_cover != 'full',
        item.due_date is None,
        item.due_date or date.min,
        item.key,
    )


async def assemble_work_items_async(
    db: AsyncSession,
    org_id: UUID,
    user: UserContextDTO,
    *,
    date_to: date,
    limit: int,
    reach: int | None = None,
    include_done: bool = False,
    done_since: datetime | None = None,
    view: WorkItemView = 'all',
    state: WorkItemState | None = None,
    assignee: str | None = None,
    inbound: list[Document],
    outbound: list[Document],
    stage_updates: dict[UUID, dict[str, Any]],
    backorders: list[Document],
    approvals: list[Document],
    documents_total: int,
    location_ids: list[UUID] | None = None,
) -> WorkItemsSection:
    """Every task the reader can see, soonest first.

    The caller has already read the documents (the same rows the queue's two
    lists are made of); the rest of the sources are read here. ``limit`` caps
    the merged list and ``reach`` (``limit`` when not given) each source, and
    ``total`` is the server's count
    of every task there is, so a longer queue says so. ``documents_total`` is
    the number of tasks the documents the caller read stand for in all.

    ``view``, ``state`` and ``assignee`` (a user id, or ``UNASSIGNED``) narrow
    the list before it is cut to ``limit``, so a filter looks through
    everything the sources returned and not just the first page; its
    ``total`` is the number of tasks that passed it. With ``include_done``,
    the work posted or recorded in the last day is listed as ``done`` after
    the open tasks; ``done_since`` shortens that to the reader's own day.
    ``location_ids`` (a warehouse and the places under it) keeps the putaway
    and posted-document tasks that stand in them; the sources the caller read
    were narrowed the same way.
    """
    window_start = datetime.now(UTC) - _DONE_WINDOW
    if done_since is not None:
        done_since = max(done_since, window_start)
    elif include_done:
        done_since = window_start
    cover = await backorder_cover_async(db, org_id, backorders)
    items = [
        *(
            _document_item(
                doc,
                kind='receive',
                date_to=date_to,
                stage=stage_updates.get(doc.id),
            )
            for doc in inbound
        ),
        *(
            _document_item(
                doc,
                kind='ship',
                date_to=date_to,
                stage=stage_updates.get(doc.id),
            )
            for doc in outbound
        ),
        *(
            _document_item(
                doc,
                kind='backorder',
                date_to=date_to,
                next_action='open_draft',
                origin_number=getattr(doc, 'backorder_of_number', None),
                scheduled=False,
                stock_cover=cover.get(doc.id),
            )
            for doc in backorders
        ),
        *(
            _document_item(
                doc,
                kind='approve',
                date_to=date_to,
                next_action='review_approval',
                scheduled=False,
            )
            for doc in approvals
        ),
    ]
    provided, provided_total = await _provided_items_async(
        db, org_id, user, date_to=date_to, limit=reach or limit, done_since=done_since
    )
    items += provided
    putaway, putaway_total = await putaway_items_async(
        db, org_id, date_to=date_to, limit=reach or limit, warehouse_ids=location_ids
    )
    items += putaway
    documents_total += putaway_total
    if done_since is not None:
        posted, posted_total = await completed_documents_async(
            db,
            org_id,
            since=done_since,
            limit=reach or limit,
            location_ids=location_ids,
        )
        tallies = await line_tallies_async(db, [doc.id for doc in posted])
        items += [
            _document_item(
                doc,
                kind='receive' if dt.is_receipt(doc.type) else 'ship',
                date_to=date_to,
                done=True,
                tally=tallies.get(doc.id, (0, 0)),
            )
            for doc in posted
        ]
        documents_total += posted_total

    derived, custom = await _overlays_async(db, org_id, items, done_since=done_since)
    items += [_custom_item(row, date_to) for row in custom]

    member_names = {
        member.id: member.full_name or member.email
        for member in await core_api.users.list_org_members_async(db, org_id)
    }
    for item in items:
        overlay = derived.get((item.source_kind, item.source_id))
        assignee_id = overlay.assignee_id if overlay else item.assignee_id
        item.assignee_id = assignee_id
        item.assignee_name = member_names.get(assignee_id) if assignee_id else None

    items.sort(key=_order)
    if view == 'all' and state is None and assignee is None:
        return WorkItemsSection(
            items=items[:limit],
            total=documents_total + provided_total + len(custom),
        )
    narrowed = [
        item for item in items if _in_view(item, view, user.id, state, assignee)
    ]
    return WorkItemsSection(items=narrowed[:limit], total=len(narrowed))


async def _journal_async(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    action: AuditAction,
    target_id: UUID,
    snapshot: dict[str, Any],
) -> None:
    """One row in the organization log: who did what to which task."""
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=action,
        target_type=AuditTargetType.WORK_ITEM,
        target_id=target_id,
        snapshot=snapshot,
    )


def _already_taken_error() -> ConflictException:
    """The refusal of a claim: somebody else was given the task first."""
    return ConflictException(
        'WORK_ITEM_TAKEN',
        get_error_message('work_item_taken', get_current_lang()),
    )


async def _claim_unassigned_async(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    *,
    source_kind: str,
    source_id: UUID,
    assignee_id: UUID | None,
) -> None:
    """Give a task to ``assignee_id`` only while nobody else holds it.

    One statement, so two people tapping the same task cannot both win: the
    overlay row is inserted when there is none and updated when it is still
    nobody's, and the conflict branch leaves another person's holder untouched.
    A conflict that the update's own condition refused returns no row, which is
    how the caller learns the task was taken; a claim by the person who already
    holds it is a no-op success, so a double tap is harmless.
    """
    table = WorkItemOverlay.__table__
    claimed = (
        await db.execute(
            pg_insert(WorkItemOverlay)
            .values(
                organization_id=org_id,
                source_kind=source_kind,
                source_id=source_id,
                assignee_id=assignee_id,
                created_by=user_id,
            )
            .on_conflict_do_update(
                index_elements=['organization_id', 'source_kind', 'source_id'],
                index_where=table.c.source_id.isnot(None),
                set_={'assignee_id': assignee_id},
                where=or_(
                    table.c.assignee_id.is_(None),
                    table.c.assignee_id == assignee_id,
                ),
            )
            .returning(WorkItemOverlay.id)
        )
    ).scalar_one_or_none()
    if claimed is None:
        raise _already_taken_error()


async def assign_work_item_async(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    *,
    source_kind: str,
    source_id: UUID,
    assignee_id: UUID | None,
    only_if_unassigned: bool = False,
) -> None:
    """Give a task to a person, or take it back to nobody.

    A custom task carries its own assignee; for any other the overlay row is
    made on first use. The person must belong to this organization.

    ``only_if_unassigned`` turns the write into a claim: it lands only while
    the task has nobody, and a task somebody else took first is refused with
    a conflict instead of being taken from them. An ordinary assignment keeps
    its deliberate reassignment, the desktop's choosing of a person.
    """
    lang = get_current_lang()
    if (
        assignee_id is not None
        and await core_api.users.get_async(db, org_id, assignee_id) is None
    ):
        raise NotFoundException('user', lang)
    if source_kind == CUSTOM_SOURCE_KIND:
        if only_if_unassigned:
            # A custom task is its own overlay row, so the claim is one
            # conditional UPDATE: the row decides between two people tapping
            # it at once, not a holder either of them read a moment earlier.
            claimed = (
                await db.execute(
                    update(WorkItemOverlay)
                    .where(
                        WorkItemOverlay.id == source_id,
                        WorkItemOverlay.organization_id == org_id,
                        WorkItemOverlay.source_kind == CUSTOM_SOURCE_KIND,
                        or_(
                            WorkItemOverlay.assignee_id.is_(None),
                            WorkItemOverlay.assignee_id == assignee_id,
                        ),
                    )
                    .values(assignee_id=assignee_id)
                    .returning(WorkItemOverlay.id)
                )
            ).scalar_one_or_none()
            if claimed is None:
                # Which refusal it is: no such task, or one somebody took
                # while this person was looking at it.
                await get_custom_item_async(db, org_id, source_id)
                raise _already_taken_error()
        else:
            row = await get_custom_item_async(db, org_id, source_id)
            row.assignee_id = assignee_id
            await db.flush()
        await _journal_async(
            db,
            org_id,
            user_id,
            AuditAction.UPDATE,
            source_id,
            {'source_kind': source_kind, 'assignee_id': str(assignee_id or '')},
        )
        return
    if only_if_unassigned:
        await _claim_unassigned_async(
            db,
            org_id,
            user_id,
            source_kind=source_kind,
            source_id=source_id,
            assignee_id=assignee_id,
        )
        await _journal_async(
            db,
            org_id,
            user_id,
            AuditAction.UPDATE,
            source_id,
            {'source_kind': source_kind, 'assignee_id': str(assignee_id or '')},
        )
        return
    existing = (
        await db.execute(
            select(WorkItemOverlay)
            .where(
                WorkItemOverlay.organization_id == org_id,
                WorkItemOverlay.source_kind == source_kind,
                WorkItemOverlay.source_id == source_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.assignee_id = assignee_id
    else:
        db.add(
            WorkItemOverlay(
                organization_id=org_id,
                source_kind=source_kind,
                source_id=source_id,
                assignee_id=assignee_id,
                created_by=user_id,
            )
        )
    await db.flush()
    await _journal_async(
        db,
        org_id,
        user_id,
        AuditAction.UPDATE,
        source_id,
        {'source_kind': source_kind, 'assignee_id': str(assignee_id or '')},
    )


async def get_custom_item_async(
    db: AsyncSession, org_id: UUID, item_id: UUID
) -> WorkItemOverlay:
    row = (
        await db.execute(
            select(WorkItemOverlay).where(
                WorkItemOverlay.id == item_id,
                WorkItemOverlay.organization_id == org_id,
                WorkItemOverlay.source_kind == CUSTOM_SOURCE_KIND,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundException('work_item', get_current_lang())
    return row


async def create_custom_item_async(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    *,
    title: str,
    assignee_id: UUID | None,
    due_date: date | None,
) -> WorkItemOverlay:
    if (
        assignee_id is not None
        and await core_api.users.get_async(db, org_id, assignee_id) is None
    ):
        raise NotFoundException('user', get_current_lang())
    row = WorkItemOverlay(
        organization_id=org_id,
        source_kind=CUSTOM_SOURCE_KIND,
        title=title,
        assignee_id=assignee_id,
        due_date=due_date,
        created_by=user_id,
    )
    db.add(row)
    await db.flush()
    await _journal_async(
        db,
        org_id,
        user_id,
        AuditAction.CREATE,
        row.id,
        {
            'title': title,
            'assignee_id': str(assignee_id or ''),
            'due_date': due_date.isoformat() if due_date else '',
        },
    )
    return row


async def set_custom_item_done_async(
    db: AsyncSession, org_id: UUID, user_id: UUID, item_id: UUID, *, done: bool
) -> WorkItemOverlay:
    row = await get_custom_item_async(db, org_id, item_id)
    row.done_at = datetime.now(UTC) if done else None
    await db.flush()
    await _journal_async(
        db,
        org_id,
        user_id,
        AuditAction.UPDATE,
        row.id,
        {'title': row.title, 'done': done},
    )
    return row


async def delete_custom_item_async(
    db: AsyncSession, org_id: UUID, user_id: UUID, item_id: UUID
) -> None:
    row = await get_custom_item_async(db, org_id, item_id)
    snapshot = {'title': row.title, 'done': row.done_at is not None}
    await db.delete(row)
    await db.flush()
    await _journal_async(
        db, org_id, user_id, AuditAction.HARD_DELETE, item_id, snapshot
    )
