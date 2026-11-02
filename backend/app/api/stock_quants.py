"""GET /api/v1/stock-quants — what lies where, and how much of it is spoken for.

The item list shows ``Item.quantity``: one row per record, and the right
answer for a household. A warehouse works from the sum — how much of a
product is at one place, out of which batch, and how much of it is already
promised. That is a quant, the records of a group summed with their
reservation rows beside them (``stock_quants_from_records``), and until now
the only way in was a route the warehouse module registered,
so an organization running purchase orders and stock takes without documents
could not open its own shelves.

Reservations are never subtracted from the quantity: "six on the shelf, four
promised" and "two on the shelf" are different sentences, and only the first
one lets a picker plan. Both numbers and their difference are columns.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import StockQuantRowDTO, SystemPermission, UserContextDTO
from app.core.db_utils import LIST_COUNT_CAP
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.public_api import core_api
from app.schemas.pagination import PaginatedResponse

router = APIRouter()


@router.get('/stock-quants', response_model=PaginatedResponse[StockQuantRowDTO])
async def list_stock_quants(
    product_template_id: UUID | None = Query(None, description='Only this product.'),
    location_id: UUID | None = Query(
        None, description='This place and everything below it.'
    ),
    lot_id: UUID | None = Query(None, description='Only this batch.'),
    include_empty: bool = Query(
        False,
        description=(
            'Include shelves drained to zero with nothing promised — the '
            'only record of where a product used to be.'
        ),
    ),
    search: str | None = Query(
        None,
        description=(
            'Narrow the shelves to a product or a batch: what the product '
            'list matches on (name, brand, barcode, SKU) plus the batch name '
            'this list prints in its own column.'
        ),
    ),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: object = require_permission(SystemPermission.ITEMS_READ),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> Any:
    """This organization's stock, grouped by place."""
    org_id = require_org(current_user)
    items, total = await core_api.stock.list_quant_rows_async(
        db,
        org_id,
        product_template_id=product_template_id,
        location_id=location_id,
        lot_id=lot_id,
        include_empty=include_empty,
        search=search,
        limit=limit,
        offset=offset,
        count_cap=LIST_COUNT_CAP,
    )
    return PaginatedResponse.from_slice(
        items=items, offset=offset, limit=limit, total=total, count_cap=LIST_COUNT_CAP
    )
