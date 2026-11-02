from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import escape_ilike, in_ids, paginate_async
from app.core.logging import get_logger
from app.models.item import Item
from app.models.storage_location import StorageLocation

from ._search_terms import item_matches_text

logger = get_logger(__name__)


async def search_by_org_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    query_text: str | None = None,
    category_id: UUID | None = None,
    context_tag: str | None = None,
    storage_location_id: UUID | None = None,
    is_deleted: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Item], int]:

    q = (
        select(Item)
        .join(StorageLocation, Item.storage_location_id == StorageLocation.id)
        .where(
            StorageLocation.organization_id == organization_id,
            # Named on the record too. The join scopes the rows by
            # organization, but only through a location: while the tenant is
            # a property of the joined table the planner cannot start from
            # ``ix_items_org_created``, and the page is ordered by it. It
            # walked the global timeline instead, reading other tenants'
            # rows in write order to answer one organization's page.
            Item.organization_id == organization_id,
            Item.is_deleted == is_deleted,
        )
    )

    if query_text:
        q = q.where(item_matches_text(query_text, organization_id))

    if category_id:
        q = q.where(Item.category_id == category_id)

    if context_tag:
        from app.core.module_ownership import items_with_context_tag

        q = q.where(items_with_context_tag(context_tag))

    if storage_location_id:
        q = q.where(Item.storage_location_id == storage_location_id)

    return await paginate_async(
        db,
        q.order_by(Item.created_at.desc()),
        limit=limit,
        offset=offset,
    )


async def search_cursor_paginated_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    storage_ids: list[UUID] | None = None,
    storage_id: UUID | None = None,
    search: str | None = None,
    quantity_above: Decimal | None = None,
    cursor_ts=None,
    cursor_id: UUID | None = None,
    limit: int = 50,
) -> list[Item]:
    """Cursor (keyset) pagination on Item.created_at for infinite-scroll UIs.

    Returns up to *limit* items ordered by created_at DESC, id DESC,
    optionally filtered by storage_ids, single storage_id, a free-text
    name search, and a stock floor (strictly above *quantity_above*). The (cursor_ts, cursor_id) pair is the
    keyset tie-breaker: without it, rows sharing a created_at (bulk
    imports) are skipped or returned twice across pages.
    """
    from sqlalchemy import and_, or_
    from sqlalchemy.orm import joinedload

    q = select(Item).options(joinedload(Item.category), joinedload(Item.uom))

    if storage_ids:
        q = q.where(in_ids(Item.storage_location_id, storage_ids))
    if storage_id:
        q = q.where(Item.storage_location_id == storage_id)
    if search:
        pattern = f'%{escape_ilike(search)}%'
        q = q.where(Item.name.ilike(pattern))
    if quantity_above is not None:
        # A stock floor has to bite before the LIMIT cut: applied after it,
        # a page full of emptied records pushes the record that still has
        # goods off the page and the caller answers "nothing found" about
        # a shelf that holds them. NULL fails the comparison too, so
        # records without a tracked quantity drop with the empty ones.
        q = q.where(Item.quantity > quantity_above)
    if cursor_ts is not None:
        if cursor_id is not None:
            q = q.where(
                or_(
                    Item.created_at < cursor_ts,
                    and_(Item.created_at == cursor_ts, Item.id < cursor_id),
                )
            )
        else:
            q = q.where(Item.created_at < cursor_ts)
    q = q.where(
        Item.is_deleted.is_(False),
        Item.storage_location_id.isnot(None),
    )
    if organization_id is not None:
        # Tenant scoping MUST be applied unconditionally. Relying solely on
        # ``storage_ids`` leaks cross-tenant when the caller's org has zero
        # storage locations (storage_ids == [] -> the IN filter is skipped).
        q = q.where(Item.organization_id == organization_id)

    result = await db.scalars(
        q.order_by(Item.created_at.desc(), Item.id.desc()).limit(limit)
    )
    return list(result.unique().all())


