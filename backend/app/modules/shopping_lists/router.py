from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_read_write,
)
from app.core.exceptions import ConflictException, map_service_errors
from app.core.module_sdk import PaginatedResponse
from app.core.modules import require_module
from app.i18n import Language
from app.i18n.service import get_current_lang, get_error_message

from ._po_convert import convert_list_to_po_async
from .models import ShoppingList as ShoppingListModel
from .models import ShoppingListItem as ShoppingListItemModel
from .schemas import (
    ConvertToPORequest,
    ConvertToPOResponse,
    ShoppingListCreate,
    ShoppingListItemCreate,
    ShoppingListItemUpdate,
    ShoppingListUpdate,
    ShoppingListWithItems,
    ShoppingSuggestionPreview,
    ShoppingSuggestionResponse,
    ShoppingSuggestionSchema,
)
from .schemas import (
    ShoppingList as ShoppingListSchema,
)
from .schemas import (
    ShoppingListItem as ShoppingListItemSchema,
)
from .shopping_list_service import (
    add_single_item,
    add_suggestions_to_list,
    bulk_add_items,
    clear_purchased_from_list,
    create_shopping_list,
    delete_shopping_list_by_id,
    delete_shopping_list_item,
    get_list_items_filtered,
    get_shopping_list_or_404,
    get_shopping_list_with_items,
    get_suggestions_for_list,
    get_suggestions_for_organization,
    list_shopping_lists,
    set_item_purchased,
    set_item_unpurchased,
    update_shopping_list_fields,
    update_shopping_list_item,
)

router = APIRouter(
    dependencies=[
        Depends(require_module('shopping_lists')),
        require_read_write('shopping_lists:read', 'shopping_lists:write'),
    ]
)


