"""What the warehouse held on a given day, and what it was worth.

Three questions an auditor, an accountant and an insurer all ask, and the
application could only answer "what is on the shelf now". Everything needed
was already recorded — the ledger holds every movement, the layers hold every
cost — and nothing put them together.

The count runs **backwards** from today's shelves: the current quantity minus
everything that moved after the date. Counting forward from zero is the
obvious way and it lies for every organization that typed its opening stock
straight into the records with no document behind it, which is most of them
on their first day. Today's quantity is what the records hold, summed the
way their view (``stock_quants_from_records``) sums them: the records are the
stock.

The value is a replay of the same FIFO draw the valuation service performs
live: receipts in order, drained by everything that left up to the date.
Deriving it as "sum of inflow layers minus sum of outflow layers" would have
been simpler, and would have disagreed with the figure the dashboard shows,
because outflow layers are priced at the average of the day and the receipts
they drain are not.

Both are one statement, and so is the page of the report built from them. At
a hundred thousand products the count and the draw used to arrive in Python
as hundreds of thousands of rows, and reading them was most of the ten
seconds the screen waited; the database now answers with the page asked for
and the figures of the whole report beside it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Numeric,
    case,
    cast,
    func,
    literal,
    literal_column,
    null,
    select,
    text,
    true,
    union_all,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement, Select

from app.core.contracts import StockAsOfRowDTO
from app.core.db_utils import escape_ilike, in_ids
from app.core.module_ownership import (
    hidden_module_tags_async,
    outside_module_products,
)
from app.core.money import quantise
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove, StockMoveState
from app.models.stock_valuation_layer import StockValuationLayer, layer_dated_at
from app.models.uom import Uom
from app.services.stock_quants_service import searched_products
from app.services.storage._queries import descendant_ids_async
from app.services.storage._relocation import parents_as_of_async, subtree_of


def _moved_at():
    """The date a movement is *about*, not the date its row was written."""
    return func.coalesce(StockMove.completed_at, StockMove.created_at)


def _layer_dated_at():
    """The date a cost layer is *about*, not the date its row was written.

    The document's date, or its UTC write date when there is no document.
    Live FIFO uses the same fallback but casts the timestamp in the session's
    time zone, so the two can order undated layers differently near midnight
    when that zone is not UTC. UTC is explicit here because a cast that read
    the session's ``TimeZone`` would be too session-dependent to be an index key;
    the index over this expression is what lets the read stop at the date
    asked about instead of replaying the organization's whole history.
    """
    return layer_dated_at()


def _settled():
    """Only movements that actually happened.

    The count runs backwards from the current shelves, and the shelves were
    only ever touched by settled movements — so undoing a draft or a
    cancelled row would subtract a quantity nobody ever added. Today every
    row is written ``done`` and the filter changes no answer; the first code
    that writes anything else would silently rewrite last month's report,
    without an error and without a failing test.
    """
    return StockMove.state == StockMoveState.DONE


#: The report reads a large share of the organization's ledger — every
#: movement after the date, every cost layer up to it — and the planner,
#: left to itself, walks those rows through an index one at a time, in the
#: index's order: the movements by product, to group them without hashing,
#: and the layers by date. At a hundred thousand products that visited a
#: table page once per row, hundreds of thousands of times, where reading the
#: same rows by bitmap visits each page once; the report's statement took
#: 1.9 s one way and 1.4 s the other on the same database. Plain index scans
#: are turned off for that one statement and back on after it — local to the
#: transaction, so a statement that fails takes the setting with it, and the
#: indexes still choose the rows (a bitmap is built from them).
#:
#: Each sum per product holds about a hundred thousand groups, and at the
#: default 16 MB every one of them spilled to disk; with 64 MB they stay in
#: memory, another tenth off the statement. As in the reconciliation report,
#: the memory is a ceiling for the transaction, not a reservation, and it is
#: left in place: the setting that changes which plans exist is the one
#: handed back.
_READ_BY_BITMAP = (
    "SELECT set_config('enable_indexscan', 'off', true),"
    " set_config('work_mem', '64MB', true)"
)
_READ_IN_INDEX_ORDER_AGAIN = 'SET LOCAL enable_indexscan TO DEFAULT'


async def ledger_starts_at_async(
    db: AsyncSession, organization_id: UUID
) -> datetime | None:
    """The oldest movement this organization holds, or None if it holds none.

    Everything before it is unknown, not zero. A draft nobody posted does not
    extend the coverage: the report could not reconstruct that far anyway.
    """
    return await db.scalar(
        select(func.min(_moved_at())).where(
            StockMove.organization_id == organization_id,
            _settled(),
        )
    )


def _quantities_as_of(
    organization_id: UUID,
    as_of: datetime,
    location_ids: list[UUID] | None,
    hidden_tags: set[str] | None = None,
    product_pattern: str | None = None,
) -> Select:
    """Quantity per product on the date, summed over the places asked about.

    Today's side counts the live records on a shelf, summed the way
    ``stock_quants_from_records`` sums them — a deleted record holds
    nothing, a NaN quantity is set aside — but read from the records
    directly: the view also builds each group's id and its reservations,
    which a sum per product does not need and which cost three quarters of
    a second at three hundred thousand records. The schema keeps every
    record on a shelf (``items.storage_location_id`` is NOT NULL); the
    filter keeps a shelfless record out of a count the ledger could not undo
    if that ever changes.

    Every movement after the date is undone: what came in is taken back
    out, what left is put back. An internal transfer touches both sides, so
    the organization's total is unchanged and only the places move. Both
    sides are read in one pass over the movements.
    """
    # A product a vertical module owns stays off the report unless the
    # organization shows module data, as its records stay off the products
    # list: the family laptop is not part of a pantry's stock on a date. The
    # report is per product, so the product goes with its records — wholly,
    # movements included, or the movements alone would put it back.
    held = select(
        Item.template_id.label('product_template_id'),
        func.sum(func.nullif(Item.quantity, literal_column("'NaN'::numeric"))).label(
            'quantity'
        ),
    ).where(
        Item.organization_id == organization_id,
        Item.is_deleted.is_(False),
        Item.template_id.is_not(None),
        Item.storage_location_id.is_not(None),
    )
    arrived: ColumnElement[bool] = StockMove.to_location_id.is_not(None)
    left: ColumnElement[bool] = StockMove.from_location_id.is_not(None)
    if location_ids is not None:
        held = held.where(in_ids(Item.storage_location_id, location_ids))
        arrived = in_ids(StockMove.to_location_id, location_ids)
        left = in_ids(StockMove.from_location_id, location_ids)
    held = held.group_by(Item.template_id)

    undone = (
        select(
            StockMove.product_template_id,
            (
                func.sum(case((left, StockMove.quantity), else_=0))
                - func.sum(case((arrived, StockMove.quantity), else_=0))
            ).label('quantity'),
        )
        .where(
            StockMove.organization_id == organization_id,
            _settled(),
            _moved_at() > as_of,
            arrived | left,
        )
        .group_by(StockMove.product_template_id)
    )

    sides = union_all(held, undone).subquery('sides')
    quantities = (
        select(
            sides.c.product_template_id,
            func.sum(sides.c.quantity).label('quantity'),
        )
        .group_by(sides.c.product_template_id)
        .having(func.sum(sides.c.quantity) != 0)
    )
    quantities = quantities.where(
        outside_module_products(
            sides.c.product_template_id, organization_id, hidden_tags
        )
    )
    if product_pattern is not None:
        # The products a typed string reaches, read as the stock list reads
        # it (their own fields and their batches) — narrowing the report to
        # them keeps the figures beside the rows (the total, the unpriced
        # count) about the same products.
        quantities = quantities.where(
            sides.c.product_template_id.in_(
                searched_products(organization_id, product_pattern)
            )
        )
    return quantities


def _values_as_of(organization_id: UUID, as_of: datetime, org_currency: str) -> Select:
    """Value per product on the date, replaying the FIFO draw of the layers.

    One row per product with a receipt up to the date: ``value``, what its
    priced receipts still hold, and ``priced``, whether any of its receipts
    carries a cost at all. ``value`` is NULL for a product whose shelf holds
    nothing a cost is known for: 0.00 in that cell is a valuation nobody
    performed.

    The draw takes what left up to the date from the receipts in order, so a
    receipt still holds whatever its running total exceeds what left, up to
    its own quantity — ``least(quantity, received - delivered)`` — which is
    the replay done row by row, written as a window over the receipts.

    A receipt nobody priced — an ``unknown`` layer at 0.00 — still takes its
    turn in the draw, because the live drain takes goods from it like from
    any other receipt. What is left of it adds nothing: its quantity is real,
    its figure is not a cost (:attr:`StockValuationLayer.carries_a_cost`). So
    a product is worth what its priced layers still hold on the date, which
    is the figure the dashboard and the list footer give for the same layers.

    Layers are cut on the date they are about — their document's date, and
    their write date only when there is no document — so a receipt booked
    today for last week lands in last week, on both sides of the report.
    Ordering matches the live FIFO down to the tiebreakers, so replaying the
    draw here and drawing it there cannot reach two different answers. A
    receipt priced in another currency is left out of the draw; the report
    counts those apart.
    """
    layer = StockValuationLayer
    delivered = (
        select(
            layer.product_template_id,
            func.sum(layer.quantity).label('delivered'),
        )
        .where(
            layer.organization_id == organization_id,
            layer.direction == 'OUT',
            _layer_dated_at() <= as_of,
        )
        .group_by(layer.product_template_id)
        .subquery('delivered')
    )
    receipts = (
        select(
            layer.product_template_id,
            layer.quantity,
            layer.unit_cost,
            layer.carries_a_cost.label('priced'),
            func.sum(layer.quantity)
            .over(
                partition_by=layer.product_template_id,
                order_by=(
                    _layer_dated_at().asc(),
                    layer.created_at.asc(),
                    layer.id.asc(),
                ),
            )
            .label('received'),
        )
        .where(
            layer.organization_id == organization_id,
            layer.direction == 'IN',
            _layer_dated_at() <= as_of,
            (layer.currency.is_(None)) | (layer.currency == org_currency),
        )
        .subquery('receipts')
    )
    still_held = func.least(
        receipts.c.quantity,
        receipts.c.received - func.coalesce(delivered.c.delivered, 0),
    )
    return (
        select(
            receipts.c.product_template_id,
            func.sum(still_held * receipts.c.unit_cost)
            .filter(receipts.c.priced & (still_held > 0))
            .label('value'),
            func.bool_or(receipts.c.priced).label('priced'),
        )
        .select_from(
            receipts.outerjoin(
                delivered,
                delivered.c.product_template_id == receipts.c.product_template_id,
            )
        )
        .group_by(receipts.c.product_template_id)
    )


async def _foreign_receipts_async(
    db: AsyncSession, organization_id: UUID, as_of: datetime, org_currency: str
) -> int:
    """Receipts up to the date priced in a currency that is not the
    organization's — left out of the draw, because two currencies do not add."""
    return int(
        await db.scalar(
            select(func.count()).where(
                StockValuationLayer.organization_id == organization_id,
                StockValuationLayer.direction == 'IN',
                _layer_dated_at() <= as_of,
                StockValuationLayer.currency.is_not(None),
                StockValuationLayer.currency != org_currency,
            )
        )
        or 0
    )


