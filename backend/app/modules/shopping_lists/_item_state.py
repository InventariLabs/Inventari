"""ShoppingListItem purchase-state operations.

Mark items purchased/unpurchased, clear purchased batch.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictException, NotFoundException
from app.i18n import Language
from app.i18n.service import get_current_lang, get_error_message

from ._helpers import get_shopping_list_or_404
from .models import ShoppingList, ShoppingListItem


async def _get_updated_shopping_list_item(
    db: AsyncSession, item_id: UUID, lang: Language | None
) -> ShoppingListItem:
    result = await db.execute(
        select(ShoppingListItem)
        .options(selectinload(ShoppingListItem.category))
        .where(ShoppingListItem.id == item_id)
    )
    item = result.scalars().first()
    if not item:
        raise NotFoundException('shopping_list_item', lang)
    return item


async def set_item_purchased(
    db: AsyncSession,
    list_id: UUID,
    item_id: UUID,
    organization_id: UUID,
    user_id: UUID,
    lang: Language | None,
) -> ShoppingListItem:
    now = datetime.now(UTC)
    # idempotency guard — re-PATCHing an already-purchased item
    # would silently overwrite the original `purchased_at` / `purchased_by`,
    # destroying the only audit trail. Refuse with 409 instead.
    existing = (
        await db.execute(
            select(ShoppingListItem).where(
                ShoppingListItem.id == item_id,
                ShoppingListItem.shopping_list_id == list_id,
                ShoppingListItem.shopping_list_id
                == select(ShoppingList.id)
                .where(
                    ShoppingList.id == list_id,
                    ShoppingList.organization_id == organization_id,
                )
                .scalar_subquery(),
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        raise NotFoundException('shopping_list_item', lang)
    if existing.is_purchased:
        raise ConflictException(
            code='ALREADY_PURCHASED',
            message=get_error_message(
                'shopping_item_already_purchased_reset', get_current_lang()
            ),
        )

    result = await db.execute(
        update(ShoppingListItem)
        .where(
            ShoppingListItem.id == item_id,
            ShoppingListItem.shopping_list_id
            == select(ShoppingList.id)
            .where(
                ShoppingList.id == list_id,
                ShoppingList.organization_id == organization_id,
            )
            .scalar_subquery(),
            ShoppingListItem.is_purchased.is_(False),
        )
        .values(is_purchased=True, purchased_at=now, purchased_by=user_id)
        .returning(ShoppingListItem.id)
    )
    updated_id = result.scalar_one_or_none()
    if updated_id is None:
        # Lost the race against a concurrent PATCH — treat as already-purchased
        raise ConflictException(
            code='ALREADY_PURCHASED',
            message=get_error_message(
                'shopping_item_already_purchased', get_current_lang()
            ),
        )

    await db.flush()
    return await _get_updated_shopping_list_item(db, updated_id, lang)


async def set_item_unpurchased(
    db: AsyncSession,
    list_id: UUID,
    item_id: UUID,
    organization_id: UUID,
    lang: Language | None,
) -> ShoppingListItem:
    result = await db.execute(
        update(ShoppingListItem)
        .where(
            ShoppingListItem.id == item_id,
            ShoppingListItem.shopping_list_id
            == select(ShoppingList.id)
            .where(
                ShoppingList.id == list_id,
                ShoppingList.organization_id == organization_id,
            )
            .scalar_subquery(),
        )
        .values(is_purchased=False, purchased_at=None, purchased_by=None)
        .returning(ShoppingListItem.id)
    )
    updated_id = result.scalar_one_or_none()
    if updated_id is None:
        raise NotFoundException('shopping_list_item', lang)

    await db.flush()
    return await _get_updated_shopping_list_item(db, updated_id, lang)


async def clear_purchased_from_list(
    db: AsyncSession, list_id: UUID, organization_id: UUID, lang: Language | None
) -> None:
    await get_shopping_list_or_404(db, list_id, organization_id, lang)
    await db.execute(
        delete(ShoppingListItem).where(
            ShoppingListItem.shopping_list_id == list_id,
            ShoppingListItem.is_purchased == True,
        )
    )
    await db.flush()
