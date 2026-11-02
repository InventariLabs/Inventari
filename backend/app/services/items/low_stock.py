"""What "running low" means — said once, for every screen that asks.

``ProductTemplate.min_quantity`` is **one value per product**, not a limit
each stock record is measured against on its own. The module that adds
per-location thresholds on top of it says so in the docstring of its own
table: *"Per-location granularity is the main value-add over the flat
ProductTemplate.min_quantity field, which is org-global."*

Three places used to answer "is this running out" and two of them compared
that org-global number against a single ``Item`` row. For a product kept
in six places — 8, 7, 8, 5, 2 and 4 units against a minimum of 10 — the
dashboard tile and the list filter answered "six shortages" while the
purchasing engine, which summed, answered "none". Thirty-four units
against a minimum of ten is not six shortages, and the more carefully
somebody spread their stock the more shortages the tile invented.

It was unstable as well as wrong: an ``Item`` row is not a quant. A
quant is one (org, product, location, lot, owner) group, however many
records it sums; ``Item`` carries none of that, and two receipts of the same
hand-typed name into one place leave two rows. So the number on the tile
moved with how a name had been typed at goods-in.

Two conditions complete the rule, and both are read from this one place by
every surface — the dashboard tile, the products filter, the statistics
screen and the purchasing engine behind the replenish button:

- stock standing in a non-internal location (customer, production,
  consumed, external) is not on the shelf;
- a product with *active* stock outside the shelf is not bought again —
  something already on its way is not something to order. The engine kept
  this condition to itself, so on the shape it was written for — a product
  at zero on the shelf and one row moved to a customer location — the tile
  said "1 low stock" while the engine behind the tile's own button proposed
  nothing. A surface a reader acts on may not be narrower than the rule
  the action follows, so the condition lives here now.

Both queries join the records on the organization as well as on the product:
``items`` has no index that starts at ``template_id``, so a join on the
product alone read the whole table once per short product — 11.9 million
buffers and 28 s at 100 000 products — where the ``(organization, product)``
index answers each in a few pages.

A product with no records at all is not short: there is nothing whose
threshold was crossed. The outer joins and the ``count`` keep that
answer inside this one query.
"""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, String, case, cast, exists, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import LowStockProductDTO
from app.core.module_ownership import unclaimed_by_a_module
from app.core.module_scope import get_claimed_context_tags
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.storage_location import LocationUsage, StorageLocation
from app.models.uom import Uom


def claimed_tags_for(exclude_module_contexts: bool) -> set[str] | None:
    """The category tags a general list hides, or ``None`` when it hides none.

    The ``or None`` is the item list's own reading of the setting: a build
    whose modules claim only a namespace has no tags to hide by.
    """
    if not exclude_module_contexts:
        return None
    return get_claimed_context_tags() or None


def low_stock_template_ids(
    organization_id: UUID, claimed_tags: set[str] | None = None
) -> Select:
    """Products whose stock on the shelves has reached their threshold.

    Returns a selectable of ``ProductTemplate.id`` — one row per product,
    never one per record — so a caller may count it, or filter records by
    it, and get answers that agree.

    *claimed_tags* is what a general list hides (see :func:`claimed_tags_for`):
    a short product whose every record is a module's has nothing visible left
    and drops out with them. The count the dashboard heading shows, the tile
    and the list behind them all take their set from here.
    """
    internal_qty = case(
        (StorageLocation.usage == LocationUsage.INTERNAL, Item.quantity),
        else_=0,
    )
    active_outside = case(
        (
            (StorageLocation.usage != LocationUsage.INTERNAL) & (Item.quantity > 0),
            1,
        ),
        else_=0,
    )
    short = (
        select(ProductTemplate.id)
        .outerjoin(
            Item,
            (Item.organization_id == organization_id)
            & (Item.template_id == ProductTemplate.id)
            & (Item.is_deleted.is_(False)),
        )
        .outerjoin(StorageLocation, Item.storage_location_id == StorageLocation.id)
        .where(
            ProductTemplate.organization_id == organization_id,
            ProductTemplate.min_quantity.isnot(None),
            ProductTemplate.min_quantity > 0,
        )
        .group_by(ProductTemplate.id, ProductTemplate.min_quantity)
        .having(
            func.coalesce(func.sum(internal_qty), 0) <= ProductTemplate.min_quantity,
            func.count(Item.id) > 0,
            func.coalesce(func.sum(active_outside), 0) == 0,
        )
    )
    if claimed_tags is None:
        return short
    short_ids = short.subquery()
    visible_record = select(Item.id).where(
        Item.template_id == short_ids.c.id,
        # Not the shelves: a product used up has its last record under the
        # virtual Consumed location. What hides a product is that every
        # record is a module's.
        Item.organization_id == organization_id,
        Item.is_deleted.is_(False),
        unclaimed_by_a_module(claimed_tags),
    )
    return select(short_ids.c.id).where(exists(visible_record))


