"""Overview inventory-health read-model.

High-level counts (total items, expiring soon, expired, low stock) for an
organization. Domain-neutral: works identically for food, equipment, or
warehouse verticals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import OverviewDTO
from app.core.module_ownership import (
    general_rows,
    hidden_module_tags_async,
    unclaimed_by_a_module,
)
from app.core.open_package import OPENED_KEY
from app.models import Item, StorageLocation
from app.services.items.expiry import (
    DEFAULT_EXPIRING_SOON_DAYS,
    is_expired,
    is_expiring_soon,
)
from app.services.items.low_stock import claimed_tags_for, low_stock_count_async

from ._common import (
    VALUE_FROM_PURCHASE_PRICE,
    get_internal_storage_ids_async,
    org_today_async,
    priced_and_unpriced_records_async,
    stock_value_async,
    unvalued_stock_count_async,
)


@dataclass(frozen=True)
class HealthCounts:
    """What needs attention, counted once for every screen that asks.

    ``expired`` and ``expiring_soon`` are records, for a date; ``low_stock``
    is products, for a threshold — the three shares the attention count is
    summed from. The overview the statistics screen reads and the
    attention-counts endpoint the dashboard reads both take them from
    :func:`_health_counts_async`, so a heading and a tile cannot compute
    different answers for the same organization.
    """

    expired: int
    expiring_soon: int
    low_stock: int


def _internal_shelves(organization_id: UUID) -> Select:
    # The organization's own shelves, asked of the locations table inside the
    # statement: a list of their ids bound one by one ran past what one
    # statement may carry, and as ``= ANY(...)`` it steered the planner onto
    # the location index across every record.
    return select(StorageLocation.id).where(
        StorageLocation.organization_id == organization_id,
        StorageLocation.usage == 'internal',
    )


def _dated_counts_query(organization_id: UUID, today: date) -> Select:
    horizon = today + timedelta(days=DEFAULT_EXPIRING_SOON_DAYS)
    return select(
        func.count(case((is_expiring_soon(today), 1))).label('expiring_soon'),
        func.count(case((is_expired(today), 1))).label('expired'),
    ).where(
        Item.organization_id == organization_id,
        Item.storage_location_id.in_(_internal_shelves(organization_id)),
        Item.is_deleted.is_(False),
        # Only a record dated by the horizon can be either: by its own date,
        # or by the use-by written when it was opened. Each of the two is
        # read through its own index, so the count reads the dated records
        # near today instead of every record of the organization.
        or_(Item.expiry_date <= horizon, Item.meta_data.has_key(OPENED_KEY)),
    )


async def _health_counts_async(
    db: AsyncSession,
    organization_id: UUID,
    today: date,
    claimed_tags: set[str] | None,
) -> HealthCounts:
    """The three numbers, with the module filter already resolved.

    *claimed_tags* is ``None`` when the module-data setting is on — and
    when no module claims a category tag in this build, which is how the
    item list resolves the same setting. A set of tags keeps only the
    records a general list shows; a short product whose records are all
    module-owned has nothing visible left and drops out with them, which
    is what the list behind the count shows.
    """
    item_query = _dated_counts_query(organization_id, today)
    if claimed_tags is not None:
        item_query = item_query.where(unclaimed_by_a_module(claimed_tags))
    row = (await db.execute(item_query)).one()

    low_stock = await low_stock_count_async(db, organization_id, claimed_tags)

    return HealthCounts(
        expired=row.expired or 0,
        expiring_soon=row.expiring_soon or 0,
        low_stock=low_stock,
    )


async def get_health_counts_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    exclude_module_contexts: bool = False,
) -> HealthCounts:
    """Count what needs attention, from one place, for every screen.

    ``exclude_module_contexts`` mirrors the item list's own filter: a
    record filed under a category a vertical module claims is left out,
    and so is a short product that has no visible record left. Both the
    dashboard heading and the statistics health card read this function —
    the dashboard through ``GET /items/attention-counts``, the statistics
    overview through :func:`get_overview_async` — so one organization has
    one number, not two independent computations of it.
    """
    today = await org_today_async(db, organization_id)
    # The `or None` is the item list's own reading of the setting: a build
    # whose modules claim only a namespace has no tags to hide by.
    claimed_tags = claimed_tags_for(exclude_module_contexts)
    return await _health_counts_async(db, organization_id, today, claimed_tags)


async def get_overview_async(db: AsyncSession, organization_id: UUID) -> OverviewDTO:
    """Aggregate inventory health snapshot for an organization.

    A vertical module's records and places stay out unless the organization
    shows module data in its general lists — the products list leaves them
    out, and the snapshot beside it counted the family laptop among the
    pantry's records, places and value.
    """
    hidden = await hidden_module_tags_async(db, organization_id)
    storage_ids = await get_internal_storage_ids_async(db, organization_id, hidden)

    today = await org_today_async(db, organization_id)

    counts = await _health_counts_async(db, organization_id, today, claimed_tags=hidden)
    # The shelf itself: every record, and the ones that carry a date.
    shelf = (
        await db.execute(
            select(
                func.count(Item.id).label('total_items'),
                func.count(Item.effective_expiry_date).label('dated_items'),
            ).where(
                Item.organization_id == organization_id,
                Item.storage_location_id.in_(_internal_shelves(organization_id)),
                Item.is_deleted.is_(False),
                general_rows(hidden),
            )
        )
    ).one()

    # What the stock is worth comes from the cost ledger where the
    # organization keeps one. It used to be `quantity * purchase_price`, and
    # `purchase_price` is a field on a form — so correcting a price rewrote
    # the history of what the warehouse was worth, with no document behind
    # the change and nothing to reconcile against.
    total_value, value_source, excluded, value_scope = await stock_value_async(
        db, organization_id, storage_ids, hidden
    )

    # Off the records, a missing price adds nothing: a shelf nobody priced
    # summed to 0.00 and read as worth nothing. With no price anywhere the
    # value is unknown, and says so; with some, the records left out are
    # counted beside the figure, which is then a lower bound.
    unpriced = 0
    unvalued = await unvalued_stock_count_async(db, organization_id, hidden)
    if value_source == VALUE_FROM_PURCHASE_PRICE:
        priced, unpriced = await priced_and_unpriced_records_async(
            db, storage_ids, hidden
        )
        value_known = not (unpriced and not priced)
    else:
        # From the ledger: receipts nobody priced, and nothing priced left on
        # hand to add them to — the same "nobody said" in the ledger's words.
        value_known = not (unvalued and not total_value)

    return OverviewDTO(
        total_items=shelf.total_items or 0,
        total_locations=len(storage_ids),
        expiring_soon=counts.expiring_soon,
        expired=counts.expired,
        low_stock=counts.low_stock,
        total_value=total_value,
        value_known=value_known,
        value_source=value_source,
        excluded_other_currency_count=excluded,
        value_scope=value_scope,
        unvalued_stock_count=unvalued,
        unpriced_item_count=unpriced,
        tracks_expiry=bool(shelf.dated_items),
    )
