"""ShoppingListItem CRUD operations.

Create, read, update, delete operations on individual ShoppingListItem rows.
Item purchase-state changes live in _item_state.py.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    NotFoundException,
    catalogue_refusal,
    catalogue_status_refusal,
)
from app.i18n import Language
from app.i18n.service import stated_quantity
from app.schemas.validators import QUANTITY_STEP

from ._helpers import get_shopping_list_item_or_404
from .models import ShoppingList, ShoppingListItem
from .schemas import ShoppingListItemCreate, ShoppingListItemUpdate

# The column holds three places; a value that rounds below its own first
# digit is a zero the store would keep and the schema would refuse on the
# way back out — bricking every read of the list. Refuse at the door, in
# the reader's language, instead.
_ZERO_REFUSAL_KEY = 'shopping_list_item_quantity_rounds_to_zero'

# A uom_id the uoms table does not know is a foreign-key violation the
# database would answer with a raw 500.  The unit selector in the UI
# offers only real units, but the API is reachable by integrations,
# import scripts and external tests — every caller that assembles its
# own request.  Refuse at the write layer, naming the field, so the
# class is closed for every door that sets the column.
_UOM_REFUSAL_KEY = 'shopping_list_item_uom_unknown'

# The same class for the three product references: a category_id, item_id
# or template_id no visible row answers used to reach the INSERT and die
# on the foreign key with a bare 500.  The check is scoped the
# way the uom check is — what the organization can see (its own rows plus
# the system catalogue) — so an id borrowed from another organization is
# refused too, not only a missing one.
_CATEGORY_REFUSAL_KEY = 'shopping_list_item_category_unknown'
_ITEM_REFUSAL_KEY = 'shopping_list_item_item_unknown'
_TEMPLATE_REFUSAL_KEY = 'shopping_list_item_template_unknown'


def _refuse_if_zero(quantity: Decimal | None, lang: Language | None) -> None:
    if quantity is not None and quantity <= 0:
        raise catalogue_refusal(
            _ZERO_REFUSAL_KEY,
            lang=lang,
            quantity=quantity,
            smallest=stated_quantity(QUANTITY_STEP, lang),
        )


async def _refuse_if_unknown_uom(
    db: AsyncSession,
    uom_ids: set[UUID | None],
    lang: Language | None,
    organization_id: UUID,
) -> None:
    """Refuse uom_ids that have no row in the uoms table.

    Validates at the write layer — the one place the column is set —
    so every door that stores a uom_id gets the same check without
    each input schema repeating it.
    """
    from app.core.public_api import core_api

    known = {u for u in uom_ids if u is not None}
    if not known:
        return
    found = await core_api.uoms.existing_ids_async(db, known, organization_id)
    missing = known - found
    if missing:
        raise catalogue_status_refusal(
            _UOM_REFUSAL_KEY, 422, lang=lang, uom_id=str(next(iter(missing)))
        )


def _refuse_first_missing(
    found: set[UUID],
    wanted: set[UUID],
    refusal_key: str,
    field: str,
    lang: Language | None,
) -> None:
    missing = wanted - found
    if missing:
        params: dict[str, Any] = {field: str(next(iter(missing)))}
        raise catalogue_status_refusal(refusal_key, 422, lang=lang, **params)


async def _refuse_if_unknown_references(
    db: AsyncSession,
    *,
    item_ids: set[UUID | None],
    category_ids: set[UUID | None],
    template_ids: set[UUID | None],
    lang: Language | None,
    organization_id: UUID,
) -> None:
    """Refuse product references no visible row answers, naming the field.

    The twin of the uom refusal for the three product reference columns,
    validated at the same write layer.  Each family is one batched
    question for the whole payload, so a ten-line add pays three queries,
    not thirty.
    """
    from app.core.public_api import core_api

    items = {value for value in item_ids if value is not None}
    if items:
        _refuse_first_missing(
            await core_api.items.existing_ids_async(db, organization_id, items),
            items,
            _ITEM_REFUSAL_KEY,
            'item_id',
            lang,
        )
    categories = {value for value in category_ids if value is not None}
    if categories:
        _refuse_first_missing(
            await core_api.categories.existing_ids_async(
                db, organization_id, categories
            ),
            categories,
            _CATEGORY_REFUSAL_KEY,
            'category_id',
            lang,
        )
    templates = {value for value in template_ids if value is not None}
    if templates:
        _refuse_first_missing(
            set(
                await core_api.product_templates.get_many_async(
                    db, organization_id, list(templates)
                )
            ),
            templates,
            _TEMPLATE_REFUSAL_KEY,
            'template_id',
            lang,
        )


async def add_single_item(
    db: AsyncSession,
    list_id: UUID,
    item_in: ShoppingListItemCreate,
    organization_id: UUID,
    lang: Language | None = None,
) -> ShoppingListItem:
    _refuse_if_zero(item_in.quantity, lang)
    await _refuse_if_unknown_uom(db, {item_in.uom_id}, lang, organization_id)
    await _refuse_if_unknown_references(
        db,
        item_ids={item_in.item_id},
        category_ids={item_in.category_id},
        template_ids={item_in.template_id},
        lang=lang,
        organization_id=organization_id,
    )
    item = ShoppingListItem(
        shopping_list_id=list_id,
        item_id=item_in.item_id,
        category_id=item_in.category_id,
        template_id=item_in.template_id,
        name=item_in.name,
        quantity=item_in.quantity or 1,
        uom_id=item_in.uom_id,
        notes=item_in.notes,
        note_data=item_in.note_data,
        estimated_price=item_in.estimated_price,
        priority=item_in.priority or 0,
        source='manual',
    )
    db.add(item)
    await db.flush()
    # The response schema reads uom (the symbol the row renders with);
    # nothing loads it on a row that was just built — lazy='joined' only
    # answers queries — and the lazy read outside the greenlet took the
    # whole 201 response down.
    await db.refresh(item, ['category', 'uom'])
    return item


async def bulk_add_items(
    db: AsyncSession,
    list_id: UUID,
    items_in: list[ShoppingListItemCreate],
    organization_id: UUID,
    lang: Language | None = None,
) -> list[ShoppingListItem]:
    for item_in in items_in:
        _refuse_if_zero(item_in.quantity, lang)
    await _refuse_if_unknown_uom(
        db, {item_in.uom_id for item_in in items_in}, lang, organization_id
    )
    await _refuse_if_unknown_references(
        db,
        item_ids={item_in.item_id for item_in in items_in},
        category_ids={item_in.category_id for item_in in items_in},
        template_ids={item_in.template_id for item_in in items_in},
        lang=lang,
        organization_id=organization_id,
    )
    created_items = []
    for item_in in items_in:
        item = ShoppingListItem(
            shopping_list_id=list_id,
            item_id=item_in.item_id,
            category_id=item_in.category_id,
            template_id=item_in.template_id,
            name=item_in.name,
            quantity=item_in.quantity or 1,
            uom_id=item_in.uom_id,
            notes=item_in.notes,
            note_data=item_in.note_data,
            estimated_price=item_in.estimated_price,
            priority=item_in.priority or 0,
            source=item_in.source or 'manual',
        )
        db.add(item)
        created_items.append(item)
    await db.flush()
    for item in created_items:
        await db.refresh(item, ['category', 'uom'])
    return created_items


async def update_shopping_list_item(
    db: AsyncSession,
    list_id: UUID,
    item_id: UUID,
    organization_id: UUID,
    data: ShoppingListItemUpdate,
    lang: Language | None,
) -> ShoppingListItem:
    item = await get_shopping_list_item_or_404(
        db, list_id, item_id, organization_id, lang
    )
    _refuse_if_zero(data.quantity, lang)
    if 'uom_id' in data.model_fields_set:
        await _refuse_if_unknown_uom(db, {data.uom_id}, lang, organization_id)
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(item, field, value)
    await db.flush()
    # The unit joins the refresh: after a change of uom_id the loaded
    # relationship still wears the old unit, and the response would name
    # the one the row just stopped carrying.
    await db.refresh(item, ['category', 'uom'])
    return item


async def delete_shopping_list_item(
    db: AsyncSession,
    list_id: UUID,
    item_id: UUID,
    organization_id: UUID,
    lang: Language | None,
) -> None:
    result = await db.execute(
        select(ShoppingListItem)
        .join(ShoppingList)
        .where(
            ShoppingListItem.id == item_id,
            ShoppingListItem.shopping_list_id == list_id,
            ShoppingList.organization_id == organization_id,
        )
        .with_for_update(of=ShoppingListItem)
    )
    item = result.scalars().first()
    if not item:
        raise NotFoundException('shopping_list_item', lang)
    await db.delete(item)
    await db.flush()


# tri-state filter — PENDING (default), PURCHASED, or ALL.
# Replaces the old `purchased_only: bool` which conflated "no filter" with
# "only pending" and made it impossible to fetch both at once.
PURCHASED_FILTER_PENDING = 'pending'
PURCHASED_FILTER_PURCHASED = 'purchased'
PURCHASED_FILTER_ALL = 'all'
PURCHASED_FILTER_VALUES = frozenset(
    {PURCHASED_FILTER_PENDING, PURCHASED_FILTER_PURCHASED, PURCHASED_FILTER_ALL}
)


async def get_list_items_filtered(
    db: AsyncSession,
    list_id: UUID,
    purchased_filter: str = PURCHASED_FILTER_PENDING,
) -> list[ShoppingListItem]:
    if purchased_filter not in PURCHASED_FILTER_VALUES:
        purchased_filter = PURCHASED_FILTER_PENDING
    stmt = (
        select(ShoppingListItem)
        .options(selectinload(ShoppingListItem.category))
        .where(ShoppingListItem.shopping_list_id == list_id)
    )
    if purchased_filter == PURCHASED_FILTER_PURCHASED:
        stmt = stmt.where(ShoppingListItem.is_purchased.is_(True))
    elif purchased_filter == PURCHASED_FILTER_PENDING:
        stmt = stmt.where(ShoppingListItem.is_purchased.is_(False))
    # PURCHASED_FILTER_ALL: no extra where clause
    result = await db.execute(
        stmt.order_by(
            ShoppingListItem.priority.desc(),
            ShoppingListItem.created_at.asc(),
            ShoppingListItem.id,
        )
    )
    return list(result.scalars().all())