def used_up_short_product_records(
    organization_id: UUID, claimed_tags: set[str] | None = None
) -> Select:
    """The record a list shows for a short product with nothing on the shelves.

    Using up the last unit moves the record to the virtual Consumed place, so
    a list of the shelves has no row for the product the count calls short:
    "needs attention 3" opened two records. This names one record per such
    product — its most recently changed, the one that was used up last —
    rather than every record it ever used up. A product with a record on a
    shelf is shown by that record and gets none here.

    *claimed_tags* is what the list hides (:func:`claimed_tags_for`): the
    record named is one the list can show.
    """
    shown = unclaimed_by_a_module(claimed_tags) if claimed_tags else true()
    shelved = (
        select(Item.template_id)
        .join(StorageLocation, Item.storage_location_id == StorageLocation.id)
        .where(
            Item.organization_id == organization_id,
            Item.template_id.is_not(None),
            Item.is_deleted.is_(False),
            StorageLocation.usage == LocationUsage.INTERNAL,
            shown,
        )
    )
    return (
        select(Item.id)
        .where(
            Item.organization_id == organization_id,
            Item.is_deleted.is_(False),
            Item.template_id.in_(low_stock_template_ids(organization_id, claimed_tags)),
            Item.template_id.not_in(shelved),
            shown,
        )
        .distinct(Item.template_id)
        .order_by(Item.template_id, Item.updated_at.desc(), Item.id.desc())
    )


async def template_stock_total_async(
    db: AsyncSession, organization_id: UUID, template_id: UUID
) -> Decimal:
    """How much of one product is on the shelves, summed the same way.

    The number the threshold is compared against, so the screen that sets
    a threshold can show it. It used to show the quantity of the single
    record the reader had opened, and offered to copy that number into a
    field governing the product as a whole: on a product kept in six
    places, "set the alert to what is here now" set it to a sixth of what
    is there now, and the alert then never fired.
    """
    total = await db.scalar(
        select(func.coalesce(func.sum(Item.quantity), 0))
        .select_from(Item)
        .join(StorageLocation, Item.storage_location_id == StorageLocation.id)
        .where(
            Item.organization_id == organization_id,
            Item.template_id == template_id,
            Item.is_deleted.is_(False),
            StorageLocation.usage == LocationUsage.INTERNAL,
        )
    )
    return Decimal(str(total or 0))


async def low_stock_count_async(
    db: AsyncSession, organization_id: UUID, claimed_tags: set[str] | None
) -> int:
    """How many products are short — the tile's number and the list's total.

    *claimed_tags* is already resolved (``claimed_tags_for``), the way both
    callers hold it, so the number and the rows it counts are one query.
    """
    return (
        await db.scalar(
            select(func.count()).select_from(
                low_stock_template_ids(organization_id, claimed_tags).subquery()
            )
        )
        or 0
    )


async def low_stock_products_async(
    db: AsyncSession,
    organization_id: UUID,
    limit: int = 100,
    exclude_module_contexts: bool = False,
    offset: int = 0,
) -> list[LowStockProductDTO]:
    """The products behind the tile's number, the emptiest first.

    Same rule, same query as the tile counts (``low_stock_template_ids``),
    so the list can never hold a different set than the number it explains.
    A product with nothing on the shelves is listed with ``on_hand`` of 0:
    where its last record went is not something the reader has to know.
    ``exclude_module_contexts`` leaves out what the item list leaves out, and
    the row's record to open is always one the list can show.
    """
    claimed_tags = claimed_tags_for(exclude_module_contexts)
    short_ids = low_stock_template_ids(organization_id, claimed_tags)
    shown = unclaimed_by_a_module(claimed_tags) if claimed_tags else true()
    internal_qty = case(
        (StorageLocation.usage == LocationUsage.INTERNAL, Item.quantity),
        else_=0,
    )
    rows = await db.execute(
        select(
            ProductTemplate.id,
            ProductTemplate.name,
            ProductTemplate.min_quantity,
            func.coalesce(func.sum(internal_qty), 0).label('on_hand'),
            # Shelf records sort ahead of the rest ('0' < '1'), so a used-up
            # product falls back to its last record. A record the list hides
            # has no key, so it is never the one to open.
            func.min(
                case(
                    (
                        shown,
                        func.concat(
                            case(
                                (StorageLocation.usage == LocationUsage.INTERNAL, '0'),
                                else_='1',
                            ),
                            cast(Item.id, String),
                        ),
                    )
                )
            ).label('item_id'),
            Uom.symbol,
        )
        .outerjoin(
            Item,
            (Item.organization_id == organization_id)
            & (Item.template_id == ProductTemplate.id)
            & (Item.is_deleted.is_(False)),
        )
        .outerjoin(StorageLocation, Item.storage_location_id == StorageLocation.id)
        .outerjoin(Uom, ProductTemplate.uom_id == Uom.id)
        .where(ProductTemplate.id.in_(short_ids))
        .group_by(ProductTemplate.id, ProductTemplate.name, Uom.symbol)
        # The id breaks a tie, so a page boundary cannot repeat or drop a row.
        .order_by('on_hand', ProductTemplate.name, ProductTemplate.id)
        .offset(offset)
        .limit(limit)
    )
    return [
        LowStockProductDTO(
            template_id=row[0],
            name=row[1],
            minimum=float(row[2]),
            on_hand=float(row[3]),
            item_id=UUID(row[4][1:]) if row[4] else None,
            uom_symbol=row[5],
        )
        for row in rows.all()
    ]