async def search_stock_summary_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    storage_ids: list[UUID] | None = None,
    search: str | None = None,
    quantity_above: Decimal | None = None,
    limit: int = 50,
) -> list[tuple[Item, Decimal, bool]]:
    """Distinguishable stock rows individually, interchangeable ones summed.

    A caller that shows one row per record has to offer records nothing on
    the row can tell apart as separate identical choices; this answers both
    shapes in one call — records carrying a best-before or a serial come
    back one by one, and the complement (no date, no serial) comes back as
    one row per (product, shelf) carrying the shelf's total. The complement
    is exact: a record already travelling individually is not counted into
    any group, so a shelf holding both kinds offers its stock once.

    The summing happens in SQL, before any page is cut: a Python merge on a
    cut page made the total depend on the page size (four records of one
    piece answering two at limit=2 and three at limit=3).

    Records catalogued as no template group by their name: to the reader,
    same-named goods on one shelf are one row of stock. A group's row is
    its newest record — that date puts the row on the page — and groups are
    cut newest first, so the combined list stays newest-first like every
    other search. The page is a top-N over both kinds: a shelf whose dated
    records fill it leaves its undated remainder for the next page.

    Returns ``(item, offered_quantity, merged)`` triples: ``merged`` marks
    the summed rows, whose ``offered_quantity`` is the group's total and
    whose other fields come from the group's newest record.
    """
    from sqlalchemy import String, and_, func, or_
    from sqlalchemy.dialects.postgresql import aggregate_order_by
    from sqlalchemy.orm import joinedload

    def _base_filters(q):
        q = q.where(
            Item.is_deleted.is_(False),
            Item.storage_location_id.isnot(None),
        )
        if storage_ids:
            q = q.where(in_ids(Item.storage_location_id, storage_ids))
        if search:
            pattern = f'%{escape_ilike(search)}%'
            q = q.where(Item.name.ilike(pattern))
        if quantity_above is not None:
            q = q.where(Item.quantity > quantity_above)
        # Tenant scoping MUST be applied unconditionally (see the cursor
        # search above: storage_ids == [] skips the IN filter).
        q = q.where(Item.organization_id == organization_id)
        return q

    # Records a reader can tell apart: the date or the serial makes them
    # two rows, so they travel individually.
    distinct_q = _base_filters(
        select(Item).options(joinedload(Item.category), joinedload(Item.uom))
    ).where(or_(Item.expiry_date.isnot(None), Item.serial_number.isnot(None)))
    distinct_rows = list(
        (
            await db.scalars(
                distinct_q.order_by(Item.created_at.desc(), Item.id.desc()).limit(limit)
            )
        )
        .unique()
        .all()
    )

    # Records nothing names apart: one row per (product or name, shelf),
    # summed where the query runs. The where is the exact complement of the
    # individual pass above — dated and serialised records are already rows
    # of their own, and a group that counted them too offered the same
    # goods twice (shelf total plus the dated rows standing on it).
    group_key = func.coalesce(func.cast(Item.template_id, String), 'name:' + Item.name)
    grouped_q = _base_filters(
        select(
            Item.storage_location_id.label('shelf_id'),
            group_key.label('group_key'),
            # The group's representative is its newest record — the date a
            # reader goes by. Aggregate-ordered so the seed survives as a
            # single id instead of an array.
            func.array_agg(
                aggregate_order_by(Item.id, Item.created_at.desc(), Item.id.desc())
            )[1].label('seed_id'),
            func.sum(Item.quantity).label('total'),
        )
        .group_by(Item.storage_location_id, group_key)
        .order_by(func.max(Item.created_at).desc())
        .limit(limit)
    )
    grouped_q = grouped_q.where(
        Item.expiry_date.is_(None), Item.serial_number.is_(None)
    ).subquery()
    summed = await db.execute(
        select(Item, grouped_q.c.total)
        .join(
            grouped_q,
            and_(
                Item.storage_location_id == grouped_q.c.shelf_id,
                func.coalesce(func.cast(Item.template_id, String), 'name:' + Item.name)
                == grouped_q.c.group_key,
                Item.id == grouped_q.c.seed_id,
            ),
        )
        .where(
            # The join rides the seed id, which is globally unique, so these
            # never bite today — but the sibling cursor search carries them
            # and the next reader should not have to prove it again.
            Item.organization_id == organization_id,
            Item.is_deleted.is_(False),
        )
        .options(joinedload(Item.category), joinedload(Item.uom))
    )
    grouped_rows: list[tuple[Item, Decimal]] = [
        (item, total) for item, total in summed.unique().all()
    ]

    combined: list[tuple[Item, Decimal, bool]] = [
        *[(row, row.quantity, False) for row in distinct_rows],
        *[(item, total, True) for item, total in grouped_rows],
    ]
    combined.sort(key=lambda triple: triple[0].created_at, reverse=True)
    return [(item, offered, merged) for item, offered, merged in combined[:limit]]
