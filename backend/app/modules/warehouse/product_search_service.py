"""Product search service for warehouse module."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ItemDTO, ProductTemplateDTO


async def search_products_async(
    db: AsyncSession,
    org_id: UUID,
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Async product search with priority ranking via CoreAPI."""
    from app.core.public_api import core_api

    q = query.strip()
    if not q:
        return []

    templates = await core_api.product_templates.search_ranked_async(
        db, org_id, q, limit=limit
    )
    # One lookup per distinct unit, not per hit: a page of cards mostly
    # shares a handful of them.
    symbols: dict[UUID, str | None] = {}
    for uom_id in {t.uom_id for t in templates if t.uom_id}:
        uom = await core_api.uoms.get_async(db, uom_id, org_id)
        symbols[uom_id] = uom.symbol if uom else None
    prices = await _purchase_prices_async(db, org_id, [t.id for t in templates])
    return [
        _template_dto_to_dict(
            t, symbols.get(t.uom_id) if t.uom_id else None, prices.get(t.id)
        )
        for t in templates
    ]


async def _purchase_prices_async(
    db: AsyncSession, org_id: UUID, template_ids: list[UUID]
) -> dict[UUID, Decimal]:
    """The latest purchase price on record for each template that has one.

    The price lives on the stock records, not on the template; a document
    line that buys the product again starts from what it last cost.
    """
    from app.core.public_api import core_api

    if not template_ids:
        return {}
    grouped = await core_api.items.list_with_template_async(db, org_id, template_ids)
    prices: dict[UUID, Decimal] = {}
    for tid, items in grouped.items():
        newest: tuple[datetime, Decimal] | None = None
        for item in items:
            if item.purchase_price is None:
                continue
            if newest is None or item.created_at > newest[0]:
                newest = (item.created_at, item.purchase_price)
        if newest is not None:
            prices[tid] = newest[1]
    return prices


async def search_stock_items_async(
    db: AsyncSession,
    org_id: UUID,
    query: str,
    location_id: UUID | None = None,
    limit: int = 10,
    merge: bool = False,
) -> list[dict[str, Any]]:
    """Search the stock on hand, narrowed to *location_id* when there is one.

    The location is a filter, not the reason to search stock at all: a scrap
    document names no shelf of its own, and its search used to fall back to
    the catalogue for want of a location, handing back entries the stock
    executors could do nothing with.

    The location is a zone or a shelf. A shelf is exact: it holds its own
    records and nothing below it. A zone (a location with locations under
    it) offers the stock of its whole subtree, because a document naming it
    takes from the shelves below, each line on the shelf its record stands
    on. Either way each result names the shelf it stands on, which is what
    the line will be pinned to.

    Each result names the shelf it stands on. Without a location the search
    covers the whole organisation, so two hits can share a name and a
    best-before while sitting on different shelves — without the shelf in the
    row, the only thing telling them apart was the quantity.

    Records nothing on the row can tell apart — same product, same shelf, no
    date, no serial — collapse into one hit carrying the shelf's total, the
    number the engine works with. The executor checks and pulls by product
    and shelf (FEFO across records), so interchangeable records are one row
    of stock, not several identical choices.

    Records with nothing on them are not offered. A line built on an empty
    record starts life promising goods that are not there; a shelf can still
    serve a take via its other records, but this row has nothing to give the
    picker standing in front of it.

    ``merge`` folds records nothing on the row can tell apart into one hit —
    but only for the documents whose executor pulls across records. A
    dispatch and a scrap answer with one row per shelf; a transfer moves a
    single record and gets the rows one by one, because a merged row
    promising seven would move whichever record the line named and leave
    the other behind.
    """
    from app.core.public_api import core_api

    q = query.strip()
    if not q:
        return []

    storage_ids = None
    if location_id is not None:
        below = await core_api.locations.descendant_ids_async(db, org_id, location_id)
        storage_ids = [location_id, *below]

    if merge:
        # The summing happens in SQL, before the page is cut — a Python
        # merge after LIMIT made the shelf total depend on the page size.
        summary = await core_api.items.search_stock_summary_async(
            db,
            org_id,
            storage_ids=storage_ids,
            search=q,
            quantity_above=Decimal('0'),
            limit=limit,
        )
        rows = [
            _item_dto_to_dict(item, offered=offered, merged=merged)
            for item, offered, merged in summary
        ]
    else:
        page = await core_api.items.search_cursor_paginated_async(
            db,
            org_id,
            storage_ids=storage_ids,
            search=q,
            # In SQL, before the LIMIT cut — see the floor's own comment.
            quantity_above=Decimal('0'),
            limit=limit,
        )
        rows = [_item_dto_to_dict(i) for i in page.items]
    rows = await _apply_shelf_claims_async(db, org_id, rows, merge=merge)
    for row in rows:
        row.pop('merged', None)  # routing fact, not part of the answer
    return rows


