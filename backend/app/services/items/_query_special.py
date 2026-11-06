"""Specialized view-specific queries.

Groups the ``get_*_or_404``, ``get_expiring_items``,
``get_archived_items`` and ``get_product_template_or_404`` families. These
are the queries backing dashboard widgets, alerts, archive views and
PO/template lookups. Single-item lookups live in ``_query_get.py``,
listings in ``_query_listing.py``, and lookups/counts in
``_query_lookup.py``.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, joinedload, noload, selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.core.db_utils import in_ids, paginate_async
from app.core.exceptions import AppException, NotFoundException
from app.i18n.service import get_current_lang, get_error_message
from app.models.item import Item
from app.models.item_history import ItemAction, ItemHistory
from app.models.product_template import ProductTemplate


async def get_item_or_404_async(
    db: AsyncSession,
    item_id: UUID,
    user_storage_ids: list[UUID],
    *,
    for_update: bool = False,
    include_archived: bool = False,
) -> Item:
    """Return an item by id restricted to *user_storage_ids*, or 404.

    ``for_update`` takes the row lock a read-modify-write needs. The edit
    path computes ``delta = new - old`` from the quantity it read here, so
    two edits in flight both measured against the same stale ``old``: their
    deltas both reached the quants and ``Item.quantity`` kept whichever
    write landed last, leaving the cache and the stock it stands for at two
    different numbers for good. The scanning paths took this lock through
    ``get_by_id_for_update_async`` already; this is the same lock — ``FOR NO
    KEY UPDATE``, which leaves foreign key checks alone — on the door the
    form uses.

    The eager load changes with it: a row lock cannot ride an outer join, so
    the locking read fetches the unit in a second query instead.

    ``include_archived`` answers a screen whose record stays reachable after
    archiving — the archive is a soft delete, and a card linked from
    assignment history needs the row to render its archived state. The
    default keeps hiding it behind the archive-pointing 404 the live lists
    expect.
    """
    query = select(Item).where(
        Item.id == item_id, in_ids(Item.storage_location_id, user_storage_ids)
    )
    if for_update:
        query = query.options(selectinload(Item.uom)).with_for_update(
            of=Item, key_share=True
        )
    else:
        query = query.options(joinedload(Item.uom))
    result = await db.scalars(query)
    item = result.first()
    if not item:
        raise NotFoundException('item')
    if item.is_deleted and not include_archived:
        # A soft-deleted product is in the archive, not nowhere:
        # the same 404 status — it is not part of the live lists — but a
        # code that lets the detail page say so and point at the archive
        # instead of claiming the record stopped existing.
        raise AppException(
            status_code=404,
            code='ITEM_ARCHIVED',
            message=get_error_message('item_archived', get_current_lang()),
        )
    return item


async def get_expiring_items_async(
    db: AsyncSession,
    user_storage_ids: list[UUID],
    organization_id: UUID | None = None,
    days: int = 7,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[Item], int]:
    """Products approaching expiry, soonest first, and how many there are.

    The same window as the counters: ``is_expiring_soon``, which starts at
    the organization's own today. Items already past their date belong to
    the expired bucket and used to appear in both.
    """
    from app.services.items.expiry import expiry_today_async, is_expiring_soon

    today = await expiry_today_async(db, organization_id)
    query = (
        select(Item)
        .options(joinedload(Item.category), joinedload(Item.uom))
        .where(
            in_ids(Item.storage_location_id, user_storage_ids),
            Item.is_deleted.is_(False),
            is_expiring_soon(today, days),
        )
        .order_by(Item.effective_expiry_date.asc(), Item.id)
    )
    return await paginate_async(db, query, limit=limit, offset=offset)


async def get_archived_items_async(
    db: AsyncSession,
    user_storage_ids: list[UUID],
    *,
    offset: int = 0,
    limit: int = 50,
    context_tag: str | None = None,
    claimed_tags: set[str] | None = None,
    module_scope: str | None = None,
    search: str | None = None,
) -> tuple[list[Item], int]:
    """List soft-deleted items, optionally scoped by module context.

    context_tag: positive filter — only items whose category has this tag.
    claimed_tags: negative filter — exclude items whose category tag is in
        this set (used by the Inventory view via exclude_module_contexts).
    module_scope: positive filter — everything one named vertical module
        counts as its own, which is ``context_tag`` plus the records filed
        under no category at all. A module's own Archive wants this one: the
        equipment form has never required a category, so an asset saved
        without one was archived out of the module's sight and could not be
        restored from inside it. A module nobody registered claims nothing.
    search: same ILIKE fields as the active list (``get_items``) — the
        archive is that list in another state, so it narrows the same way.
    Returns (items, total) so callers can build a paginated envelope.
    """
    conditions: list[ColumnElement[bool]] = [
        in_ids(Item.storage_location_id, user_storage_ids),
        Item.is_deleted.is_(True),
    ]

    if search:
        from ._search_terms import item_matches_text

        conditions.append(item_matches_text(search))

    if module_scope:
        from app.core.module_ownership import claimed_by_module
        from app.core.module_scope import get_context_tags_of

        conditions.append(
            claimed_by_module(module_scope, get_context_tags_of(module_scope))
        )
    elif context_tag:
        from app.models.category import Category

        conditions.extend(
            (
                Item.category_id.isnot(None),
                Item.category.has(Category.context_tag == context_tag),
            )
        )
    elif claimed_tags:
        from app.core.module_ownership import unclaimed_by_a_module

        conditions.append(unclaimed_by_a_module(claimed_tags))

    query = (
        select(Item)
        .options(joinedload(Item.category))
        .options(
            noload(Item.storage_location),
            noload(Item.uom),
            noload(Item.template),
        )
        .where(*conditions)
        .order_by(Item.deleted_at.desc())
    )
    return await paginate_async(db, query, limit=limit, offset=offset)


async def get_deletion_notes_async(
    db: AsyncSession, item_ids: list[UUID]
) -> dict[UUID, str]:
    """The note typed into the delete dialog, per archived product.

    The note is written once, into the ``DELETED`` history entry; a product
    deleted, restored and deleted again has several, and the latest one is
    the deletion the archive is showing. A product deleted without a note
    has no key in the result.
    """
    if not item_ids:
        return {}
    rows = await db.execute(
        select(ItemHistory.item_id, ItemHistory.changes)
        .where(
            ItemHistory.item_id.in_(item_ids),
            ItemHistory.action == ItemAction.DELETED.value,
        )
        .order_by(ItemHistory.created_at.asc())
    )
    notes: dict[UUID, str] = {}
    for item_id, changes in rows:
        note = (changes or {}).get('notes')
        if note:
            notes[item_id] = note
        else:
            notes.pop(item_id, None)
    return notes


def get_product_template_or_404(
    db: Session,
    template_id: UUID,
    organization_id: UUID,
) -> ProductTemplate:
    template = db.get(ProductTemplate, template_id)
    if not template:
        raise NotFoundException('product_template')
    if template.organization_id and template.organization_id != organization_id:
        raise NotFoundException('product_template')
    return template
