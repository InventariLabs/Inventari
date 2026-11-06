"""The stock screen's rows — one page of shelves, in words.

The picking reads live in ``_stock_quant_query``; this is the reporting
side, and it differs in the one way that matters: it resolves names in the
same statement, counts the whole answer, and never subtracts a reservation
from the quantity it prints.

A row is a group — a product on a shelf, in one batch, of one owner — and
everything on it comes from the records and the reservation rows. The page
walks the anchors (one per product on a shelf) in the order it prints them,
sums each anchor's records by batch and owner beside it, and stops once it
is full; the count is taken straight off the records. There is no quant
table to read: it went with the one-number stock model (ADR-022).
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    CompoundSelect,
    Numeric,
    and_,
    cast,
    func,
    literal,
    literal_column,
    or_,
    select,
    true,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import StockQuantRowDTO
from app.core.db_utils import count_window, escape_ilike, in_ids
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.stock_anchor import StockAnchor
from app.models.stock_lot import (
    LotStatus,
    StockLot,
    effective_status_expression,
)
from app.models.stock_reservation import StockReservation
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.services.storage._queries import descendant_ids_async

# Rendered into the statement, never bound. asyncpg prepares every statement,
# and after five runs Postgres may plan it once for any parameters: a bound
# ``0`` or ``LIMIT`` is then a number it does not know, it guesses how many
# records hold stock and how many rows the page wants, and it sorts every
# anchor of the organization to print fifty rows (1.9-2.8x today's page on
# 100 000 records, against 0.55x with the numbers written in).
_NAN: ColumnElement[Decimal] = literal_column("'NaN'::numeric")
_ZERO: ColumnElement[Decimal] = literal_column('0')


def _holds() -> ColumnElement[bool]:
    """A record that holds something: more than nothing, and a number.

    A record never holds less than nothing (``ck_items_quantity_nonneg``), so
    a group holds stock exactly when one of its records holds more than zero,
    and the sum over those records is the group's whole sum. The screen hides
    an empty group unless asked, and this is how it tells one — off the
    index, without adding a group up first.
    """
    return and_(Item.quantity > _ZERO, Item.quantity != _NAN)


def _product_matches(pattern: str) -> ColumnElement[bool]:
    """What a typed string is matched against on the product's side.

    Its name, brand, the code a scan wrote and its catalogue number — the
    same reading the product list uses (``app.services.items._search_terms``),
    minus the fields only an item carries: a shelf row is a product at a
    place, not a record. The batch is matched too, by the caller, because
    PARTIA is a column of this very list and a recall notice names the batch
    rather than the product.
    """
    return or_(
        ProductTemplate.name.ilike(pattern),
        ProductTemplate.brand.ilike(pattern),
        ProductTemplate.barcode.ilike(pattern),
        ProductTemplate.sku.ilike(pattern),
    )


def searched_products(organization_id: UUID, pattern: str) -> CompoundSelect:
    """The products a typed string can reach: by their own fields or by a batch.

    Narrowing to these first is what keeps a search cheap: the groups of
    every other product are never added up to learn that nothing on them
    matches.
    """
    return (
        select(ProductTemplate.id)
        .where(
            ProductTemplate.organization_id == organization_id,
            _product_matches(pattern),
        )
        .union(
            select(StockLot.product_template_id).where(
                StockLot.organization_id == organization_id,
                StockLot.name.ilike(pattern),
            )
        )
    )


def _group_id(
    organization_id: UUID,
    product_template_id: UUID,
    storage_location_id: UUID,
    lot_id: UUID | None,
    owner_id: UUID | None,
) -> UUID:
    """The group's id as ``stock_quants_from_records`` spells it.

    A row keeps one identity whichever read it came from. Not a secret and
    not a check — the view derives its row id the same way.
    """
    key = '/'.join(
        '-' if part is None else str(part)
        for part in (
            organization_id,
            product_template_id,
            storage_location_id,
            lot_id,
            owner_id,
        )
    )
    return UUID(hashlib.md5(key.encode(), usedforsecurity=False).hexdigest())


def _free_stock(
    quantity: Decimal, reserved: Decimal, lot_status: str | None
) -> Decimal:
    """What a picker could actually take off this shelf.

    Stock minus reservations, and nothing at all when the batch is one the
    engine will not release: ``active_lot_predicate`` keeps a held batch out
    of the picking candidates and ``assert_lot_consumable_async`` refuses it
    in words. Leaving the arithmetic alone put a badge saying "quarantined"
    next to a number saying "take twelve" — and this column exists to be
    summed, so a planner promised a customer goods the warehouse would not
    hand over, learning of the refusal only at picking time.

    Stock outside any batch has no batch status to obey and is unaffected.
    """
    if lot_status is not None and lot_status != LotStatus.ACTIVE:
        return Decimal('0')
    return (quantity or Decimal('0')) - (reserved or Decimal('0'))


async def _count_groups_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    product_template_id: UUID | None,
    location_ids: list[UUID] | None,
    lot_id: UUID | None,
    include_empty: bool,
    pattern: str | None,
    count_up_to: int | None = None,
) -> int:
    """How many rows the whole answer has: the distinct groups of the records.

    Read off the records alone. A record with a product on a shelf always
    stands in an anchor's group (the key from ``items`` to ``stock_anchors``),
    so these are exactly the groups the page walks. ``count_up_to`` stops one
    group past it: a total above it means there are more.
    """
    groups = (
        select(Item.template_id, Item.storage_location_id, Item.lot_id, Item.owner_id)
        .where(
            Item.organization_id == organization_id,
            Item.is_deleted.is_(False),
            Item.template_id.is_not(None),
            Item.storage_location_id.is_not(None),
        )
        .distinct()
    )
    if not include_empty:
        groups = groups.where(_holds())
    if product_template_id is not None:
        groups = groups.where(Item.template_id == product_template_id)
    if location_ids is not None:
        groups = groups.where(in_ids(Item.storage_location_id, location_ids))
    if lot_id is not None:
        groups = groups.where(Item.lot_id == lot_id)
    if pattern is not None:
        groups = (
            groups.where(
                Item.template_id.in_(searched_products(organization_id, pattern))
            )
            .join(ProductTemplate, ProductTemplate.id == Item.template_id)
            .outerjoin(StockLot, StockLot.id == Item.lot_id)
            .where(or_(_product_matches(pattern), StockLot.name.ilike(pattern)))
        )
    if count_up_to is not None:
        groups = groups.limit(count_up_to + 1)
    return (await db.scalar(select(func.count()).select_from(groups.subquery()))) or 0


async def list_rows_for_org_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    product_template_id: UUID | None = None,
    location_id: UUID | None = None,
    lot_id: UUID | None = None,
    include_empty: bool = False,
    search: str | None = None,
    limit: int = 200,
    offset: int = 0,
    count_cap: int | None = None,
) -> tuple[list[StockQuantRowDTO], int]:
    """One page of shelves, ordered so that a place reads as a block.

    ``include_empty`` shows the groups whose records hold nothing; a group
    with no live record at all has nothing to show and is not a row.
    ``count_cap`` counts only so far (``db_utils.paginate_async``); the caller
    hands the same cap to ``from_slice``.
    """
    location_ids = None
    if location_id is not None:
        location_ids = [
            location_id,
            *await descendant_ids_async(db, organization_id, location_id),
        ]
    pattern = f'%{escape_ilike(search)}%' if search else None

    total = await _count_groups_async(
        db,
        organization_id,
        product_template_id=product_template_id,
        location_ids=location_ids,
        lot_id=lot_id,
        include_empty=include_empty,
        pattern=pattern,
        count_up_to=count_window(offset, limit, count_cap) if count_cap else None,
    )

    # What each group of the anchor holds, summed beside it — the records
    # grouped by batch and owner the way ``stock_quants_from_records`` groups
    # them, ``nullif`` setting a NaN record aside as the view does, and the
    # sums carrying its numeric(12,3).
    held = func.sum(func.nullif(Item.quantity, _NAN))
    groups = (
        select(
            Item.lot_id.label('lot_id'),
            Item.owner_id.label('owner_id'),
            cast(func.coalesce(held, 0), Numeric(12, 3)).label('quantity'),
            func.min(Item.effective_expiry_date).label('expiry_date'),
        )
        .where(
            Item.organization_id == StockAnchor.organization_id,
            Item.template_id == StockAnchor.product_template_id,
            Item.storage_location_id == StockAnchor.storage_location_id,
            Item.is_deleted.is_(False),
        )
        .group_by(Item.lot_id, Item.owner_id)
    )
    if not include_empty:
        groups = groups.where(_holds())
    if lot_id is not None:
        groups = groups.where(Item.lot_id == lot_id)
    group = groups.lateral('stock_group')

    # The group's promises: the reservation rows naming its anchor, batch and
    # owner, the same rows the view sums.
    promised = (
        select(cast(func.sum(StockReservation.quantity), Numeric(12, 3)))
        .where(
            StockReservation.anchor_id == StockAnchor.id,
            StockReservation.lot_id.is_not_distinct_from(group.c.lot_id),
            StockReservation.owner_id.is_not_distinct_from(group.c.owner_id),
        )
        .correlate(StockAnchor, group)
        .scalar_subquery()
    )

    stmt = (
        select(
            StockAnchor.product_template_id,
            StockAnchor.storage_location_id,
            group.c.lot_id,
            group.c.owner_id,
            group.c.quantity,
            # The group's own records first: an opened package carries its
            # use-by date there. The batch's date is what an undated record
            # of a dated batch stands on.
            func.coalesce(
                group.c.expiry_date,
                func.least(
                    func.coalesce(StockLot.use_by_date, StockLot.expiry_date),
                    func.coalesce(StockLot.expiry_date, StockLot.use_by_date),
                ),
            ).label('expiry_date'),
            promised.label('reserved'),
            ProductTemplate.name.label('product_name'),
            Uom.symbol.label('uom_symbol'),
            StorageLocation.name.label('location_name'),
            StockLot.name.label('lot_name'),
            effective_status_expression().label('lot_status'),
        )
        .select_from(StorageLocation)
        .join(StockAnchor, StockAnchor.storage_location_id == StorageLocation.id)
        .join(ProductTemplate, ProductTemplate.id == StockAnchor.product_template_id)
        .join(group, true())
        .outerjoin(StockLot, StockLot.id == group.c.lot_id)
        .outerjoin(Uom, Uom.id == ProductTemplate.uom_id)
        .where(
            StorageLocation.organization_id == organization_id,
            StockAnchor.organization_id == organization_id,
        )
        # Grouped by place, because that is how a picker walks the building;
        # the anchor keeps two places or products of one name apart.
        .order_by(
            StorageLocation.name,
            ProductTemplate.name,
            StockAnchor.id,
            StockLot.name,
        )
        .limit(literal(int(limit), literal_execute=True))
        .offset(literal(int(offset), literal_execute=True))
    )
    if not include_empty:
        # A place where nothing stands is passed over before its anchors are
        # read. Goods received through a dock lane leave an anchor there for
        # every product that ever crossed it, all of them empty, and the
        # lanes sort near the top: at a hundred thousand products the first
        # page walked 35 000 empty anchors to find fifty rows.
        stmt = stmt.where(
            select(Item.id)
            .where(
                Item.storage_location_id == StorageLocation.id,
                Item.organization_id == organization_id,
                Item.is_deleted.is_(False),
                _holds(),
            )
            .exists()
        )
    if product_template_id is not None:
        stmt = stmt.where(StockAnchor.product_template_id == product_template_id)
    if location_ids is not None:
        stmt = stmt.where(in_ids(StockAnchor.storage_location_id, location_ids))
    if pattern is not None:
        stmt = stmt.where(
            StockAnchor.product_template_id.in_(
                searched_products(organization_id, pattern)
            ),
            or_(_product_matches(pattern), StockLot.name.ilike(pattern)),
        )

    rows: list[StockQuantRowDTO] = []
    for row in (await db.execute(stmt)).all():
        quantity = row.quantity or Decimal('0')
        reserved = row.reserved or Decimal('0')
        rows.append(
            StockQuantRowDTO(
                id=_group_id(
                    organization_id,
                    row.product_template_id,
                    row.storage_location_id,
                    row.lot_id,
                    row.owner_id,
                ),
                product_template_id=row.product_template_id,
                location_id=row.storage_location_id,
                lot_id=row.lot_id,
                quantity=quantity,
                reserved_quantity=reserved,
                available_quantity=_free_stock(quantity, reserved, row.lot_status),
                product_name=row.product_name,
                uom_symbol=row.uom_symbol,
                location_name=row.location_name,
                lot_name=row.lot_name,
                lot_status=row.lot_status,
                expiry_date=row.expiry_date,
            )
        )
    return rows, int(total)
