from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import SystemPermission
from app.core.contracts.dtos import UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import (
    ConflictException,
    ServiceRejectionError,
    refusal_code,
    refusal_text,
)
from app.core.public_api import core_api

from .product_search_service import search_products_async, search_stock_items_async
from .product_stub_service import quick_create_stub_async
from .schemas import ProductSearchResult, QuickCreateStub

router = APIRouter()


@router.get(
    '/product-search',
    # list-envelope-exception: search hits for a picker, capped by limit
    response_model=list[ProductSearchResult],
)
async def product_search(
    q: str = Query(''),
    limit: int = Query(10, ge=1, le=50),
    location_id: UUID | None = Query(
        None,
        description=(
            'Narrow a stock search to this location and the ones under it. '
            'On its own it also selects the stock search, for callers written '
            'before the explicit flag.'
        ),
    ),
    stock: bool = Query(
        False,
        description=(
            'Answer with the stock on hand rather than the product catalogue. '
            'Results then carry item_id, which the lines of a document taking '
            'goods off a shelf require. Combine with location_id to narrow it.'
        ),
    ),
    merge: bool = Query(
        False,
        description=(
            'Fold records nothing on a row can tell apart into one hit '
            'carrying the shelf total. Only for documents whose executor '
            'pulls across records — a transfer moves a single record and '
            'needs the rows one by one.'
        ),
    ),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    if not q or not q.strip():
        raise ServiceRejectionError('search_query_empty')
    org_id = require_org(current_user)
    if stock or location_id is not None:
        return await search_stock_items_async(
            db, org_id, q, location_id, limit=limit, merge=merge
        )
    return await search_products_async(db, org_id, q, limit=limit)


@router.post(
    '/product-search/quick-create',
    response_model=ProductSearchResult,
    status_code=status.HTTP_201_CREATED,
)
async def product_quick_create(
    data: QuickCreateStub,
    # Founding a product template is items work: the door used to hand a
    # stub to any documents writer, and the record it founded was real.
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    try:
        tpl = await quick_create_stub_async(
            db, org_id, data.name, data.barcode, current_user.id
        )
        is_stub = tpl.meta_data.get('is_stub', False) if tpl.meta_data else False
        uom_symbol = None
        if tpl.uom_id:
            uom_dto = await core_api.uoms.get_async(db, tpl.uom_id, org_id)
            if uom_dto:
                uom_symbol = uom_dto.symbol
        return ProductSearchResult(
            product_template_id=str(tpl.id),
            name=tpl.name,
            sku=tpl.sku,
            barcode=tpl.barcode,
            brand=tpl.brand,
            uom_id=str(tpl.uom_id) if tpl.uom_id else None,
            uom_symbol=uom_symbol,
            image_url=tpl.image_url,
            is_stub=is_stub,
        )
    except ValueError as exc:
        raise ConflictException(
            code=refusal_code(exc, 'STUB_CREATION_FAILED'),
            message=refusal_text(exc),
        ) from exc
