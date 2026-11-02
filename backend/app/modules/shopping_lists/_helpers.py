"""Internal helpers for shopping list operations.

Shared by list_crud, item_crud, item_state, and suggestions sub-modules.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import get_org_owned_or_404_async
from app.core.exceptions import NotFoundException
from app.i18n import Language

from .models import ShoppingList, ShoppingListItem


async def get_shopping_list_or_404(
    db: AsyncSession, list_id: UUID, organization_id: UUID, lang: Language | None
) -> ShoppingList:
    return await get_org_owned_or_404_async(
        db, ShoppingList, list_id, organization_id, lang=lang
    )


async def get_shopping_list_item_or_404(
    db: AsyncSession,
    list_id: UUID,
    item_id: UUID,
    organization_id: UUID,
    lang: Language | None,
) -> ShoppingListItem:
    result = await db.execute(
        select(ShoppingListItem)
        .join(ShoppingList)
        .where(
            ShoppingListItem.id == item_id,
            ShoppingListItem.shopping_list_id == list_id,
            ShoppingList.organization_id == organization_id,
        )
    )
    item = result.scalars().first()
    if not item:
        raise NotFoundException('shopping_list_item', lang)
    return item