@dataclass(frozen=True)
class StockAsOfPage:
    """One page of the report, and the figures of the whole of it.

    ``total`` counts every row, ``unpriced`` the rows whose value nobody can
    state and ``total_value`` adds the value of every row, whichever page
    ``rows`` holds: the reader of a page reads the warehouse's figures
    under it, not the page's.
    """

    rows: list[StockAsOfRowDTO]
    total: int
    unpriced: int
    total_value: Decimal | None
    excluded: int


async def report_async(
    db: AsyncSession,
    organization_id: UUID,
    as_of: datetime,
    *,
    location_id: UUID | None = None,
    org_currency: str,
    has_layers: bool,
    limit: int | None = None,
    offset: int = 0,
    search: str | None = None,
) -> StockAsOfPage:
    """The rows of one organization on one date, ``limit`` of them from
    ``offset`` in name order — all of them when ``limit`` is None, as the
    files want them.

    One statement answers the page and the figures of the whole report
    beside it, so the screen's page costs what the count and the draw cost
    in the database, not what reading a hundred thousand rows costs here.
    """
    location_ids: list[UUID] | None = None
    if location_id is not None:
        # The place as it stood on the date: a location that physically
        # moved in since counts where it was then, not where it is now.
        # Shelf ids never change, so once the right shelves are named the
        # backwards count below is the same as for any other place.
        parents_then = await parents_as_of_async(db, organization_id, as_of)
        location_ids = (
            subtree_of(parents_then, location_id)
            if parents_then is not None
            else [
                location_id,
                *await descendant_ids_async(db, organization_id, location_id),
            ]
        )

    # A location filter narrows the quantities but not the layers: those are
    # kept per product, not per shelf, so a value for one aisle could only be
    # an apportionment — and an apportionment is an estimate wearing the
    # clothes of a figure. The report says nothing instead.
    priced = has_layers and location_id is None

    hidden_tags = await hidden_module_tags_async(db, organization_id)
    quantities = _quantities_as_of(
        organization_id,
        as_of,
        location_ids,
        hidden_tags,
        f'%{escape_ilike(search)}%' if search else None,
    ).cte('quantities')
    if priced:
        values = _values_as_of(organization_id, as_of, org_currency).cte('stock_values')
        rows = (
            select(
                quantities.c.product_template_id,
                quantities.c.quantity,
                # The money leaves with the two places money has here.
                # Quantity carries three decimals and a unit cost four, so
                # their product arrives with seven — and a reader comparing
                # exports has to be able to tell an exact value from a
                # rounded one. The total adds the rounded figures the rows
                # print, half away from zero as ``quantise`` rounds.
                func.round(values.c.value, 2).label('value'),
            )
            .select_from(
                quantities.outerjoin(
                    values,
                    values.c.product_template_id == quantities.c.product_template_id,
                )
            )
            .cte('report_rows')
        )
        any_priced: ColumnElement[Any] = select(
            func.bool_or(values.c.priced)
        ).scalar_subquery()
    else:
        rows = select(
            quantities.c.product_template_id,
            quantities.c.quantity,
            cast(null(), Numeric).label('value'),
        ).cte('report_rows')
        any_priced = literal(False)

    figures = select(
        func.count().label('total'),
        func.count(rows.c.value).label('stated'),
        func.sum(rows.c.value).label('total_value'),
        any_priced.label('any_priced'),
    ).subquery('figures')
    ordered = (
        select(
            rows.c.product_template_id,
            rows.c.quantity,
            rows.c.value,
            ProductTemplate.name,
            Uom.symbol,
        )
        .select_from(
            rows.outerjoin(
                ProductTemplate, ProductTemplate.id == rows.c.product_template_id
            ).outerjoin(Uom, Uom.id == ProductTemplate.uom_id)
        )
        # Name order as Python's ``str.lower`` sorts it: by code point,
        # whatever collation the database was created with.
        .order_by(
            func.lower(func.coalesce(ProductTemplate.name, '')).collate('C'),
            rows.c.product_template_id,
        )
        # Rendered, not bound — a bound LIMIT lets a generic plan guess the
        # page size (see ``stock_quants_service``).
        .offset(literal(int(offset), literal_execute=True))
    )
    if limit is not None:
        ordered = ordered.limit(literal(int(limit), literal_execute=True))
    page = ordered.lateral('page')

    await db.execute(text(_READ_BY_BITMAP))
    result = (
        await db.execute(
            select(*figures.c, *page.c).select_from(figures.outerjoin(page, true()))
        )
    ).all()
    await db.execute(text(_READ_IN_INDEX_ORDER_AGAIN))
    head = result[0]
    if not head.total:
        return StockAsOfPage(
            rows=[],
            total=0,
            unpriced=0,
            total_value=(quantise(Decimal('0')) if priced else None),
            excluded=0,
        )

    excluded = (
        await _foreign_receipts_async(db, organization_id, as_of, org_currency)
        if priced
        else 0
    )
    # A product is worth what its priced layers still hold; one whose shelf
    # holds nothing anybody priced is worth nothing anybody can state, and
    # the two must not print the same.
    page_rows = [
        StockAsOfRowDTO(
            product_template_id=row.product_template_id,
            product_name=row.name,
            uom_symbol=row.symbol,
            quantity=row.quantity,
            value=row.value,
        )
        for row in result
        if row.product_template_id is not None
    ]

    # The total adds what is known and the rows say what is not, as the list
    # footer does. But an organization that never named a price, in any
    # currency, has a ledger full of quantities and not one cost in it: a
    # total there is not 0.00, it is no valuation at all.
    total_value: Decimal | None = (
        quantise(head.total_value or Decimal('0'))
        if priced and (head.any_priced or excluded)
        else None
    )
    return StockAsOfPage(
        rows=page_rows,
        total=head.total,
        unpriced=head.total - head.stated,
        total_value=total_value,
        excluded=excluded,
    )
