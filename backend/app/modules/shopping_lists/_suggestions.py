"""Shopping list suggestions.

Generate and add suggested items based on consumption patterns.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import acquire_advisory_lock, get_org_owned_or_404_async
from app.i18n.service import get_current_lang

from .models import ShoppingList, ShoppingListItem, ShoppingListStatus
from .shopping_suggestions_service import (
    ShoppingSuggestion,
    filter_duplicate_suggestions,
    generate_suggestions,
)


async def get_suggestions_for_list(
    list_id: UUID, org_id: UUID, db: AsyncSession
) -> tuple[list[dict[str, Any]], list[ShoppingSuggestion]]:
    await get_org_owned_or_404_async(
        db, ShoppingList, list_id, org_id, lang=get_current_lang()
    )

    existing_result = await db.execute(
        select(ShoppingListItem).where(ShoppingListItem.shopping_list_id == list_id)
    )
    existing_items = existing_result.scalars().all()
    existing_items_data = [
        {'name': item.name, 'is_purchased': item.is_purchased}
        for item in existing_items
    ]

    suggestions = await generate_suggestions(db, org_id)
    unique_suggestions = filter_duplicate_suggestions(suggestions, existing_items_data)

    return existing_items_data, unique_suggestions


async def add_suggestions_to_list(
    list_id: UUID,
    unique_suggestions: list[ShoppingSuggestion],
    existing_items_data: list[dict[str, Any]],
    db: AsyncSession,
) -> tuple[int, list[ShoppingListItem]]:
    await acquire_advisory_lock(db, f'shopping_list:suggestions:{list_id}')
    added_count = 0
    for suggestion in unique_suggestions:
        already_on_list = any(
            existing['name'].lower() == suggestion.name.lower()
            for existing in existing_items_data
            if not existing['is_purchased']
        )
        if already_on_list:
            continue

        item = ShoppingListItem(
            shopping_list_id=list_id,
            item_id=suggestion.item_id,
            template_id=suggestion.template_id,
            category_id=suggestion.category_id,
            name=suggestion.name,
            quantity=suggestion.quantity,
            uom_id=suggestion.uom_id,
            notes=suggestion.notes,
            estimated_price=suggestion.estimated_price,
            source=suggestion.source,
            priority=suggestion.priority,
        )
        db.add(item)
        added_count += 1
        existing_items_data.append({'name': suggestion.name, 'is_purchased': False})

    await db.flush()

    added_result = await db.execute(
        select(ShoppingListItem)
        .where(ShoppingListItem.shopping_list_id == list_id)
        .order_by(ShoppingListItem.created_at.desc())
        .limit(added_count)
    )
    return added_count, list(added_result.scalars().all())


async def get_suggestions_for_organization(
    org_id: UUID,
    db: AsyncSession,
    *,
    include_low_stock: bool = True,
    include_frequent: bool = True,
    include_expiring: bool = True,
) -> list[ShoppingSuggestion]:
    """What the app would propose buying, without a list to propose it onto.

    The list was never needed to answer this. It was used for one thing —
    subtracting what is already on it — and the screen that asked created
    an empty list to have an id, leaving the organization with a list
    nobody had agreed to. A reader looking at a proposal has agreed to
    nothing yet, so nothing is written.

    Where an active list exists its rows are still subtracted: proposing
    what somebody has already written down is noise. Where none exists
    there is nothing to subtract, and still nothing to create.
    """
    active = await db.scalars(
        select(ShoppingList)
        .where(
            ShoppingList.organization_id == org_id,
            ShoppingList.status == ShoppingListStatus.ACTIVE.value,
        )
        .order_by(ShoppingList.created_at.desc())
        .limit(1)
    )
    active_list = active.first()

    existing_items_data: list[dict[str, Any]] = []
    if active_list is not None:
        existing_result = await db.execute(
            select(ShoppingListItem).where(
                ShoppingListItem.shopping_list_id == active_list.id
            )
        )
        existing_items_data = [
            {'name': item.name, 'is_purchased': item.is_purchased}
            for item in existing_result.scalars().all()
        ]

    suggestions = await generate_suggestions(
        db,
        org_id,
        include_low_stock=include_low_stock,
        include_frequent=include_frequent,
        include_expiring=include_expiring,
    )
    return filter_duplicate_suggestions(suggestions, existing_items_data)
