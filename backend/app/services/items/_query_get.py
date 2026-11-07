"""Single-item get queries for the items service.

This module groups the ``get_*_by_id`` family: functions that fetch one
or a few specific items by primary key or unique identifier. Listing /
counting / lookup-by-barcode queries live in ``_query_listing.py`` and
``_query_lookup.py``. Specialized view queries (expiring, low_stock,
archived, 404 variants) live in ``_query_special.py``.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, distinct, func, literal, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, aliased, lazyload, selectinload

from app.core.db_utils import in_ids, paginate
from app.core.exceptions import NotFoundException
from app.core.read_scope import keep_loaded
from app.core.txn_memo import records_locked
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.uom import Uom, UomCategory
from app.services.analytics._common import (
    VALUE_FROM_LAYERS,
    VALUE_FROM_PURCHASE_PRICE,
    VALUE_NOT_AVAILABLE_UNDER_FILTER,
    org_currency_filter,
)
from app.services.items.weight import (
    CONTINUOUS_UOM_CATEGORIES,
    REFERENCE_UNITS_PER_STORED_UNIT,
    VOLUME_UOM_CATEGORY,
)
from app.services.storage._queries import get_organization_storage_ids

from ._loaded import give_the_card_and_category
from ._search_terms import item_matches_text


def _apply_item_filters(  # noqa: C901 - the filter list is the list's contract
    query,
    *,
    organization_id: UUID | None = None,
    user_organization_id: UUID | None = None,
    user_storage_ids: list[UUID] | None = None,
    scope_organization_id: UUID | None = None,
    is_deleted: bool = False,
    location_usage: str | None = 'internal',
    include_empty: bool = False,
    storage_id: UUID | None = None,
    category_id: UUID | None = None,
    context_tag: str | None = None,
    claimed_tags: set[str] | None = None,
    search: str | None = None,
    expiring_days: int | None = None,
    only_expired: bool = False,
    only_low_stock: bool = False,
    needs_attention: bool = False,
    source_document_id: UUID | None = None,
    template_ids: list[UUID] | None = None,
    today: date | None = None,
    short_products_listed: bool = False,
):
    """Every narrowing the items list supports, applied to any ``Item`` select.

    The list and the aggregates endpoint share this so the footer sums can
    never drift from the rows above them: both start from
    ``Item`` joined to ``StorageLocation`` and take the same clauses.

    Two access modes, told apart by which id is given:

    - *organization_id* is the org mode: the scope is every location the
      organization owns, read through the join.
    - *user_organization_id* is tenancy for the user mode: the scope is
      every location the reader's organization has, named by the
      organization rather than listed. A list of every location id was the
      scope once, and at a few thousand locations it steered the planner
      onto ``ix_items_storage_location_id`` across every record of the
      organization (to remove nothing), while ``ix_items_org_created``
      starts with the organization and serves a page by reading the page;
      past 32 767 locations the list could not even be bound to one
      statement. ``user_storage_ids`` is the scope only for a caller that
      names no organization.

    *scope_organization_id* is neither: it narrows nothing on its own and
    names the organization whose stock a filter has to look at as a whole.
    Only ``only_low_stock`` needs it, because a threshold belongs to a
    product rather than to a record, so answering it means summing beyond
    the rows this query is about. In the user mode the caller derives it
    from the same place it derives the storage scope.

    *short_products_listed* is what ``only_low_stock`` means to the shelves,
    for a caller that has already turned that filter into ``template_ids``.
    """

    if organization_id is not None:
        query = query.where(
            StorageLocation.organization_id == organization_id,
            Item.is_deleted == is_deleted,
        )
    elif user_organization_id is not None:
        query = query.where(
            Item.organization_id == user_organization_id,
            StorageLocation.organization_id == user_organization_id,
            Item.is_deleted.is_(False),
        )
    else:
        query = query.where(
            in_ids(Item.storage_location_id, user_storage_ids or []),
            Item.is_deleted.is_(False),
        )

    # The organization a product's threshold is measured in — see
    # *scope_organization_id* above.
    stock_org_id = organization_id or user_organization_id or scope_organization_id

    if location_usage:
        if include_empty:
            # "Show used up": a record with nothing left joins the rows
            # wherever it sits. Consuming the last unit files it under the
            # virtual Consumed location (usage CUSTOMER), so the internal
            # default hid it and the one way back ran through the storage
            # tree — the list can answer for itself instead.
            query = query.where(
                or_(
                    StorageLocation.usage == location_usage,
                    Item.quantity <= 0,
                )
            )
        elif (
            (needs_attention or only_low_stock or short_products_listed)
            and location_usage == 'internal'
            and stock_org_id
        ):
            # A product used up to nothing is short, and has no record left
            # on a shelf: it joins by the record it was used up from, or the
            # count above the list names one product more than the rows.
            from app.services.items.low_stock import used_up_short_product_records

            query = query.where(
                or_(
                    StorageLocation.usage == location_usage,
                    Item.id.in_(
                        used_up_short_product_records(stock_org_id, claimed_tags)
                    ),
                )
            )
        else:
            query = query.where(StorageLocation.usage == location_usage)

    if storage_id:
        query = query.where(Item.storage_location_id == storage_id)
    if category_id:
        query = query.where(Item.category_id == category_id)

    if context_tag:
        from app.core.module_ownership import items_with_context_tag

        query = query.where(items_with_context_tag(context_tag))

    if claimed_tags:
        from app.core.module_ownership import unclaimed_by_a_module

        query = query.where(unclaimed_by_a_module(claimed_tags))

    if search:
        query = query.where(
            item_matches_text(search, organization_id or user_organization_id)
        )

    if expiring_days is not None:
        from app.services.items.expiry import is_expiring_soon

        # Horizon *and* floor. This copy had only the horizon, so the list
        # behind the "expiring soon" tile also carried items already past
        # their date and reported one more than the tile did. The horizon
        # counts from *today* — the caller's organization's day.
        query = query.where(is_expiring_soon(today, days=expiring_days))

    if only_expired:
        from app.services.items.expiry import is_expired

        query = query.where(is_expired(today))

    if only_low_stock:
        # The threshold belongs to the product, so what is short is a
        # product; the rows this list then shows are that product's, all
        # of them. Comparing the threshold against each row separately
        # made a well-spread stock look like several shortages, and
        # disagreed with the purchasing engine by the number of places
        # the product was kept in. The rule lives in one module now —
        # `app.services.items.low_stock`.
        from app.services.items.low_stock import low_stock_template_ids

        # No organization means no scope either: the branch above has already
        # narrowed to an empty list of locations, so the query answers nothing
        # whatever this filter would have said.
        if stock_org_id is not None:
            query = query.where(
                Item.template_id.in_(low_stock_template_ids(stock_org_id))
            )

    if needs_attention:
        # What the "needs attention" number counts, as one list: expired,
        # expiring inside the horizon, or a record of a product that reached
        # its threshold. The tiles that show the number used to open the
        # whole list, where the few it counted were nowhere marked; the
        # three chips combine with AND, so none of them could answer an OR.
        # The low-stock half is the count's own rule, module scoping and all.
        from app.services.items.expiry import (
            DEFAULT_EXPIRING_SOON_DAYS,
            is_expired,
            is_expiring_soon,
        )
        from app.services.items.low_stock import low_stock_template_ids

        reasons = [
            is_expired(today),
            is_expiring_soon(today, days=DEFAULT_EXPIRING_SOON_DAYS),
        ]
        if stock_org_id is not None:
            reasons.append(
                Item.template_id.in_(
                    low_stock_template_ids(stock_org_id, claimed_tags or None)
                )
            )
        query = query.where(or_(*reasons))

    if source_document_id:
        query = query.where(Item.source_document_id == source_document_id)
    # Neutral on purpose: Core narrows to a set of templates, and whoever asks
    # decides what the set means. "Products with a formula" is maker's
    # question, and Core does not need to learn it.
    if template_ids:
        query = query.where(in_ids(Item.template_id, template_ids))

    return query


async def count_needing_attention_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    claimed_tags: set[str] | None,
    today: date,
) -> int:
    """How many rows the "needs attention" list has: the number that opens it.

    The shares beside it cannot be summed into this. ``low_stock`` counts
    products and the list shows their records, and a record can be both dated
    and short, so a heading of 14 opened 17 rows.
    """
    query = _apply_item_filters(
        select(func.count(Item.id))
        .select_from(Item)
        .join(StorageLocation, Item.storage_location_id == StorageLocation.id),
        user_organization_id=organization_id,
        claimed_tags=claimed_tags,
        needs_attention=True,
        today=today,
    )
    return await db.scalar(query) or 0


def get_items(
    db: Session,
    user=None,
    storage_id: UUID | None = None,
    category_id: UUID | None = None,
    context_tag: str | None = None,
    claimed_tags: set[str] | None = None,
    location_usage: str | None = 'internal',
    include_empty: bool = False,
    search: str | None = None,
    expiring_days: int | None = None,
    only_expired: bool = False,
    only_low_stock: bool = False,
    needs_attention: bool = False,
    low_stock_threshold: float = 1.0,
    offset: int = 0,
    limit: int = 100,
    user_storage_ids: list[UUID] | None = None,
    user_organization_id: UUID | None = None,
    sort_by: str | None = None,
    sort_order: str = 'asc',
    source_document_id: UUID | None = None,
    template_ids: list[UUID] | None = None,
    organization_id: UUID | None = None,
    is_deleted: bool = False,
    eager_load: bool = True,
    today: date | None = None,
    count_cap: int | None = None,
) -> tuple[list[Item], int]:
    """Fetch items with advanced server-side filtering and pagination.

    Supports two access modes:
      - **User-based** (default): pass ``user`` or ``user_storage_ids``,
        and ``user_organization_id`` so the page can be served by the
        organization's own index rather than sorted in memory.
      - **Org-based**: pass ``organization_id`` to scope by org directly.

    Text search uses ILIKE across ``name``, ``brand``, ``barcode``, ``label_code``.

    *today* is the organization's own day, resolved by the async caller
    (the sync body has no org clock to ask) — expiry filters cut on it.

    *count_cap* stops the count there (``db_utils.paginate``); the caller
    hands the same cap to ``from_slice``.
    """
    if (
        user_storage_ids is None
        and organization_id is None
        and user_organization_id is None
    ):
        if user and user.organization_id:
            user_storage_ids = get_organization_storage_ids(db, user.organization_id)
        else:
            user_storage_ids = []
    # The organization a whole-product question has to be asked about. The
    # storage scope above cannot answer one: a threshold belongs to the
    # product, so "is it running out" is a sum over places this list may
    # not be showing.
    scope_organization_id = (
        organization_id
        or user_organization_id
        or (user.organization_id if user else None)
    )

    short_products_listed = False
    if only_low_stock and scope_organization_id is not None:
        # The short products are asked for once and handed to the page and
        # its count as a set: asked inside both statements, the sum over
        # every record of the organization ran twice per page.
        from app.services.items.low_stock import low_stock_template_ids

        short = set(db.scalars(low_stock_template_ids(scope_organization_id)).all())
        template_ids = (
            [tid for tid in template_ids if tid in short]
            if template_ids
            else list(short)
        )
        if not template_ids:
            return [], 0
        only_low_stock = False
        short_products_listed = True

    query = select(Item).join(StorageLocation)

    if eager_load:
        # Loaded for the page's rows after the page is cut, not joined into
        # the statement that picks them: joined, a search matching thousands
        # of records carried four tables' columns for every match into the
        # sort that keeps fifty.
        query = query.options(
            selectinload(Item.category),
            selectinload(Item.storage_location),
            selectinload(Item.uom),
            selectinload(Item.template),
        )

    query = _apply_item_filters(
        query,
        organization_id=organization_id,
        user_organization_id=user_organization_id,
        user_storage_ids=user_storage_ids,
        scope_organization_id=scope_organization_id,
        is_deleted=is_deleted,
        location_usage=location_usage,
        include_empty=include_empty,
        storage_id=storage_id,
        category_id=category_id,
        context_tag=context_tag,
        claimed_tags=claimed_tags,
        search=search,
        expiring_days=expiring_days,
        only_expired=only_expired,
        only_low_stock=only_low_stock,
        needs_attention=needs_attention,
        short_products_listed=short_products_listed,
        source_document_id=source_document_id,
        template_ids=template_ids,
        today=today,
    )

    # Three alternatives to the default ``created_at``; only ``name`` gets an
    # index of its own — a decision with a reason, not an omission.
    #
    # An index in this list's shape is paid on every write to the column it
    # orders. ``quantity`` and ``expiry_date`` are rewritten by stock
    # movements and by edits, and a stock movement is the hottest write path
    # in the application; the list's default order is served by
    # ``ix_items_org_created`` precisely because ``created_at`` is written
    # once and never rewritten, so that index is paid once per record. What
    # the two mutable columns already have is enough to leave alone: the FEFO
    # index orders the expiry walk, and the quantity index — kept for the
    # stock filters, not for this list — is walked in quantity order. The
    # expiry sort is on the effective date (the batch's or, if earlier, the
    # use-by given at opening), an expression no plain index answers, so it
    # sorts the reader's own rows. ``name`` can be edited, but sorting every
    # record of a large organization by it took three seconds a page, so
    # ``ix_items_org_name`` is worth its write cost and is walked instead.
    _sort_cols = {
        'name': Item.name,
        'quantity': Item.quantity,
        'expiry_date': Item.effective_expiry_date,
    }
    sort_key = sort_by or 'created_at'
    order_col = _sort_cols.get(sort_key, Item.created_at)

    ordering = order_col.desc() if sort_order == 'desc' else order_col.asc()
    # ``expiry_date`` is the one sortable column that can hold NULL, and a
    # row without a date belongs at the end either way. On the other three
    # the clause is not neutral: the column is NOT NULL, so ``NULLS LAST``
    # asks for an order the DESC index cannot provide and Postgres drops
    # the index for an in-memory sort to honour a distinction that cannot
    # arise.
    if sort_key == 'expiry_date':
        ordering = ordering.nullslast()
    query = query.order_by(ordering)

    return paginate(db, query, limit=limit, offset=offset, count_cap=count_cap)


@dataclass(frozen=True)
class ItemTotals:
    """What the list footer shows for the whole filtered set."""

    count: int
    #: How many products those records are of: the unit a short product is
    #: counted in, so a list of its records can say how the two numbers meet.
    product_count: int
    total_weight: float
    #: Litres, summed separately from ``total_weight``: a litre is not a
    #: kilogram, and one figure labelled kilograms read 2 l of milk as 2 kg.
    #: Each line lands in the sum its own unit names, by the rule
    #: ``Item.total_weight_unit`` applies per row.
    total_volume: float
    #: None when a filter narrowed the set and the organization prices from
    #: the cost ledger: the ledger has no value for a slice (see
    #: ``get_items_aggregates``), and the footer says so instead.
    total_value: float | None
    value_source: str
    unpriced_count: int
    #: True when the set the footer describes leaves out the items a
    #: vertical module owns (the list's default view excludes them while
    #: the statistics tile sums the whole ledger) — the two figures agree
    #: to disagree only while the footer names the difference.
    excludes_module_items: bool = False
    #: True when the ledger holds open cost layers for products this list
    #: has no record of. The footer clamps each product to what the list
    #: can see, so such a layer reaches the statistics tile and not this
    #: sum — the second reason the two numbers differ, and the one that
    #: used to be left unexplained while the module sentence implied it
    #: accounted for the whole gap.
    excludes_unlisted_layers: bool = False


def get_items_aggregates(
    db: Session,
    *,
    user_storage_ids: list[UUID] | None = None,
    user_organization_id: UUID | None = None,
    location_usage: str | None = 'internal',
    include_empty: bool = False,
    storage_id: UUID | None = None,
    category_id: UUID | None = None,
    context_tag: str | None = None,
    claimed_tags: set[str] | None = None,
    search: str | None = None,
    expiring_days: int | None = None,
    only_expired: bool = False,
    only_low_stock: bool = False,
    needs_attention: bool = False,
    source_document_id: UUID | None = None,
    template_ids: list[UUID] | None = None,
    today: date | None = None,
    has_layers: bool = False,
    org_currency: str | None = None,
) -> ItemTotals:
    """Count, total weight and total value over the whole filtered set.

    The list paginates, so the page footer cannot be summed from its rows.
    The filter comes from ``_apply_item_filters`` — the same function the
    list uses — so the totals describe exactly the rows the list would show
    with the same filters and no pagination.

    ``user_organization_id`` is tenancy, not a filter, exactly as it is for
    the list: it names the organization whose locations ``user_storage_ids``
    already are, and it must be given wherever the list gives it, or the
    footer would count the rows the list no longer shows.

    The value is read where the statistics and the stock-as-of report read
    it. An organization that keeps a cost ledger (*has_layers*) is valued
    from its receipt layers: each record at its product's layer-average
    rate — but only for the whole organization, unfiltered. The layers
    know products, not shelves, so the rates are organization-wide, and a
    slice with rows removed, priced with them, would carry money its own
    shelves never earned; under such a filter the ledger figure is
    withheld — ``total_value`` comes back None and ``value_source`` says
    the slice has no ledger value. A value that only ADDS rows beyond the
    default view (every usage instead of the internal one, the emptied
    records) keeps the figure: the rates price products, and every
    product in the wider set is still priced at its own organization's
    rate. A receipt posted by document then moves the
    unfiltered footer by what the goods cost, freight included, and a
    price corrected on a card does not; it used to be the other way round.
    An organization without a ledger is valued from the price on each
    record — a figure that can follow a filter, because the price sits on
    the very rows the filter keeps — and ``value_source`` says which of
    the sources the reader is looking at.

    ``unpriced_count`` is how many of the counted records the sum could not
    price — no cost history, or no price on the card, or a price in a
    currency other than the organization's (two currencies have no sum;
    the statistics tile applies the same policy and counts what it leaves
    out). A footer that summed them as nothing said "worth 0.00" about
    stock nobody had valued.

    Weight is the ADR-015 line weight, derived not stored: a line counted in
    a continuous unit (grams, millilitres) carries its weight in the quantity
    itself; a line counted in pieces takes the unit weight from its product
    template. Both branches divide by the reference-unit factor, matching
    ``app.services.items.weight``. The result leaves in two sums, never one:
    kilograms in ``total_weight``, litres in ``total_volume``, each line
    falling to the sum its own unit names by the same rule
    ``Item.total_weight_unit`` applies per row. A single figure summed both
    and read 2 l of milk as 2 kg.
    """
    # Whether the request removes any row the default view holds. The ledger
    # rates are organization-wide (the layers know products, not shelves), so
    # the moment rows are removed, pricing the slice from the ledger would
    # price it at rates the rest of the organization earned. What removes
    # rows and what only adds them are two different questions, answered in
    # two named groups so the next parameter has to pick a side: a value
    # that removes rows withholds the ledger figure; a value that only adds
    # rows beyond the default view (a wider usage, the emptied records)
    # keeps it — the rates still describe every product in the wider set.
    narrowing = any(
        (
            storage_id is not None,
            category_id is not None,
            context_tag is not None,
            bool(search),
            expiring_days is not None,
            only_expired,
            only_low_stock,
            needs_attention,
            source_document_id is not None,
            bool(template_ids),
            # Only a usage other than the default internal one removes
            # rows: 'customer' or 'inventory' swaps the whole slice out,
            # while '' (or None) drops the usage clause and only widens.
            bool(location_usage) and location_usage != 'internal',
        )
    )
    # Values that add rows without removing any. The footer sums a set the
    # default view does not hold, but the ledger rates price products, not
    # views, so the figure stands — and the reconciliation still clamps
    # each product to the cards this wider set can see.
    widening = any(
        (
            not location_usage,
            include_empty,
        )
    )
    filtered = narrowing

    if has_layers:
        source = VALUE_FROM_LAYERS
        unit_price = None
    else:
        source = VALUE_FROM_PURCHASE_PRICE
        # One currency policy, the statistics tile's own: a price counts
        # when its currency is the organization's or unstated. Two
        # currencies have no sum, and a footer that added złoty to euro
        # disagreed with the tile by exactly the foreign money.
        unit_price = case(
            (org_currency_filter(Item.currency, org_currency), Item.purchase_price)
        )

    # The records are added up once, per product and unit, and every sum
    # below is taken over those groups: a weight, a volume and a value are
    # each the group's quantity times a factor of its product and unit, so
    # summing the groups gives what summing the records gave. Joined to the
    # products and units record by record, the footer of a hundred thousand
    # products took seconds.
    group_columns: list[Any] = [
        Item.organization_id.label('organization_id'),
        Item.template_id.label('template_id'),
        Item.uom_id.label('uom_id'),
        func.count(Item.id).label('records'),
        func.sum(Item.quantity).label('quantity'),
    ]
    if unit_price is not None:
        group_columns += [
            func.sum(unit_price * Item.quantity).label('priced_value'),
            func.count(Item.id).filter(unit_price.is_(None)).label('unpriced'),
        ]
    groups = _apply_item_filters(
        select(*group_columns)
        .select_from(Item)
        .join(StorageLocation, Item.storage_location_id == StorageLocation.id),
        user_storage_ids=user_storage_ids,
        user_organization_id=user_organization_id,
        location_usage=location_usage,
        include_empty=include_empty,
        storage_id=storage_id,
        category_id=category_id,
        context_tag=context_tag,
        claimed_tags=claimed_tags,
        search=search,
        expiring_days=expiring_days,
        only_expired=only_expired,
        only_low_stock=only_low_stock,
        needs_attention=needs_attention,
        source_document_id=source_document_id,
        template_ids=template_ids,
        today=today,
    ).group_by(Item.organization_id, Item.template_id, Item.uom_id)
    groups = groups.cte('record_groups')

    weight_kg, volume_l, measured = _weight_and_volume(groups)

    if unit_price is not None:
        value_columns = [
            func.coalesce(func.sum(groups.c.priced_value), 0.0).label('value'),
            func.coalesce(func.sum(groups.c.unpriced), 0).label('unpriced'),
        ]
    else:
        value_columns = [literal(None).label('value'), literal(0).label('unpriced')]
    query = select(
        func.coalesce(func.sum(groups.c.records), 0).label('records'),
        func.count(distinct(groups.c.template_id)).label('products'),
        weight_kg.label('weight'),
        volume_l.label('volume'),
        *value_columns,
    ).select_from(measured)

    # The ledger prices what it actually holds, not what the cards claim:
    # stock that arrived without a priced receipt — a count overwrite, a
    # production run, a hand-made record — has no layer, and valuing it at
    # the received rate invented money the ledger never held (the footer
    # and the statistics tile disagreed by exactly that amount). Per
    # template, the valued quantity is the smaller of the cards in scope
    # and the layers on hand; the unbacked rest contributes nothing, and
    # the records carrying it are counted in ``unpriced_count`` by their
    # product's missing rate.
    #
    # Only the whole organization has a ledger value. The rates are
    # organization-wide, so priced under a filter they valued the shelf's
    # stock at a rate the organization's other receipts earned — the footer
    # printed money no ledger held and said nothing about it. A filtered
    # slice has no ledger value: the figure is withheld and the source says
    # so. The count and the weight still describe the slice;
    # ``unpriced_count`` falls back to zero, since "left out of the value"
    # names nothing when no value stands beside it.
    if has_layers and not filtered:
        valued = _ledger_value(groups, org_currency, user_organization_id)
        # One statement, so the groups are added up once for both halves.
        sums = query.subquery()
        query = select(
            sums.c.records,
            sums.c.products,
            sums.c.weight,
            sums.c.volume,
            valued.c.value,
            valued.c.unpriced,
        ).select_from(sums.join(valued, true()))

    count, product_count, total_weight, total_volume, total_value, unpriced = (
        db.execute(query).one()
    )
    if has_layers and filtered:
        source = VALUE_NOT_AVAILABLE_UNDER_FILTER
        unpriced = 0

    # The claimed set is a property of the running build, not of the
    # organization — "module-scoped" alone says nothing about what THIS
    # reader's list holds. The flag stands only when the scoping actually
    # removed rows from this answer, and only on the unfiltered view:
    # under a filter the difference from the statistics tile belongs to
    # the filter, and a sentence about modules would point the wrong way.
    excludes_module_items = False
    if claimed_tags and not filtered and not widening and total_value is not None:
        from app.core.module_ownership import unclaimed_by_a_module

        rejected = _apply_item_filters(
            select(func.count(Item.id))
            .select_from(Item)
            .join(StorageLocation, Item.storage_location_id == StorageLocation.id),
            user_storage_ids=user_storage_ids,
            user_organization_id=user_organization_id,
            location_usage=location_usage,
            storage_id=storage_id,
            category_id=category_id,
            context_tag=context_tag,
            claimed_tags=None,
            search=search,
            expiring_days=expiring_days,
            only_expired=only_expired,
            only_low_stock=only_low_stock,
            needs_attention=needs_attention,
            source_document_id=source_document_id,
            template_ids=template_ids,
            today=today,
        ).where(~unclaimed_by_a_module(claimed_tags))
        excludes_module_items = (db.execute(rejected).scalar() or 0) > 0

    # The other half of the same question: the footer clamps each product
    # to the cards this list can see, so an open layer whose product has no
    # record here is money the tile counts and this sum cannot. Asked only
    # on the unfiltered view, for the reason the module flag is: under a
    # filter the difference belongs to the filter.
    excludes_unlisted_layers = False
    if not filtered and not widening and total_value is not None:
        # The module scoping does not reach this query: a product it hides is
        # already named by the module sentence, and a layer on such a
        # product lighting the layer sentence too made one 100.00 carry two
        # explanations — a reader adding them up charged it twice. "Unlisted"
        # here means the list shows no record of the product at all, so the
        # question is asked against the list the scoping never touched.
        listed_templates = _apply_item_filters(
            select(Item.template_id)
            .select_from(Item)
            .join(StorageLocation, Item.storage_location_id == StorageLocation.id),
            user_storage_ids=user_storage_ids,
            user_organization_id=user_organization_id,
            location_usage=location_usage,
            storage_id=storage_id,
            category_id=category_id,
            context_tag=context_tag,
            claimed_tags=None,
            search=search,
            expiring_days=expiring_days,
            only_expired=only_expired,
            only_low_stock=only_low_stock,
            needs_attention=needs_attention,
            source_document_id=source_document_id,
            template_ids=template_ids,
            today=today,
        ).where(Item.template_id.isnot(None))
        # The layers are matched to the reader's organization: the one named,
        # or the one the locations the reader may see belong to.
        reader_orgs: Any = None
        if user_organization_id is not None:
            reader_orgs = [user_organization_id]
        elif user_storage_ids:
            reader_orgs = (
                select(StorageLocation.organization_id)
                .where(in_ids(StorageLocation.id, user_storage_ids))
                .distinct()
            )
        # Exactly the layers the statistics tile sums (see
        # ``analytics.stock_value_async``): an inflow still on hand, in a
        # currency the organization adds up. A layer the tile does not count
        # either is no difference to explain, and the sentence would send
        # the reader looking for money nobody is showing.
        unlisted_layers = select(StockValuationLayer.product_template_id).where(
            StockValuationLayer.direction == 'IN',
            StockValuationLayer.remaining_qty > 0,
            org_currency_filter(StockValuationLayer.currency, org_currency),
            StockValuationLayer.product_template_id.notin_(listed_templates),
        )
        if reader_orgs is not None:
            unlisted_layers = unlisted_layers.where(
                StockValuationLayer.organization_id.in_(reader_orgs)
            )
        unlisted = select(func.count()).select_from(unlisted_layers.limit(1).subquery())
        excludes_unlisted_layers = (db.execute(unlisted).scalar() or 0) > 0

    return ItemTotals(
        count=int(count),
        product_count=int(product_count),
        total_weight=float(total_weight),
        total_volume=float(total_volume),
        total_value=None if total_value is None else float(total_value),
        value_source=source,
        unpriced_count=int(unpriced),
        excludes_module_items=excludes_module_items,
        excludes_unlisted_layers=excludes_unlisted_layers,
    )


def _weight_and_volume(groups: Any) -> tuple[Any, Any, Any]:
    """The kilograms and the litres of the record groups, and what to join.

    Weight is the ADR-015 line weight (see ``get_items_aggregates``); a
    group carries its quantity, its product and its unit, so the factors
    are applied to the group as they were to each record of it.
    """
    template = aliased(ProductTemplate)
    weight_uom = aliased(Uom)
    weight_uom_category = aliased(UomCategory)

    line_weight = case(
        (
            UomCategory.name.in_(tuple(CONTINUOUS_UOM_CATEGORIES)),
            groups.c.quantity * Uom.factor / REFERENCE_UNITS_PER_STORED_UNIT,
        ),
        else_=(
            groups.c.quantity
            * template.weight_value
            * func.coalesce(weight_uom.factor, 1)
            / REFERENCE_UNITS_PER_STORED_UNIT
        ),
    )
    # Which of the two sums the line belongs to, asked of the same two
    # branches that produced the number: a line counted in a continuous
    # unit carries its own category; a line counted in pieces takes the
    # template's weight unit, and only a product with none falls back to
    # kilograms — the per-row rule ``Item.total_weight_unit`` applies.
    # Litres and kilograms then leave in two sums; one figure holding both
    # read 2 l of milk as 2 kg.
    line_is_volume = case(
        (UomCategory.name == VOLUME_UOM_CATEGORY, True),
        (UomCategory.name.in_(tuple(CONTINUOUS_UOM_CATEGORIES)), False),
        else_=func.coalesce(weight_uom_category.name == VOLUME_UOM_CATEGORY, False),
    )
    weight_kg = func.coalesce(
        func.sum(case((line_is_volume, None), else_=line_weight)), 0.0
    )
    volume_l = func.coalesce(func.sum(case((line_is_volume, line_weight))), 0.0)
    measured = (
        groups.outerjoin(Uom, groups.c.uom_id == Uom.id)
        .outerjoin(UomCategory, Uom.category_id == UomCategory.id)
        .outerjoin(template, groups.c.template_id == template.id)
        .outerjoin(weight_uom, template.weight_uom_id == weight_uom.id)
        .outerjoin(
            weight_uom_category, weight_uom.category_id == weight_uom_category.id
        )
    )
    return weight_kg, volume_l, measured


def _ledger_value(
    groups: Any, org_currency: str | None, organization_id: UUID | None
) -> Any:
    """The ledger's value of the record groups, and the records it cannot price.

    Per product, the smaller of the cards in scope and the layers on hand,
    at the layers' average rate (see ``get_items_aggregates``); a record
    whose product has no rate is counted as unpriced.
    """
    rates = _layer_average_rates(org_currency, organization_id)
    card = (
        select(
            groups.c.organization_id,
            groups.c.template_id,
            func.sum(groups.c.quantity).label('card_qty'),
            func.sum(groups.c.records).label('records'),
        )
        .group_by(groups.c.organization_id, groups.c.template_id)
        .subquery()
    )
    return (
        select(
            func.coalesce(
                func.sum(
                    func.least(
                        card.c.card_qty,
                        func.coalesce(rates.c.on_hand_qty, 0.0),
                    )
                    * func.coalesce(rates.c.rate, 0.0)
                ),
                0.0,
            ).label('value'),
            func.coalesce(
                func.sum(card.c.records).filter(rates.c.rate.is_(None)), 0
            ).label('unpriced'),
        )
        .select_from(card)
        .outerjoin(
            rates,
            and_(
                rates.c.organization_id == card.c.organization_id,
                rates.c.product_template_id == card.c.template_id,
            ),
        )
        .subquery()
    )


def _layer_average_rates(org_currency: str | None, organization_id: UUID | None = None):
    """Per (organization, product): the average cost of the layers on hand.

    The same figure ``core_api.valuation.get_rates_batch_async`` hands out,
    as a subquery so the footer can join it instead of fetching a rate per
    product. Its refusals are kept: a product whose open layers disagree on
    a currency, or agree on one that is not the organization's own, has no
    rate — a bare number every reader would take for the house's money.
    NULL on a layer means the house currency and is resolved before the
    comparison, so a backfilled layer beside a stated one is not a dispute.

    *organization_id* keeps the layers to that organization's, when the
    caller knows it; the footer joins the rates to its own products anyway,
    and averaging every other organization's layers first was wasted.
    """
    currency = func.coalesce(StockValuationLayer.currency, org_currency)
    layers = (
        select(
            StockValuationLayer.organization_id.label('organization_id'),
            StockValuationLayer.product_template_id.label('product_template_id'),
            func.sum(StockValuationLayer.remaining_qty).label('on_hand_qty'),
            (
                func.sum(
                    StockValuationLayer.remaining_qty * StockValuationLayer.unit_cost
                )
                / func.sum(StockValuationLayer.remaining_qty)
            ).label('rate'),
            func.count(distinct(currency)).label('currencies'),
            func.min(currency).label('currency'),
        )
        .where(
            StockValuationLayer.direction == 'IN',
            StockValuationLayer.remaining_qty > 0,
            # Stock that arrived with nobody naming a price and no rate to
            # borrow is on the books at 0.00 marked unknown. It is not a
            # cost; averaging it in would price the product below anything
            # anyone paid, and a product with nothing else behind it gets
            # no rate at all — and is counted out loud. The same rule the
            # rate a priceless receipt borrows applies, so the two agree.
            StockValuationLayer.carries_a_cost,
        )
        .group_by(
            StockValuationLayer.organization_id,
            StockValuationLayer.product_template_id,
        )
    )
    if organization_id is not None:
        layers = layers.where(StockValuationLayer.organization_id == organization_id)
    on_hand = layers.subquery()
    in_house_money = and_(
        on_hand.c.currencies == 1,
        or_(on_hand.c.currency.is_(None), on_hand.c.currency == org_currency),
    )
    return select(
        on_hand.c.organization_id,
        on_hand.c.product_template_id,
        on_hand.c.on_hand_qty,
        case((in_house_money, on_hand.c.rate), else_=None).label('rate'),
    ).subquery()


def _item_active_query(organization_id: UUID, item_id: UUID):
    return select(Item).where(
        Item.id == item_id,
        Item.organization_id == organization_id,
        Item.is_deleted.is_(False),
    )


def _item_any_query(organization_id: UUID, item_id: UUID):
    return select(Item).where(
        Item.id == item_id,
        Item.organization_id == organization_id,
    )


async def get_by_id_async(
    db: AsyncSession,
    organization_id: UUID,
    item_id: UUID,
) -> Item | None:
    """Return a single non-deleted item belonging to *organization_id*, or None."""
    result = await db.scalars(_item_active_query(organization_id, item_id))
    return result.first()


async def existing_item_ids_async(
    db: AsyncSession,
    organization_id: UUID,
    item_ids: set[UUID],
) -> set[UUID]:
    """Return the subset of *item_ids* that are live rows of *organization_id*.

    The batch twin of ``get_by_id_async``'s existence question, with its
    exact semantics (the organization's own, not soft-deleted) — one query,
    so a write validating a list of references does not pay per line.
    """
    if not item_ids:
        return set()
    rows = await db.scalars(
        select(Item.id).where(
            Item.id.in_(item_ids),
            Item.organization_id == organization_id,
            Item.is_deleted.is_(False),
        )
    )
    return set(rows.all())


def _locked_loading() -> tuple[Any, ...]:
    """How a record read under its lock is loaded.

    The product and the category are not read with it: they come from the
    session afterwards, since the card of a record being written is in hand
    already. A function, as the options configure the mappers.
    """
    return (
        selectinload(Item.uom),
        selectinload(Item.storage_location),
        lazyload(Item.template),
        lazyload(Item.category),
    )


async def lock_records_async(
    db: AsyncSession, organization_id: UUID, item_ids: Iterable[UUID]
) -> None:
    """Take the row locks of *item_ids* in one statement, in id order.

    What :func:`get_by_id_for_update_async` does for one record, for a document
    that is about to ask for each of its lines' records in turn: the locks are
    held and the records in hand afterwards, so each line's own request is
    answered without a statement. Ids that name no record are left to that
    request to refuse. Taken in id order, so two documents that do this meet
    their common records in the same order.
    """
    held = records_locked(db)
    wanted = sorted({i for i in item_ids if (organization_id, i) not in held})
    if not wanted:
        return
    records = (
        await db.scalars(
            select(Item)
            .where(
                Item.id.in_(wanted),
                Item.organization_id == organization_id,
                Item.is_deleted.is_(False),
            )
            .order_by(Item.id)
            .options(*_locked_loading())
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
    ).all()
    for record in records:
        await give_the_card_and_category(db, record)
        held.add((organization_id, record.id))
    keep_loaded(db, records)


async def get_by_id_for_update_async(
    db: AsyncSession,
    organization_id: UUID,
    item_id: UUID,
) -> Item | None:
    """Return a single item with row-level lock (SELECT ... FOR NO KEY UPDATE).

    Tier 2 CoreAPI primitive for concurrent workflows (picking scan,
    stock adjustment) that need to prevent two callers from mutating
    the same item at once. The lock is released when the surrounding
    transaction commits/rolls back.

    ``FOR NO KEY UPDATE``, not ``FOR UPDATE``: the change is to the
    quantity, never to the record's key. ``FOR UPDATE`` also held off the
    ``FOR KEY SHARE`` every insert referring to the record takes for its
    foreign key, so a document line naming the record waited for the change,
    and a two-line draft and another document's completion could each hold
    a record the other wanted — a deadlock over a line nobody was changing.

    The row is re-read into the object, not just locked. Without
    ``populate_existing`` an item this session had already loaded came back
    from the identity map with the quantity it held *before* the lock was
    granted — so a caller that waited for another transaction's write still
    saw the number from before it, and wrote over it.
    """
    from sqlalchemy import inspect
    from sqlalchemy.orm.util import identity_key

    # A lock lasts to the end of the transaction and nobody else can change
    # the row while it is held, so the record this transaction already holds
    # and has in hand is still what the database says. Reading it again was a
    # statement per line for the documents that ask twice.
    held = records_locked(db)
    if (organization_id, item_id) in held:
        record = db.sync_session.identity_map.get(identity_key(Item, item_id))
        if (
            record is not None
            and record.organization_id == organization_id
            and not record.is_deleted
            and not inspect(record).expired_attributes
        ):
            return record

    result = await db.scalars(
        _item_active_query(organization_id, item_id)
        .options(*_locked_loading())
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    record = result.first()
    if record is not None:
        await give_the_card_and_category(db, record)
        held.add((organization_id, item_id))
        # The session forgets a record nobody holds; inside a posting this one
        # is wanted again by the next layer that asks for its lock.
        keep_loaded(db, [record])
    return record


async def get_any_by_id_async(
    db: AsyncSession,
    organization_id: UUID,
    item_id: UUID,
) -> Item | None:
    """Return a single item (including soft-deleted) belonging to *organization_id*, or None."""
    result = await db.scalars(_item_any_query(organization_id, item_id))
    return result.first()


async def get_any_item_in_locations_async(
    db: AsyncSession,
    item_id: UUID,
    user_storage_ids: list[UUID],
) -> Item | None:
    """Return an item by id scoped to a set of storage locations, or None."""
    result = await db.scalars(
        select(Item).where(
            Item.id == item_id,
            in_ids(Item.storage_location_id, user_storage_ids),
        )
    )
    return result.first()


async def get_any_item_in_locations_or_404_async(
    db: AsyncSession,
    item_id: UUID,
    user_storage_ids: list[UUID],
) -> Item:
    """Return an item scoped to storage locations, or raise 404."""
    item = await get_any_item_in_locations_async(db, item_id, user_storage_ids)
    if not item:
        raise NotFoundException('item')
    return item