@router.post('', response_model=ShoppingListSchema, status_code=status.HTTP_201_CREATED)
async def create_shopping_list_endpoint(
    data: ShoppingListCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> ShoppingListModel:
    lang = get_current_lang()
    org_id = require_org(current_user)
    return await create_shopping_list(db, org_id, current_user.id, data.name, lang)


@router.get('', response_model=PaginatedResponse[ShoppingListSchema])
async def get_shopping_lists(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    active_only: bool = Query(True, description='Only active lists'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    lists, total = await list_shopping_lists(
        db, org_id, active_only, offset=offset, limit=limit
    )
    return PaginatedResponse.from_slice(lists, offset=offset, limit=limit, total=total)


@router.get('/suggestions', response_model=ShoppingSuggestionPreview)
@map_service_errors
async def preview_suggestions(
    include_low_stock: bool = True,
    include_frequent: bool = True,
    include_expiring: bool = True,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> ShoppingSuggestionPreview:
    """What the app would propose buying. It creates nothing.

    The dashboard used to reach this answer through a list it had just
    created, because the only route to it was addressed by ``list_id`` —
    so opening a preview left an empty active list the reader had never
    asked for, and Cancel did not take it back.

    The three switches are here because the button that opens this hangs
    on the tile counting shortages, and the engine returns every source it
    knows unless it is asked otherwise: a low-stock button opened a
    screenful of expired products.

    Declared above ``GET /{list_id}`` on purpose — below it, "suggestions"
    is parsed as a malformed UUID and answered 422.
    """
    suggestions = await get_suggestions_for_organization(
        require_org(current_user),
        db,
        include_low_stock=include_low_stock,
        include_frequent=include_frequent,
        include_expiring=include_expiring,
    )
    return ShoppingSuggestionPreview(
        suggestions=[
            ShoppingSuggestionSchema(
                item_id=s.item_id,
                template_id=s.template_id,
                category_id=s.category_id,
                name=s.name,
                quantity=s.quantity,
                uom_symbol=s.unit,
                uom_id=s.uom_id,
                source=s.source,
                priority=s.priority,
                estimated_price=s.estimated_price,
                notes=s.notes,
            )
            for s in suggestions
        ]
    )


@router.get('/{list_id}', response_model=ShoppingListWithItems)
async def get_shopping_list(
    list_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> ShoppingListModel:
    lang = get_current_lang()
    return await get_shopping_list_with_items(
        db, list_id, require_org(current_user), lang
    )


@router.put('/{list_id}', response_model=ShoppingListSchema)
async def update_shopping_list(
    list_id: UUID,
    data: ShoppingListUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> ShoppingListModel:
    lang = get_current_lang()
    shopping_list = await get_shopping_list_or_404(
        db, list_id, require_org(current_user), lang
    )
    return await update_shopping_list_fields(db, shopping_list, data)


async def _require_writable_list(
    db: AsyncSession,
    list_id: UUID,
    org_id: UUID,
    lang: Language,
) -> ShoppingListModel:
    """state-machine guard. Mutating endpoints must use this helper.

    Lists in `completed` or `archived` state are frozen for content edits.
    Only status transitions (completed→active) are allowed, and that path
    goes through the dedicated update endpoint.
    """
    shopping_list = await get_shopping_list_or_404(db, list_id, org_id, lang)
    if getattr(shopping_list, 'status', 'active') in ('completed', 'archived'):
        raise ConflictException(
            'SHOPPING_LIST_NOT_EDITABLE',
            get_error_message(
                'shopping_list_not_writable',
                lang,
                status=shopping_list.status,
            ),
        )
    return shopping_list


@router.delete('/{list_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_shopping_list(
    list_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> None:
    lang = get_current_lang()
    await delete_shopping_list_by_id(
        db, list_id, require_org(current_user), lang, current_user.id
    )
    return None


@router.post(
    '/{list_id}/items',
    response_model=ShoppingListItemSchema,
    status_code=status.HTTP_201_CREATED,
)
async def add_item_to_list(
    list_id: UUID,
    item_in: ShoppingListItemCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> ShoppingListItemModel:
    lang = get_current_lang()
    org_id = require_org(current_user)
    await _require_writable_list(db, list_id, org_id, lang)
    return await add_single_item(db, list_id, item_in, org_id, lang)


@router.post(
    '/{list_id}/items/bulk',
    # list-envelope-exception: a bulk result, the items this request just added
    response_model=list[ShoppingListItemSchema],
    status_code=status.HTTP_201_CREATED,
)
async def add_items_to_list_bulk(
    list_id: UUID,
    items_in: list[ShoppingListItemCreate],
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> list[ShoppingListItemModel]:
    lang = get_current_lang()
    org_id = require_org(current_user)
    await _require_writable_list(db, list_id, org_id, lang)
    return await bulk_add_items(db, list_id, items_in, org_id, lang)


@router.get(
    '/{list_id}/items', response_model=PaginatedResponse[ShoppingListItemSchema]
)
async def get_list_items(
    list_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    # tri-state filter — `purchased_only: bool` was ambiguous because
    # `False` meant "only pending" (not "no filter"), and there was no way to
    # fetch both purchased and pending in one call.
    purchased_filter: str = Query(
        'pending',
        pattern='^(pending|purchased|all)$',
        description=('Filter by purchase state. pending (default), purchased, or all.'),
    ),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    lang = get_current_lang()
    await get_shopping_list_or_404(db, list_id, require_org(current_user), lang)
    items = await get_list_items_filtered(db, list_id, purchased_filter)
    return PaginatedResponse.from_full_list(items, offset=offset, limit=limit)


@router.put('/{list_id}/items/{item_id}', response_model=ShoppingListItemSchema)
async def update_list_item(
    list_id: UUID,
    item_id: UUID,
    data: ShoppingListItemUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> ShoppingListItemModel:
    return await update_shopping_list_item(
        db, list_id, item_id, require_org(current_user), data, get_current_lang()
    )


@router.patch(
    '/{list_id}/items/{item_id}/purchase', response_model=ShoppingListItemSchema
)
async def mark_item_as_purchased(
    list_id: UUID,
    item_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> ShoppingListItemModel:
    return await set_item_purchased(
        db,
        list_id,
        item_id,
        require_org(current_user),
        current_user.id,
        get_current_lang(),
    )


@router.post(
    '/{list_id}/convert-to-po',
    response_model=ConvertToPOResponse,
    status_code=status.HTTP_201_CREATED,
)
@map_service_errors
async def convert_list_to_po(
    list_id: UUID,
    data: ConvertToPORequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> ConvertToPOResponse:
    """Convert un-purchased, template-linked items into a DRAFT Purchase Order."""
    org_id = require_org(current_user)
    po, converted, skipped = await convert_list_to_po_async(
        db,
        list_id,
        org_id,
        current_user.id,
        supplier_id=data.supplier_id,
        lang=get_current_lang(),
    )
    return ConvertToPOResponse(
        po_id=po.id,
        po_number=po.number,
        converted_count=converted,
        skipped_count=len(skipped),
        skipped_items=skipped,
    )


@router.patch(
    '/{list_id}/items/{item_id}/unpurchase', response_model=ShoppingListItemSchema
)
async def unmark_item(
    list_id: UUID,
    item_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> ShoppingListItemModel:
    return await set_item_unpurchased(
        db, list_id, item_id, require_org(current_user), get_current_lang()
    )


@router.delete('/{list_id}/items/purchased', status_code=status.HTTP_204_NO_CONTENT)
async def clear_purchased_items(
    list_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> None:
    await clear_purchased_from_list(
        db, list_id, require_org(current_user), get_current_lang()
    )


@router.delete('/{list_id}/items/{item_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_item_from_list(
    list_id: UUID,
    item_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> None:
    await delete_shopping_list_item(
        db, list_id, item_id, require_org(current_user), get_current_lang()
    )


@router.post(
    '/{list_id}/suggestions/generate', response_model=ShoppingSuggestionResponse
)
@map_service_errors
async def generate_auto_suggestions(
    list_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> ShoppingSuggestionResponse:
    _, unique_suggestions = await get_suggestions_for_list(
        list_id, require_org(current_user), db
    )

    suggestion_schemas = [
        ShoppingSuggestionSchema(
            item_id=s.item_id,
            template_id=s.template_id,
            category_id=s.category_id,
            name=s.name,
            quantity=s.quantity,
            uom_symbol=s.unit,
            uom_id=s.uom_id,
            source=s.source,
            priority=s.priority,
            estimated_price=s.estimated_price,
            notes=s.notes,
        )
        for s in unique_suggestions
    ]
    return ShoppingSuggestionResponse(
        message=f'Added {len(suggestion_schemas)} suggestions',
        added=len(suggestion_schemas),
        suggestions=suggestion_schemas,
    )


@router.post(
    '/{list_id}/suggestions/add-all', response_model=ShoppingSuggestionResponse
)
@map_service_errors
async def add_all_suggestions_to_list(
    list_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> ShoppingSuggestionResponse:
    existing_items_data, unique_suggestions = await get_suggestions_for_list(
        list_id, require_org(current_user), db
    )

    added_count, added_items = await add_suggestions_to_list(
        list_id, unique_suggestions, existing_items_data, db
    )

    suggestion_schemas = [
        ShoppingSuggestionSchema(
            item_id=item.item_id,
            template_id=item.template_id,
            category_id=item.category_id,
            name=item.name,
            quantity=item.quantity,
            uom_symbol=item.uom.symbol if item.uom else None,
            uom_id=item.uom_id,
            source=item.source,
            priority=item.priority,
            estimated_price=item.estimated_price,
            notes=item.notes,
        )
        for item in added_items
    ]
    return ShoppingSuggestionResponse(
        message=f'Added {added_count} suggestions to list',
        added=added_count,
        suggestions=suggestion_schemas,
    )
