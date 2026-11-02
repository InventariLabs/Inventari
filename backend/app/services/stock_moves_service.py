"""StockMove service — explicit WMS stock movement records.

Backs the public ``core_api.stock_moves`` namespace.  Read/write split:
writes use ``db.add()`` + ``db.flush()`` only (no commit — the caller
commits).  Reads are pure queries.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, tzinfo
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    ColumnElement,
    DateTime,
    Row,
    Uuid,
    bindparam,
    case,
    column,
    exists,
    func,
    literal_column,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.contracts import (
    StockAgeBucketDTO,
    StockAgeEntryDTO,
    StockMoveDTO,
    StockMovePostedGroupDTO,
    StockMoveRowDTO,
)
from app.core.db_utils import in_ids
from app.core.exceptions import ContractViolationError
from app.core.keyset import read_page_after
from app.core.posting_batch import current_batch
from app.models.item import Item
from app.models.location_relocation import LocationRelocation
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove, StockMoveReferenceType, StockMoveState
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.models.user import User
from app.services.storage._queries import descendant_ids_async


async def create_async(
    db: AsyncSession,
    *,
    organization_id: UUID,
    product_template_id: UUID,
    quantity: Decimal,
    from_location_id: UUID | None = None,
    to_location_id: UUID | None = None,
    lot_id: UUID | None = None,
    owner_id: UUID | None = None,
    expiry_date: date | None = None,
    state: str = StockMoveState.DONE,
    reference_type: str | None = None,
    reference_id: UUID | None = None,
    created_by: UUID | None = None,
    completed_at: datetime | None = None,
) -> StockMoveDTO:
    """Async: create a single StockMove and return its DTO.

    No ``db.commit()`` — the caller (router / module handler / a record's
    own posting, ``_post_the_change_async``) is responsible for committing.
    ``owner_id`` says whose goods moved — the organization's own when
    None — and is the one contract every door's movement writes go
    through, so the ledger can say whose goods left.
    """
    if from_location_id is None and to_location_id is None:
        raise ContractViolationError(
            'StockMove requires at least one of from_location_id / to_location_id'
        )
    if quantity is None or quantity <= 0:
        raise ContractViolationError('StockMove quantity must be > 0')

    move = StockMove(
        organization_id=organization_id,
        product_template_id=product_template_id,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        quantity=quantity,
        lot_id=lot_id,
        owner_id=owner_id,
        expiry_date=expiry_date,
        state=state,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by=created_by,
        completed_at=completed_at or datetime.now(UTC),
    )
    db.add(move)
    await db.flush()
    await db.refresh(move)
    return StockMoveDTO.model_validate(move)


async def record_async(
    db: AsyncSession,
    *,
    organization_id: UUID,
    product_template_id: UUID,
    quantity: Decimal,
    from_location_id: UUID | None = None,
    to_location_id: UUID | None = None,
    lot_id: UUID | None = None,
    owner_id: UUID | None = None,
    reference_type: str | None = None,
    reference_id: UUID | None = None,
    created_by: UUID | None = None,
) -> None:
    """Write one movement of the ledger and hand nothing back.

    ``create_async`` for a caller that has no use for the row it wrote, so
    there is no read of it back: inside a posting the movement waits with the
    posting's other appended rows and is written with them, one statement for
    the lot.
    """
    if from_location_id is None and to_location_id is None:
        raise ContractViolationError(
            'StockMove requires at least one of from_location_id / to_location_id'
        )
    if quantity is None or quantity <= 0:
        raise ContractViolationError('StockMove quantity must be > 0')
    move = StockMove(
        id=uuid4(),
        organization_id=organization_id,
        product_template_id=product_template_id,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        quantity=quantity,
        lot_id=lot_id,
        owner_id=owner_id,
        state=StockMoveState.DONE,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by=created_by,
        completed_at=datetime.now(UTC),
    )
    batch = current_batch(db)
    if batch is not None:
        batch.add(move)
        return
    db.add(move)
    await db.flush()


async def get_async(
    db: AsyncSession,
    organization_id: UUID,
    move_id: UUID,
) -> StockMoveDTO | None:
    """Async: get a single StockMove by id, scoped to organization."""
    move = await db.scalar(
        select(StockMove).where(
            StockMove.id == move_id,
            StockMove.organization_id == organization_id,
        )
    )
    if move is None:
        return None
    return StockMoveDTO.model_validate(move)


async def list_by_template_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    *,
    limit: int = 200,
    state: str | None = None,
    since: datetime | None = None,
) -> list[StockMoveDTO]:
    """Async: list moves for one product, newest first.

    ``state`` filters by lifecycle (e.g. only ``done`` for settled history).
    ``since`` filters by ``created_at >= since`` for incremental reads.
    """
    stmt = (
        select(StockMove)
        .where(
            StockMove.organization_id == organization_id,
            StockMove.product_template_id == product_template_id,
        )
        .order_by(StockMove.created_at.desc())
        .limit(limit)
    )
    if state is not None:
        stmt = stmt.where(StockMove.state == state)
    if since is not None:
        stmt = stmt.where(StockMove.created_at >= since)

    rows = (await db.scalars(stmt)).all()
    return [StockMoveDTO.model_validate(r) for r in rows]


#: Direction is not a column — it is the shape of the pair of locations.
#: A row with no origin came in from outside, a row with no destination left,
#: and a row with both moved between two of this organization's own places.
DIRECTION_IN = 'in'
DIRECTION_OUT = 'out'
DIRECTION_INTERNAL = 'internal'


def _moved_at() -> ColumnElement[Any]:
    """When the goods moved, falling back to when the row was written.

    ``completed_at`` is the date the movement belongs to, which is the one a
    report has to cut on: a correction entered today for last week belongs to
    last week. ``created_at`` only stands in for rows that never carried one.
    """
    return func.coalesce(StockMove.completed_at, StockMove.created_at)


def _direction_condition(direction: str) -> ColumnElement[bool]:
    if direction == DIRECTION_IN:
        return StockMove.from_location_id.is_(None)
    if direction == DIRECTION_OUT:
        return StockMove.to_location_id.is_(None)
    if direction == DIRECTION_INTERNAL:
        return StockMove.from_location_id.isnot(None) & StockMove.to_location_id.isnot(
            None
        )
    raise ContractViolationError(
        f'Unknown direction {direction!r}: expected one of '
        f'{DIRECTION_IN}, {DIRECTION_OUT}, {DIRECTION_INTERNAL}'
    )


def _not_a_module_record(organization_id: UUID) -> ColumnElement[bool]:
    """Keep a move unless the records it belongs to are a module's.

    A move that names its record (``reference_type='item'``) is judged by
    that record, the way the lists judge it. Any other move carries only a
    product, so the lists' rule is asked of the product: it stays as soon
    as one record is ordinary, and a product with no record at all has
    nothing a module could claim. Deleted records still count, or a
    retired asset's history would resurface here.
    """
    from app.core.module_ownership import unclaimed_by_a_module
    from app.core.module_scope import get_claimed_context_tags

    claimed_tags = get_claimed_context_tags()
    of_the_record = (
        Item.organization_id == organization_id,
        Item.id == StockMove.reference_id,
    )
    names_a_record = (StockMove.reference_type == 'item') & exists().where(
        *of_the_record
    )
    record_is_ordinary = exists().where(
        *of_the_record, unclaimed_by_a_module(claimed_tags)
    )

    of_the_product = (
        Item.organization_id == organization_id,
        Item.template_id == StockMove.product_template_id,
    )
    has_records = exists().where(*of_the_product)
    has_ordinary_record = exists().where(
        *of_the_product, unclaimed_by_a_module(claimed_tags)
    )
    return case(
        (names_a_record, record_is_ordinary),
        else_=or_(~has_records, has_ordinary_record),
    )


async def _ledger_conditions(
    db: AsyncSession,
    organization_id: UUID,
    *,
    product_template_id: UUID | None,
    location_id: UUID | None,
    lot_id: UUID | None,
    reference_type: str | None,
    reference_id: UUID | None,
    user_id: UUID | None,
    direction: str | None,
    state: str | None,
    since: datetime | None,
    until: datetime | None,
    exclude_module_contexts: bool,
) -> list[ColumnElement[bool]]:
    """The filters a ledger question turns into, shared by both readings."""
    conditions: list[ColumnElement[bool]] = [
        StockMove.organization_id == organization_id
    ]
    if exclude_module_contexts:
        conditions.append(_not_a_module_record(organization_id))
    if product_template_id is not None:
        conditions.append(StockMove.product_template_id == product_template_id)
    if location_id is not None:
        location_ids = [
            location_id,
            *await descendant_ids_async(db, organization_id, location_id),
        ]
        conditions.append(
            or_(
                in_ids(StockMove.from_location_id, location_ids),
                in_ids(StockMove.to_location_id, location_ids),
            )
        )
    if lot_id is not None:
        conditions.append(StockMove.lot_id == lot_id)
    if reference_type is not None:
        conditions.append(StockMove.reference_type == reference_type)
    if reference_id is not None:
        conditions.append(StockMove.reference_id == reference_id)
    if user_id is not None:
        conditions.append(StockMove.created_by == user_id)
    if direction is not None:
        conditions.append(_direction_condition(direction))
    if state is not None:
        conditions.append(StockMove.state == state)
    if since is not None:
        conditions.append(_moved_at() >= since)
    if until is not None:
        conditions.append(_moved_at() <= until)
    return conditions


async def list_for_org_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    product_template_id: UUID | None = None,
    location_id: UUID | None = None,
    lot_id: UUID | None = None,
    reference_type: str | None = None,
    reference_id: UUID | None = None,
    user_id: UUID | None = None,
    direction: str | None = None,
    state: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 200,
    offset: int = 0,
    after: tuple[datetime, UUID] | None = None,
    known_total: int | None = None,
) -> tuple[list[StockMoveDTO], int]:
    """One page of the movement ledger, newest first, plus the full count.

    Every filter is optional and they compose. ``location_id`` answers for the
    whole subtree below it, because a location is a tree and "what happened in
    the warehouse" means its aisles too; a movement matches when either end of
    it stands there.

    The next page is asked for with the last row of this one
    (``after``: the date it sorts by and its id) rather than with a larger ``offset``:
    the cost then stays the size of the page however deep the reader is. The
    count is the whole answer to the filters, so a caller that already holds it
    from the first page passes it back as ``known_total`` and the statement is
    not run again.
    """
    conditions = await _ledger_conditions(
        db,
        organization_id,
        product_template_id=product_template_id,
        location_id=location_id,
        lot_id=lot_id,
        reference_type=reference_type,
        reference_id=reference_id,
        user_id=user_id,
        direction=direction,
        state=state,
        since=since,
        until=until,
        exclude_module_contexts=False,
    )

    total = (
        known_total
        if known_total is not None
        else await db.scalar(
            select(func.count()).select_from(StockMove).where(*conditions)
        )
    )

    async def read(
        extra: Sequence[ColumnElement[bool]], order: Sequence[Any], size: int
    ) -> list[StockMove]:
        rows = await db.scalars(
            select(StockMove)
            .where(*conditions, *extra)
            .order_by(*order)
            .offset(0 if after else offset)
            .limit(size)
        )
        return list(rows.all())

    if after is None:
        # The id breaks ties so a page boundary never shows one row twice and
        # hides another: two movements can share a completion instant.
        page = await read([], [_moved_at().desc(), StockMove.id], limit)
    else:
        page = await read_page_after(
            read, moment=_moved_at(), row_id=StockMove.id, after=after, limit=limit
        )
    return [StockMoveDTO.model_validate(r) for r in page], int(total or 0)


async def list_rows_for_org_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    product_template_id: UUID | None = None,
    location_id: UUID | None = None,
    lot_id: UUID | None = None,
    reference_type: str | None = None,
    reference_id: UUID | None = None,
    user_id: UUID | None = None,
    direction: str | None = None,
    state: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    exclude_module_contexts: bool = False,
    limit: int = 200,
    offset: int = 0,
    after: tuple[datetime, UUID] | None = None,
    known_total: int | None = None,
    count_up_to: int | None = None,
) -> tuple[list[StockMoveRowDTO], int]:
    """The same page, read as sentences rather than as identifiers.

    Pages the same way as :func:`list_for_org_async`: by the last row seen.
    ``count_up_to`` stops the count one row past it: a total above it means
    the ledger holds more (``db_utils.LIST_COUNT_CAP``). Counting a month of
    a large warehouse's movements on every first page was most of the page.

    The names travel with the rows in one statement: resolving them per row
    would cost five lookups a row, and a page holds up to five hundred. Every
    join is an outer one — a movement need not have an origin, a batch or an
    author, and a row missing one of those is still a row.
    """
    conditions = await _ledger_conditions(
        db,
        organization_id,
        product_template_id=product_template_id,
        location_id=location_id,
        lot_id=lot_id,
        reference_type=reference_type,
        reference_id=reference_id,
        user_id=user_id,
        direction=direction,
        state=state,
        since=since,
        until=until,
        exclude_module_contexts=exclude_module_contexts,
    )

    counted = select(StockMove.id).where(*conditions)
    if count_up_to is not None:
        counted = counted.limit(count_up_to + 1)
    total = (
        known_total
        if known_total is not None
        else await db.scalar(select(func.count()).select_from(counted.subquery()))
    )

    origin = aliased(StorageLocation, name='origin')
    destination = aliased(StorageLocation, name='destination')

    async def read(
        extra: Sequence[ColumnElement[bool]], order: Sequence[Any], size: int
    ) -> list[Row[Any]]:
        result = await db.execute(
            select(
                StockMove,
                ProductTemplate.name.label('product_name'),
                Uom.symbol.label('uom_symbol'),
                origin.name.label('from_location_name'),
                destination.name.label('to_location_name'),
                StockLot.name.label('lot_name'),
                # An account that never filled in a name is still nameable.
                func.coalesce(User.full_name, User.email).label('user_name'),
                LocationRelocation.location_name.label('relocated_location_name'),
                LocationRelocation.from_path.label('relocated_from_path'),
                LocationRelocation.to_path.label('relocated_to_path'),
            )
            .outerjoin(
                ProductTemplate, ProductTemplate.id == StockMove.product_template_id
            )
            .outerjoin(Uom, Uom.id == ProductTemplate.uom_id)
            .outerjoin(origin, origin.id == StockMove.from_location_id)
            .outerjoin(destination, destination.id == StockMove.to_location_id)
            .outerjoin(StockLot, StockLot.id == StockMove.lot_id)
            .outerjoin(User, User.id == StockMove.created_by)
            .outerjoin(
                LocationRelocation,
                (StockMove.reference_type == StockMoveReferenceType.LOCATION_RELOCATION)
                & (LocationRelocation.id == StockMove.reference_id),
            )
            .where(*conditions, *extra)
            .order_by(*order)
            .offset(0 if after else offset)
            .limit(size)
        )
        return list(result.all())

    if after is None:
        page = await read([], [_moved_at().desc(), StockMove.id], limit)
    else:
        page = await read_page_after(
            read, moment=_moved_at(), row_id=StockMove.id, after=after, limit=limit
        )

    rows = [
        StockMoveRowDTO(
            **StockMoveDTO.model_validate(row.StockMove).model_dump(),
            product_name=row.product_name,
            uom_symbol=row.uom_symbol,
            from_location_name=row.from_location_name,
            to_location_name=row.to_location_name,
            lot_name=row.lot_name,
            user_name=row.user_name,
            relocated_location_name=row.relocated_location_name,
            relocated_from_path=row.relocated_from_path,
            relocated_to_path=row.relocated_to_path,
        )
        for row in page
    ]
    return rows, int(total or 0)


async def list_by_reference_async(
    db: AsyncSession,
    organization_id: UUID,
    reference_type: str,
    reference_id: UUID,
    *,
    limit: int = 200,
    offset: int = 0,
) -> list[StockMoveDTO]:
    """Async: list moves linked to one source (e.g. a document_id).

    Useful for traceability: "show every StockMove produced by receipt
    document X" or "show every move attributed to adjustment Y". Newest
    first; the id breaks a tie between moves posted in the same instant so
    that a page boundary never repeats or skips one. Pair it with
    :func:`count_by_reference_async` for the true total.
    """
    rows = await db.scalars(
        select(StockMove)
        .where(
            StockMove.organization_id == organization_id,
            StockMove.reference_type == reference_type,
            StockMove.reference_id == reference_id,
        )
        .order_by(StockMove.created_at.desc(), StockMove.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [StockMoveDTO.model_validate(r) for r in rows]


async def count_by_reference_async(
    db: AsyncSession,
    organization_id: UUID,
    reference_type: str,
    reference_id: UUID,
) -> int:
    """Async: how many moves one source is linked to, counted in the statement."""
    total = await db.scalar(
        select(func.count())
        .select_from(StockMove)
        .where(
            StockMove.organization_id == organization_id,
            StockMove.reference_type == reference_type,
            StockMove.reference_id == reference_id,
        )
    )
    return int(total or 0)


async def posted_groups_async(
    db: AsyncSession,
    organization_id: UUID,
    reference_type: str,
    reference_id: UUID,
) -> list[StockMovePostedGroupDTO]:
    """Every group of stock one source filled, and when it last filled it.

    Unlike :func:`list_by_reference_async` this is not a page. A caller
    asking whether the stock a document posted has since been used has to
    see every group it filled: a finite sample of the newest movements drops
    the oldest group whole, and the oldest goods are the ones most likely to
    have moved on since. The grouping is done in the statement, so the
    complete answer costs one row per group rather than one per movement.

    Only movements that landed somewhere and stand are read: an issue has no
    destination, so it took stock off a shelf rather than filling one, and a
    movement that is not ``done`` never landed at all.
    """
    rows = await db.execute(
        select(
            StockMove.product_template_id,
            StockMove.to_location_id,
            StockMove.lot_id,
            StockMove.owner_id,
            func.max(StockMove.created_at).label('posted_at'),
        )
        .where(
            StockMove.organization_id == organization_id,
            StockMove.reference_type == reference_type,
            StockMove.reference_id == reference_id,
            StockMove.to_location_id.is_not(None),
            StockMove.state == StockMoveState.DONE.value,
        )
        .group_by(
            StockMove.product_template_id,
            StockMove.to_location_id,
            StockMove.lot_id,
            StockMove.owner_id,
        )
    )
    return [
        StockMovePostedGroupDTO(
            product_template_id=row.product_template_id,
            to_location_id=row.to_location_id,
            lot_id=row.lot_id,
            owner_id=row.owner_id,
            posted_at=row.posted_at,
        )
        for row in rows
    ]


async def any_departure_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    product_template_id: UUID,
    from_location_id: UUID,
    lot_id: UUID | None,
    owner_id: UUID | None,
    since: datetime,
    excluded_reference_ids: Sequence[UUID] = (),
) -> bool:
    """Whether stock left one group after *since*, other than excluded moves.

    One question the document correction path asks before it undoes a
    posted line: the line still says ten, but has anything taken those
    goods off the shelf since? Answers for one product, one shelf, one batch
    and one owner — ``lot_id`` and ``owner_id`` compare null-safely, because
    "no batch" is a group of its own. ``excluded_reference_ids`` names the
    documents that restate the original (its corrections and returns), whose
    movements are not a use of the stock. ``since`` compares the moment the
    row was recorded, which is the moment the goods landed and the clock the
    document's own arithmetic runs on.
    """
    conditions: list[ColumnElement[bool]] = [
        StockMove.organization_id == organization_id,
        StockMove.product_template_id == product_template_id,
        StockMove.from_location_id == from_location_id,
        StockMove.state == StockMoveState.DONE.value,
        StockMove.created_at >= since,
        StockMove.lot_id.is_not_distinct_from(lot_id),
        StockMove.owner_id.is_not_distinct_from(owner_id),
    ]
    if excluded_reference_ids:
        conditions.append(
            or_(
                StockMove.reference_type.is_(None),
                StockMove.reference_type != StockMoveReferenceType.DOCUMENT.value,
                StockMove.reference_id.is_(None),
                StockMove.reference_id.notin_(excluded_reference_ids),
            )
        )
    found = await db.scalar(select(StockMove.id).where(*conditions).limit(1))
    return found is not None


async def any_departure_from_groups_async(
    db: AsyncSession,
    organization_id: UUID,
    groups: Sequence[StockMovePostedGroupDTO],
    *,
    excluded_reference_ids: Sequence[UUID] = (),
) -> bool:
    """Whether stock left any of *groups* after the group last filled, bar excluded moves.

    :func:`any_departure_async` for many groups in one statement: a document of
    two hundred lines filled two hundred groups, and asking them one by one was
    two hundred round trips for one yes or no.
    """
    if not groups:
        return False
    # One array per column, unnested side by side: a VALUES list of bound
    # parameters reaches the database untyped, and a group without a batch or
    # an owner would make its column ``text``.
    wanted = (
        func.unnest(
            bindparam('products', [g.product_template_id for g in groups], ARRAY(Uuid)),
            bindparam('locations', [g.to_location_id for g in groups], ARRAY(Uuid)),
            bindparam('lots', [g.lot_id for g in groups], ARRAY(Uuid)),
            bindparam('owners', [g.owner_id for g in groups], ARRAY(Uuid)),
            bindparam(
                'sinces', [g.posted_at for g in groups], ARRAY(DateTime(timezone=True))
            ),
        )
        .table_valued(
            column('product_template_id', Uuid),
            column('location_id', Uuid),
            column('lot_id', Uuid),
            column('owner_id', Uuid),
            column('since', DateTime(timezone=True)),
        )
        .render_derived(name='wanted')
    )
    conditions: list[ColumnElement[bool]] = [
        StockMove.organization_id == organization_id,
        StockMove.state == StockMoveState.DONE.value,
        StockMove.product_template_id == wanted.c.product_template_id,
        StockMove.from_location_id == wanted.c.location_id,
        StockMove.created_at >= wanted.c.since,
        StockMove.lot_id.is_not_distinct_from(wanted.c.lot_id),
        StockMove.owner_id.is_not_distinct_from(wanted.c.owner_id),
    ]
    if excluded_reference_ids:
        conditions.append(
            or_(
                StockMove.reference_type.is_(None),
                StockMove.reference_type != StockMoveReferenceType.DOCUMENT.value,
                StockMove.reference_id.is_(None),
                StockMove.reference_id.notin_(excluded_reference_ids),
            )
        )
    found = await db.scalar(select(StockMove.id).where(*conditions).limit(1))
    return found is not None


async def list_recent_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    limit: int = 200,
) -> list[StockMoveDTO]:
    """Async: list the most recent moves across the org, newest first.

    No product or source filter — used for dashboards and recent-activity
    views.  Use ``list_by_template_async`` or ``list_by_reference_async``
    for filtered reads.
    """
    rows = await db.scalars(
        select(StockMove)
        .where(StockMove.organization_id == organization_id)
        .order_by(StockMove.created_at.desc())
        .limit(limit)
    )
    return [StockMoveDTO.model_validate(r) for r in rows]


# ----------------------------------------------------------------------------
# Stock aging
# ----------------------------------------------------------------------------

DEFAULT_AGE_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ('0-30', 0, 30),
    ('31-60', 31, 60),
    ('61-90', 61, 90),
    ('91-180', 91, 180),
    ('180+', 181, None),
)


async def list_receipts_for_aging_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    *,
    as_of: datetime | None = None,
    limit: int = 1000,
) -> list[StockAgeEntryDTO]:
    """Per-receipt aging entries for a product, net of what has left.

    Each entry corresponds to one StockMove that represents an
    *incoming* movement (from_location_id IS NULL — external
    receipt).  ``days_in_stock`` is computed from the movement's
    business date against ``as_of`` (defaults to now) so reports can be
    back-dated for testing or for a specific cutoff. Issues consume the
    receipts oldest business date first, so the buckets' sum is the
    stock a reader can still count — not everything that ever arrived.
    """
    if as_of is None:
        as_of = datetime.now(UTC)

    # The age follows the movement's business date — the same
    # coalesce(completed_at, created_at) the ledger itself sorts by. A
    # booking typed days after the goods arrived used to make the stock
    # look younger than it is.
    business_date = _moved_at()
    age_expr = func.extract('epoch', as_of - business_date) / literal_column('86400')

    # Issues consume the receipts, oldest business date first, so the
    # buckets say what is still on the shelf: ten received, four later
    # dispatched, and the buckets used to still age all ten — their sum
    # never tied back to the stock a reader could count.
    out_total = await db.scalar(
        select(func.coalesce(func.sum(StockMove.quantity), 0)).where(
            StockMove.organization_id == organization_id,
            StockMove.product_template_id == product_template_id,
            StockMove.to_location_id.is_(None),
            StockMove.state == 'done',
            business_date <= as_of,
        )
    )
    remaining_out = Decimal(str(out_total or 0))

    rows = await db.execute(
        select(
            StockMove.id,
            business_date.label('received_at'),
            StockMove.quantity,
            StockMove.to_location_id,
            StockMove.lot_id,
            StockMove.reference_type,
            age_expr.label('days_in_stock'),
        )
        .where(
            StockMove.organization_id == organization_id,
            StockMove.product_template_id == product_template_id,
            StockMove.from_location_id.is_(None),
            StockMove.state == 'done',
        )
        .order_by(business_date.asc(), StockMove.id.asc())
        .limit(limit)
    )

    entries: list[StockAgeEntryDTO] = []
    for row in rows.all():
        if remaining_out <= 0:
            entries.append(
                StockAgeEntryDTO(
                    move_id=row.id,
                    received_at=row.received_at,
                    quantity=row.quantity,
                    location_id=row.to_location_id,
                    lot_id=row.lot_id,
                    reference_type=row.reference_type,
                    days_in_stock=int(row.days_in_stock or 0),
                )
            )
            continue
        # This receipt gives up what the issues before it have consumed,
        # oldest first; a receipt fully consumed leaves the aging.
        consumed = min(Decimal(str(row.quantity)), remaining_out)
        remaining_out -= consumed
        left = Decimal(str(row.quantity)) - consumed
        if left > 0:
            entries.append(
                StockAgeEntryDTO(
                    move_id=row.id,
                    received_at=row.received_at,
                    quantity=left,
                    location_id=row.to_location_id,
                    lot_id=row.lot_id,
                    reference_type=row.reference_type,
                    days_in_stock=int(row.days_in_stock or 0),
                )
            )
    return entries


async def aggregate_aging_buckets_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    *,
    as_of: datetime | None = None,
    buckets: tuple[tuple[str, int, int | None], ...] = DEFAULT_AGE_BUCKETS,
) -> list[StockAgeBucketDTO]:
    """Aggregate aging entries into user-defined buckets.

    Default buckets: 0-30, 31-60, 61-90, 91-180, 180+ days.
    Open-ended upper bound is ``max_days=None``.
    """
    entries = await list_receipts_for_aging_async(
        db,
        organization_id,
        product_template_id,
        as_of=as_of,
    )

    out: list[StockAgeBucketDTO] = []
    for label, min_d, max_d in buckets:
        total = sum(
            (e.quantity for e in entries if _in_bucket(e.days_in_stock, min_d, max_d)),
            Decimal('0'),
        )
        count = sum(1 for e in entries if _in_bucket(e.days_in_stock, min_d, max_d))
        out.append(
            StockAgeBucketDTO(
                label=label,
                min_days=min_d,
                max_days=max_d,
                quantity=total,
                move_count=count,
            )
        )
    return out


def _in_bucket(days: int, min_d: int, max_d: int | None) -> bool:
    if days < min_d:
        return False
    if max_d is None:
        return True
    return days <= max_d


#: Column order of the exported sheet, read by somebody who has never seen
#: the application: what moved, how much, from where to where, and on whose
#: authority.
_EXPORT_COLUMNS = [
    'When',
    'Product',
    'Quantity',
    'Unit',
    'From',
    'To',
    'Batch',
    'Source',
    'Reference',
    'Who',
]


def rows_to_export_frame(rows: list[StockMoveRowDTO], tz: tzinfo) -> Any:
    """The ledger as a table a spreadsheet can open.

    Quantities go out as numbers, not strings: the first thing anyone does
    with this file is sum a column. Dates go out as dates for the same
    reason. The reference is the raw id — Core cannot name a document
    without importing the module that owns one, and an id at least joins.

    Timestamps are converted to the organization's own clock and stripped of
    their offset: Excel refuses an aware datetime outright, and a sheet in
    UTC would disagree with every screen the reader compares it against.
    """
    import pandas as pd

    if not rows:
        return pd.DataFrame(columns=_EXPORT_COLUMNS)

    def _local(moment: datetime | None) -> datetime | None:
        if moment is None:
            return None
        return moment.astimezone(tz).replace(tzinfo=None)

    return pd.DataFrame(
        [
            {
                'When': _local(row.completed_at or row.created_at),
                'Product': row.product_name,
                'Quantity': float(row.quantity),
                'Unit': row.uom_symbol,
                'From': row.from_location_name,
                'To': row.to_location_name,
                'Batch': row.lot_name,
                'Source': row.reference_type,
                'Reference': str(row.reference_id) if row.reference_id else None,
                'Who': row.user_name,
            }
            for row in rows
        ],
        columns=_EXPORT_COLUMNS,
    )