async def _apply_shelf_claims_async(
    db: AsyncSession,
    org_id: UUID,
    rows: list[dict[str, Any]],
    *,
    merge: bool,
) -> list[dict[str, Any]]:
    """Drop shelves whose stock is spoken for, and re-price rows to match.

    Reservations claim stock before the goods move, and the claim a new
    line implies is refused at confirmation — a row promising "in stock"
    that cannot be reserved sends the picker to a shelf that was never
    going to serve this document. A shelf the records' view has no group
    for at all has no reservation machinery behind it and keeps its rows.

    Under the pulling executors (``merge``) every row answers for what it
    can actually serve: a merged row is capped by both its group's total
    (the undated records only — the dated ones travel as rows of their own)
    and the shelf's claimable pool, which covers every record standing
    here. The pool belongs to the shelf, so it is handed out to the rows
    in offering order — the sum of the offered rows never exceeds it, and
    a document built from the whole offer reserves what it names. Ten
    gross with three spoken for builds a document for seven, not one that
    dies at confirmation. A transfer dialog (no merge) keeps the gross
    record count: its executor moves exactly the record the line names,
    and reservations are tracked per shelf, not per record.
    """
    from app.core.public_api import core_api

    template_ids = list(
        {UUID(r['product_template_id']) for r in rows if r['product_template_id']}
    )
    if not template_ids:
        return rows

    quants = await core_api.stock.list_quants_async(
        db, org_id, product_template_ids=template_ids
    )
    seen: set[tuple[str, str]] = set()
    claimable: dict[tuple[str, str], Decimal] = {}
    for quant in quants:
        key = (str(quant.product_template_id), str(quant.location_id))
        seen.add(key)
        claimable[key] = claimable.get(key, Decimal('0')) + (
            quant.quantity - quant.reserved_quantity
        )

    def _keep(row: dict[str, Any]) -> bool:
        if not row['product_template_id']:
            return True
        key = (row['product_template_id'], row['location_id'])
        return key not in seen or claimable[key] > 0

    kept = [r for r in rows if _keep(r)]
    if merge:
        # The group's total covers only the records nothing tells apart; the
        # shelf's claimable pool covers every record standing here, dated
        # ones included — and those travel as rows of their own. The pool is
        # handed out in FEFO order — earliest best-before first, undated
        # records last, since nothing on them can spoil — not re-read per
        # row: a cap that re-read it promised the same stock once per row,
        # so four rows under a pool of two offered eight and a document
        # built from that offer died at confirmation. A row the rows before
        # it drained offers nothing and is not offered at all — a deliberate
        # shape: the picker offers rows a document can book, and a zero row
        # would invite a line that reserves nothing. The handout order is
        # FEFO too: under a shortage the row that survives is the one the
        # picker has to walk to anyway, never whichever record the query
        # happened to return first.
        for row in sorted(kept, key=lambda r: r.get('expiry_date') or '9999-12-31'):
            key = (row['product_template_id'], row['location_id'])
            if key not in seen:
                continue
            offered = min(row['available_quantity'], claimable[key])
            claimable[key] -= offered
            row['available_quantity'] = offered
        return [
            row
            for row in kept
            if row['available_quantity'] is None or row['available_quantity'] > 0
        ]
    return kept


def _template_dto_to_dict(
    tpl: ProductTemplateDTO,
    uom_symbol: str | None,
    purchase_price: Decimal | None = None,
) -> dict[str, Any]:
    return {
        'product_template_id': str(tpl.id),
        'item_id': None,
        'available_quantity': None,
        'name': tpl.name,
        'sku': tpl.sku,
        'barcode': tpl.barcode,
        'brand': tpl.brand,
        'uom_id': str(tpl.uom_id) if tpl.uom_id else None,
        'uom_symbol': uom_symbol,
        'purchase_price': purchase_price,
        'image_url': tpl.image_url,
        'is_stub': bool(tpl.meta_data.get('is_stub', False))
        if tpl.meta_data
        else False,
    }


def _item_dto_to_dict(
    item: ItemDTO,
    offered: Decimal | None = None,
    merged: bool = False,
) -> dict[str, Any]:
    return {
        'product_template_id': str(item.template_id) if item.template_id else None,
        'item_id': str(item.id),
        'available_quantity': offered if offered is not None else item.quantity,
        'merged': merged,
        # A per-record row says when its record landed — on a shelf of
        # unmarked twins the quantity was the only thing telling them
        # apart. A merged row is a shelf total, not a record, so it names
        # no date at all.
        'created_at': None if merged else item.created_at,
        'name': item.name,
        'sku': None,
        'barcode': item.barcode,
        'brand': item.brand,
        'uom_id': str(item.uom_id) if item.uom_id else None,
        'uom_symbol': item.uom_symbol or (item.uom.symbol if item.uom else None),
        'image_url': None,
        'is_stub': False,
        'expiry_date': item.expiry_date.isoformat() if item.expiry_date else None,
        'serial_number': item.serial_number,
        'location_id': str(item.location_id),
        'location_name': item.location_name,
    }
