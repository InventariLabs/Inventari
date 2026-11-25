"""The home shelf a put-away learns.

Mounted by ``warehouse/router.py``. Endpoints:
  - PUT    /putaway/home-shelf                          make a shelf a product's home
  - GET    /documents/{id}/home-shelf-offers            what a posted one-step receipt asks
  - GET    /putaway/home-shelf/silenced                 products not asked about
  - PUT    /putaway/home-shelf/silenced/{product_id}    stop asking about a product
  - DELETE /putaway/home-shelf/silenced/{product_id}    ask about it again

A home shelf is a product-scoped putaway rule (``home_shelf_service``), so the
rules list shows and edits it like any other.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import NotFoundException, map_service_errors
from app.core.module_sdk import PaginatedResponse
from app.i18n.service import get_current_lang

from ._receipt_home_shelf import receipt_home_shelf_offers_async
from .document_query_service import get_document
from .home_shelf_service import (
    list_silenced_async,
    set_home_shelf_async,
    silence_async,
    unsilence_async,
)
from .putaway_schemas import (
    HomeShelfOffer,
    HomeShelfOut,
    HomeShelfSet,
    HomeShelfSilencedOut,
)

router = APIRouter()


@router.put('/putaway/home-shelf', response_model=HomeShelfOut)
@map_service_errors
async def put_home_shelf(
    data: HomeShelfSet,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """Make a shelf the product's home: the head of the product's own rule.

    A receiving area, the quarantine location and a location that does not
    take stock are refused, each with its own reason.
    """
    org_id = require_org(current_user)
    rule = await set_home_shelf_async(
        db, org_id, current_user.id, data.product_template_id, data.location_id
    )
    return HomeShelfOut(
        rule_id=rule.id,
        product_template_id=data.product_template_id,
        location_id=data.location_id,
    )


@router.get(
    '/documents/{doc_id}/home-shelf-offers',
    response_model=PaginatedResponse[HomeShelfOffer],
)
async def list_receipt_home_shelf_offers(
    doc_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """Which shelves a posted receipt in one step offers as a product's home.

    One entry for each product whose line was put on a shelf other than the
    suggested one; empty when the warehouse keeps no fixed places, receives in
    two steps (the put-away asks) or the product's question was silenced.
    """
    org_id = require_org(current_user)
    doc = await get_document(db, org_id, doc_id)
    if doc is None:
        raise NotFoundException('document', get_current_lang())
    offers = await receipt_home_shelf_offers_async(db, org_id, doc)
    return PaginatedResponse.from_slice(offers, 0, max(len(offers), 1), len(offers))


@router.get(
    '/putaway/home-shelf/silenced',
    response_model=PaginatedResponse[HomeShelfSilencedOut],
)
async def list_silenced(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """The products whose put-away does not ask for a home shelf."""
    org_id = require_org(current_user)
    rows = await list_silenced_async(db, org_id)
    page = [
        HomeShelfSilencedOut(product_template_id=template_id, product_name=name)
        for template_id, name in rows[offset : offset + limit]
    ]
    return PaginatedResponse.from_slice(page, offset, limit, len(rows))


@router.put(
    '/putaway/home-shelf/silenced/{product_template_id}',
    status_code=status.HTTP_204_NO_CONTENT,
)
@map_service_errors
async def silence_product(
    product_template_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Response:
    """Do not ask about this product's home shelf again."""
    await silence_async(
        db, require_org(current_user), current_user.id, product_template_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    '/putaway/home-shelf/silenced/{product_template_id}',
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unsilence_product(
    product_template_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Response:
    """Ask about this product's home shelf again."""
    await unsilence_async(
        db, require_org(current_user), current_user.id, product_template_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
