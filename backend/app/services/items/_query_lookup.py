"""Lookup-by-attribute and counting queries.

Groups the ``barcode_exists``, ``list_existing_serials`` and
``count_by_org`` families. Single-item lookups live in
``_query_get.py``, listing queries in ``_query_listing.py``, and
view-specific specialized queries in ``_query_special.py``.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import lazyload

from app.core.read_scope import keep_loaded
from app.core.txn_memo import records_locked
from app.models.item import Item
from app.models.storage_location import StorageLocation

from ._loaded import give_the_card_and_category


def _barcode_exists_query(organization_id: UUID, barcode: str):
    """EXISTS probe matching a non-deleted item by barcode in *organization_id*."""
    return exists(
        select(Item.id)
        .join(StorageLocation)
        .where(
            Item.barcode == barcode,
            StorageLocation.organization_id == organization_id,
            Item.is_deleted.is_(False),
        )
    )


async def barcode_exists_async(
    db: AsyncSession,
    organization_id: UUID,
    barcode: str,
) -> bool:
    """Return True if a non-deleted item with *barcode* exists in *organization_id*.

    EXISTS probe — the DB stops at the first match and no row is
    materialised.
    """
    result = await db.scalar(select(_barcode_exists_query(organization_id, barcode)))
    return bool(result)


async def find_by_barcode_async(
    db: AsyncSession,
    organization_id: UUID,
    barcode: str,
    *,
    quantity_positive: bool = True,
    for_update: bool = False,
) -> Item | None:
    """Return the first item with *barcode* in *organization_id*, or None.

    Tier 2 CoreAPI extension for barcode-based picking workflows. Eager-loads
    ``uom`` and ``storage_location`` so callers do not trigger extra queries
    when reading those relations. Set ``quantity_positive=False`` to match
    barcode scans that may legitimately resolve to depleted (zero-quantity)
    stock (the picking scan flow needs this for protocol lookup).

    Pass ``for_update=True`` to acquire a row-level lock on the record
    (SELECT ... FOR NO KEY UPDATE OF items) for concurrent mutation flows
    (picking scan, stock adjustment) — the same lock
    ``get_by_id_for_update_async`` takes, and for the same reason. The shelf
    joined in is read, not locked.
    """
    from sqlalchemy.orm import selectinload

    query = (
        select(Item)
        .options(
            selectinload(Item.uom),
            selectinload(Item.storage_location),
        )
        .join(StorageLocation)
        .where(
            Item.barcode == barcode,
            StorageLocation.organization_id == organization_id,
            Item.is_deleted.is_(False),
        )
    )
    if quantity_positive:
        query = query.where(Item.quantity > 0)
    if for_update:
        query = query.with_for_update(of=Item, key_share=True)
    result = await db.scalars(query)
    return result.first()


async def find_stock_row_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    barcode: str | None = None,
    template_id: UUID | None = None,
    expiry_date: date | None = None,
    storage_location_id: UUID | None = None,
    lot_id: UUID | None = None,
    owner_id: UUID | None = None,
    for_update: bool = False,
) -> Item | None:
    """Return the record a delivery to this place tops up, or None.

    With *for_update* the record comes back under its row lock
    (``FOR NO KEY UPDATE``) and freshly read, the way
    ``get_by_id_for_update_async`` returns one: a delivery that is about to
    write the record's number finds it and locks it in one statement, and the
    transaction's later ask for the same lock costs nothing.

    A receipt that names a product rather than a record has to decide whether
    that product is already here. Two things are never the answer:

    - a row with a ``serial_number``, which is one physical thing and gains
      nothing by being told there are now three of it;
    - a row owned by a vertical module (``module_name``), because an asset in
      an equipment register is not warehouse stock even when it shares a
      product template with some.

    Past that, identity is the product plus the place. ``storage_location_id``
    is part of the question because the ledger it feeds is keyed that way:
    the records' view sums the stock per (template, location), and the
    movement ledger and the reconciliation report count it per (template,
    location) too. A row topped up on one shelf while the goods land on another
    puts both shelves in drift and leaves the catalogue pointing somewhere
    nobody should walk.

    Which product it is comes from the template when the line names one. A
    template-backed row also has to agree on ``expiry_date`` — that column is
    the rotation cache for non-lot stock, and folding a June batch into a
    December row would leave FEFO reading a date true of neither — and on
    the batch and owner (``lot_id``, ``owner_id``): a record holds one batch
    of one owner's goods, so a delivery of another batch is another record.

    A line naming no template is answered by the barcode alone, and that
    answer is deliberately not narrowed by place or batch: such a record owns
    its barcode, ``uq_items_org_barcode_active`` allows exactly one active row
    to carry it, and a narrower question here would only produce a second row
    the index refuses. Those records have no template, so they have no quant
    and nothing for a location to disagree with.
    """
    if barcode is None and template_id is None:
        return None

    query = select(Item).where(
        Item.organization_id == organization_id,
        Item.is_deleted.is_(False),
        Item.serial_number.is_(None),
        Item.module_name.is_(None),
    )
    if template_id is None:
        query = query.where(Item.barcode == barcode)
    else:
        query = query.where(
            Item.template_id == template_id,
            # IS NOT DISTINCT FROM: two undated batches are the same batch.
            Item.expiry_date.is_not_distinct_from(expiry_date),
            Item.lot_id.is_not_distinct_from(lot_id),
            Item.owner_id.is_not_distinct_from(owner_id),
        )
        if storage_location_id is not None:
            query = query.where(Item.storage_location_id == storage_location_id)

    query = query.order_by(Item.created_at.asc()).limit(1)
    if for_update:
        # The product and the category are given to the record from the
        # session below rather than fetched by their loaders: a posting has
        # the product in hand already, and a statement per record is what it
        # is built not to send.
        result = await db.scalars(
            query.options(lazyload(Item.template), lazyload(Item.category))
            .with_for_update(of=Item, key_share=True)
            .execution_options(populate_existing=True)
        )
        record = result.first()
        if record is not None:
            await give_the_card_and_category(db, record)
            records_locked(db).add((organization_id, record.id))
            keep_loaded(db, [record])
        return record
    result = await db.scalars(query)
    return result.first()


async def inherited_category_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    source_category_id: UUID | None = None,
    template_id: UUID | None = None,
) -> UUID | None:
    """The category a new record of this product is filed under.

    One answer for every executor that opens a record from goods it moves
    or takes in. The record the caller names — the transfer's source, the
    record a receipt borrows its identity from — answers first: the new
    record is filed where the goods' record stands. With no source record,
    the product answers: the category most of its records carry, the newest
    record breaking a tie. No source and no records, no category — there is
    nothing to inherit, and ``None`` says so.

    ``source_category_id`` is the known category of the source record; it
    travels as the value itself rather than as an id to re-read, because
    every caller already holds that record.
    """
    if source_category_id is not None:
        return source_category_id
    if template_id is None:
        return None
    newest = func.max(Item.created_at)
    stmt = (
        select(Item.category_id)
        .where(
            Item.organization_id == organization_id,
            Item.template_id == template_id,
            Item.is_deleted.is_(False),
            Item.category_id.is_not(None),
        )
        .group_by(Item.category_id)
        .order_by(func.count(Item.id).desc(), newest.desc())
        .limit(1)
    )
    return await db.scalar(stmt)


def _serial_numbers_query(organization_id: UUID, serial_numbers: set[str]):
    return select(Item.serial_number).where(
        Item.organization_id == organization_id,
        Item.serial_number.in_(serial_numbers),
        Item.is_deleted.is_(False),
    )


async def list_existing_serials_async(
    db: AsyncSession,
    organization_id: UUID,
    serial_numbers: set[str],
) -> set[str]:
    """Return the subset of *serial_numbers* that already exist in the org."""
    if not serial_numbers:
        return set()
    result = await db.scalars(_serial_numbers_query(organization_id, serial_numbers))
    return {serial for serial in result.all() if serial is not None}


def _count_by_org_query(
    organization_id: UUID,
    *,
    is_deleted: bool = False,
    category_id: UUID | None = None,
    context_tag: str | None = None,
    storage_location_id: UUID | None = None,
):
    query = (
        select(Item)
        .join(StorageLocation, Item.storage_location_id == StorageLocation.id)
        .where(
            StorageLocation.organization_id == organization_id,
            Item.is_deleted == is_deleted,
        )
    )
    if category_id:
        query = query.where(Item.category_id == category_id)
    if context_tag:
        from app.core.module_ownership import items_with_context_tag

        query = query.where(items_with_context_tag(context_tag))
    if storage_location_id:
        query = query.where(Item.storage_location_id == storage_location_id)
    return select(func.count()).select_from(query.subquery())


async def count_by_org_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    is_deleted: bool = False,
    category_id: UUID | None = None,
    context_tag: str | None = None,
    storage_location_id: UUID | None = None,
) -> int:
    """Return count of items for *organization_id* with optional filters."""
    result = await db.scalar(
        _count_by_org_query(
            organization_id,
            is_deleted=is_deleted,
            category_id=category_id,
            context_tag=context_tag,
            storage_location_id=storage_location_id,
        )
    )
    return result or 0
