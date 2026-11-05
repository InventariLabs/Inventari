"""Shared lookup helpers for analytics read-models.

Org-scoped storage-id resolution and currency lookup, used across the
dashboard, cost, and consumption read-models so each query does not
re-implement the same sub-selects.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import in_ids
from app.core.exceptions import ServiceRejectionError
from app.core.logging import get_logger
from app.core.module_ownership import general_rows, outside_module_products
from app.core.money import quantise
from app.models import Item, Organization, StorageLocation

logger = get_logger(__name__)


def rounded(value: Decimal | float | None, places: int = 2) -> float:
    """Round *value* the way the rest of the application rounds money.

    Python's ``round`` is banker's rounding on a binary float: it sends a half
    to the nearest even digit, and it does not see a half at all where the
    binary representation falls a hair under one. Every invoice, document line
    and cost layer here rounds half away from zero, so a figure on a report
    and the same figure in the register disagreed by a cent — on the screen
    a person opens precisely to compare the two.

    Floats are still accepted: not every source upstream is exact yet, and a
    report must not crash on the ones that are not.
    """
    if value is None:
        return 0.0
    return float(quantise(Decimal(str(value)), places))


async def get_internal_storage_ids_async(
    db: AsyncSession, org_id: UUID, hidden_tags: set[str] | None = None
) -> list[UUID]:
    """IDs of internal-usage storage locations for an organization.

    *hidden_tags* leaves out the places a vertical module owns (an equipment
    rack), the way a general report leaves out its records — see
    :func:`app.core.module_ownership.hidden_module_tags_async`.
    """
    query = select(StorageLocation.id).where(
        StorageLocation.organization_id == org_id,
        StorageLocation.usage == 'internal',
    )
    if hidden_tags:
        query = query.where(
            or_(
                StorageLocation.context_tag.is_(None),
                StorageLocation.context_tag.notin_(hidden_tags),
            )
        )
    result = await db.execute(query)
    return [r[0] for r in result.all()]


async def get_org_currency_async(db: AsyncSession, org_id: UUID) -> str:
    """The configured currency for an organization.

    Raises ``ValueError`` if the organization has no currency set.
    """
    result = await db.execute(
        select(Organization.currency).where(Organization.id == org_id)
    )
    row = result.first()
    if not row or not row[0]:
        raise ServiceRejectionError('organization_currency_missing')
    return row[0]


#: Where a stock-value figure came from — carried on the DTO so a screen can
#: say it, and so two screens quoting one organization cannot disagree
#: silently about which arithmetic they used.
VALUE_FROM_LAYERS = 'valuation_layers'
VALUE_FROM_PURCHASE_PRICE = 'purchase_price'
#: No ledger value exists for the slice the reader asked about. The layers
#: know products, not shelves, so a filtered list cannot be priced from the
#: ledger — the response carries no figure instead of one invented from
#: rates the organization's other shelves earned.
VALUE_NOT_AVAILABLE_UNDER_FILTER = 'not_available_under_filter'
#: What population a stock value describes. The cost ledger knows products,
#: not shelves — a layer carries a product template and no location — so a
#: figure read from it is the organization's, whatever storage filter the
#: caller had in hand. A figure read off the records can follow the filter.
VALUE_SCOPE_ORGANIZATION = 'organization'
VALUE_SCOPE_LOCATIONS = 'locations'


def org_currency_filter(column, org_currency: str | None):
    """One currency policy, in one place: the organization's own, or unstated.

    An organization that has stated no currency keeps only the unstated
    prices in its sums — there is no "own" to match, so nothing else
    qualifies.

    Three reports had three answers. The overview added every price together
    whatever currency it was in, so złoty and euro made one number that meant
    nothing. The dashboard took only rows matching the organization exactly,
    so rows with no currency at all vanished from the total. Cost analysis
    took "ours or unstated" and counted what it left out — the right answer,
    and now everyone's.

    NULL means the organization's own currency: that is what every reader
    assumed before the column existed, and what the backfill wrote wherever
    it could.
    """
    return (column == org_currency) | (column.is_(None))


async def _org_offers_the_register_async(db: AsyncSession, org_id: UUID) -> bool:
    """Whether any enabled module of the organization reads the register.

    Documents, maker, purchase orders or stock takes — the modules whose
    manifests set ``consumes_stock_quant``. The register itself is kept for
    every organization; this answers only which
    screens speak from it, so that an organization without such a module
    sees what it always saw. The interface asks the same question of its own
    mirror of that list (``movementModules.ts``), and
    ``test_which_modules_record_movements`` fails the day the two disagree.

    Asked every time, on purpose: a memo cleared by nothing but a restart
    once left the answer depending on which worker took the request.
    """
    from app.core.module_registry import module_registry
    from app.models.organization import Organization

    enabled_modules = await db.scalar(
        select(Organization.enabled_modules).where(Organization.id == org_id)
    )
    if enabled_modules is None:
        return False

    enabled = set(enabled_modules)
    return any(
        mod.metadata.consumes_stock_quant
        for mod in module_registry.get_all()
        if mod.metadata.name in enabled
    )


async def org_uses_valuation_layers_async(db: AsyncSession, org_id: UUID) -> bool:
    """Whether this organization's stock is priced in the cost ledger.

    Two conditions, and both are about telling "worth nothing" apart from
    "nothing to say".

    The cost ledger is kept for every organization, but its figure is what
    the screens show only where a module that reads the register is enabled.
    An organization without one has always seen its stock valued off its
    records, and keeping the register for it too was not meant to
    change a number on its screens.

    And an organization that has the modules can still hold no cost: stock
    imported straight into the records, or standing there since before the
    ledger existed — the archived ``openbal01`` migration opened those shelves with
    layers at 0.00 marked ``unknown``, whose quantity is real and whose
    figure is not a cost (:attr:`StockValuationLayer.carries_a_cost`).
    Reading them reported 0.00 over records that carried their own price,
    which is the same defect this change exists to end, moved one room over.
    One layer carrying a cost puts the ledger back in charge of the whole
    organization — the tile, the list footer and the stock-as-of report ask
    this one question, so the three cannot name two sources.
    """
    from app.models.stock_valuation_layer import StockValuationLayer

    if not await _org_offers_the_register_async(db, org_id):
        return False
    has_cost = await db.scalar(
        select(func.count())
        .select_from(StockValuationLayer)
        .where(
            StockValuationLayer.organization_id == org_id,
            StockValuationLayer.direction == 'IN',
            StockValuationLayer.carries_a_cost,
        )
        .limit(1)
    )
    return bool(has_cost)


async def stock_value_async(
    db: AsyncSession,
    org_id: UUID,
    storage_ids: list[UUID],
    hidden_tags: set[str] | None = None,
) -> tuple[float, str, int, str]:
    """``(value, source, excluded, scope)`` — what the stock on hand is worth.

    From the valuation layers where the organization keeps them: a receipt
    posts a layer at what it cost, and the remaining quantity times that cost
    is the value still on the shelf. ``Item.purchase_price`` cannot answer
    this — it is a field on a form, so correcting a price silently rewrote
    the history of what the warehouse was worth, with no document behind the
    change.

    *excluded* counts the rows left out because their currency is neither the
    organization's nor unstated. Two currencies do not add, and dropping them
    without saying so turns "we cannot total this" into "0.00".

    *hidden_tags* leaves a vertical module's records out of the figure, as
    the counts beside it leave them out: off the records record by record,
    from the ledger product by product (:func:`outside_module_products`).

    *scope* says whom the figure is about. The layers carry no location, so
    the ledger branch cannot honour *storage_ids* and does not pretend to:
    it answers for the whole organization and says so, where it used to
    take the filter and drop it on the floor — a count of records in the
    internal locations beside a value for every location there is.
    """
    from app.models.stock_valuation_layer import StockValuationLayer

    org_currency = await get_org_currency_async(db, org_id)

    if await org_uses_valuation_layers_async(db, org_id):
        value = await db.scalar(
            select(
                func.coalesce(
                    func.sum(
                        StockValuationLayer.remaining_qty
                        * StockValuationLayer.unit_cost
                    ),
                    0,
                )
            ).where(
                StockValuationLayer.organization_id == org_id,
                StockValuationLayer.direction == 'IN',
                StockValuationLayer.remaining_qty > 0,
                org_currency_filter(StockValuationLayer.currency, org_currency),
                outside_module_products(
                    StockValuationLayer.product_template_id, org_id, hidden_tags
                ),
            )
        )
        excluded = await db.scalar(
            select(func.count()).where(
                StockValuationLayer.organization_id == org_id,
                StockValuationLayer.direction == 'IN',
                StockValuationLayer.remaining_qty > 0,
                outside_module_products(
                    StockValuationLayer.product_template_id, org_id, hidden_tags
                ),
                StockValuationLayer.currency.is_not(None),
                StockValuationLayer.currency != org_currency,
            )
        )
        return (
            float(value or 0),
            VALUE_FROM_LAYERS,
            int(excluded or 0),
            VALUE_SCOPE_ORGANIZATION,
        )

    value = await db.scalar(
        select(
            func.coalesce(
                func.sum(Item.quantity * func.coalesce(Item.purchase_price, 0)), 0
            )
        ).where(
            in_ids(Item.storage_location_id, storage_ids),
            Item.is_deleted.is_(False),
            org_currency_filter(Item.currency, org_currency),
            general_rows(hidden_tags),
        )
    )
    excluded = await db.scalar(
        select(func.count()).where(
            in_ids(Item.storage_location_id, storage_ids),
            Item.is_deleted.is_(False),
            general_rows(hidden_tags),
            Item.purchase_price.is_not(None),
            Item.currency.is_not(None),
            Item.currency != org_currency,
        )
    )
    return (
        float(value or 0),
        VALUE_FROM_PURCHASE_PRICE,
        int(excluded or 0),
        VALUE_SCOPE_LOCATIONS,
    )


async def priced_and_unpriced_records_async(
    db: AsyncSession, storage_ids: list[UUID], hidden_tags: set[str] | None = None
) -> tuple[int, int]:
    """``(priced, unpriced)`` — the records on these shelves with a price, and without.

    Only for the value read off the records (no cost ledger): a record with
    no ``purchase_price`` adds nothing to the sum, so a shelf where nobody
    priced anything sums to 0.00 — a figure that reads as "worth nothing"
    when the honest answer is "nobody said". A record with nothing left is
    worth nothing either way and counts on neither side.
    """
    row = (
        await db.execute(
            select(
                func.count(Item.id).filter(Item.purchase_price.is_not(None)),
                func.count(Item.id).filter(Item.purchase_price.is_(None)),
            ).where(
                in_ids(Item.storage_location_id, storage_ids),
                Item.is_deleted.is_(False),
                Item.quantity > 0,
                general_rows(hidden_tags),
            )
        )
    ).one()
    return int(row[0] or 0), int(row[1] or 0)


async def unvalued_stock_count_async(
    db: AsyncSession, org_id: UUID, hidden_tags: set[str] | None = None
) -> int:
    """How many receipts still on the shelf have no known cost.

    A receipt nobody priced, of a product with no rate to borrow, posts a
    layer marked ``unknown``: its quantity is real and adds nothing to the
    stock value, so the tile reads as a complete total. The count is what
    lets it say it is not. Only the cost ledger can answer: the record-price
    branch has no layers to be empty.
    """
    from app.models.stock_valuation_layer import CostBasis, StockValuationLayer

    if not await org_uses_valuation_layers_async(db, org_id):
        return 0
    count = await db.scalar(
        select(func.count()).where(
            StockValuationLayer.organization_id == org_id,
            StockValuationLayer.direction == 'IN',
            StockValuationLayer.remaining_qty > 0,
            StockValuationLayer.cost_basis == CostBasis.UNKNOWN,
            outside_module_products(
                StockValuationLayer.product_template_id, org_id, hidden_tags
            ),
        )
    )
    return int(count or 0)


async def org_timezone_async(db: AsyncSession, org_id: UUID) -> ZoneInfo:
    """The organization's own clock.

    ``Organization.timezone`` has existed on the row since the beginning and
    nothing in the backend ever read it: every report cut its days and months
    on the server's ``date.today()``. A warehouse in Auckland closing its
    month saw the boundary fall at 11am local, and an event at one in the
    morning on the local first of the month landed in the previous month's
    figures.

    An unreadable zone falls back to UTC rather than failing a report — a bad
    string in one row must not take the dashboard down — and says so once.
    """
    name = await db.scalar(
        select(Organization.timezone).where(Organization.id == org_id)
    )
    try:
        return ZoneInfo(name or 'UTC')
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning(
            'Organization %s has an unusable timezone %r; reading in UTC',
            org_id,
            name,
        )
        return ZoneInfo('UTC')


async def org_today_async(
    db: AsyncSession, org_id: UUID, *, now: datetime | None = None
) -> date:
    """What day it is where this organization is.

    For comparisons against date columns — expiry, the date something was
    added. *now* is a seam for tests; production passes nothing.
    """
    instant = now or datetime.now(UTC)
    return instant.astimezone(await org_timezone_async(db, org_id)).date()


async def org_window_start_async(
    db: AsyncSession, org_id: UUID, days: int, *, now: datetime | None = None
) -> datetime:
    """The instant *days* local days ago began, as a point in time.

    The reports compared a timestamp column against a bare date, which
    Postgres reads as midnight UTC — so "the last thirty days" started at a
    moment that had nothing to do with the organization's morning. Returning
    the instant its local day began puts the cut where the user would draw
    it, and every comparison site stays as it is.
    """
    tz = await org_timezone_async(db, org_id)
    instant = now or datetime.now(UTC)
    local_day = instant.astimezone(tz).date() - timedelta(days=days)
    return datetime.combine(local_day, time.min, tzinfo=tz)
