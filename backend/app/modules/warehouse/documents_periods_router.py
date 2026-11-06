from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import ConflictException, refusal_code, refusal_text
from app.core.module_sdk import PaginatedResponse
from app.i18n.service import get_current_lang

from .inventory_period_service import close_period, list_periods, reopen_period
from .schemas import InventoryPeriodCreate, InventoryPeriodSchema

router = APIRouter()

#: The months a period can be: the row is made on its first touch, so a path
#: naming month 13 used to close a thirteenth month. The years are the ones
#: the list's own filter takes.
_Year = Annotated[int, Path(ge=2000, le=2100)]
_Month = Annotated[int, Path(ge=1, le=12)]


#: The refusal sentence is translated eagerly by the service (the catalog key
#: formats with the request language), so the 409 envelope names the language
#: it already speaks — the same shape the 400 handler stamps on keyed
#: rejections elsewhere (e.g. the stock-take status refusal). The sentence
#: reaches real screens through stale client state: a page left open while
#: another operator closes the period still offers the padlock, and that
#: click is what a reader in any language ends up reading.


@router.get('/periods', response_model=PaginatedResponse[InventoryPeriodSchema])
async def list_inventory_periods(
    year: int | None = Query(None, ge=2000, le=2100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    periods, total = await list_periods(
        db, org_id, year=year, limit=limit, offset=offset
    )
    return PaginatedResponse.from_slice(periods, offset, limit, total)


@router.post('/periods/{year}/{month}/close', response_model=InventoryPeriodSchema)
async def close_inventory_period(
    year: _Year,
    month: _Month,
    data: InventoryPeriodCreate | None = None,
    _: None = require_permission('warehouse:manage'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    try:
        period = await close_period(
            db, org_id, year, month, current_user.id, notes=data.notes if data else None
        )
    except ValueError as exc:
        raise ConflictException(
            code=refusal_code(exc, 'PERIOD_CLOSED'),
            message=refusal_text(exc),
            details={'lang': get_current_lang()},
        ) from exc
    return period


@router.post('/periods/{year}/{month}/reopen', response_model=InventoryPeriodSchema)
async def reopen_inventory_period(
    year: _Year,
    month: _Month,
    data: InventoryPeriodCreate | None = None,
    _: None = require_permission('warehouse:manage'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    try:
        period = await reopen_period(
            db, org_id, year, month, current_user.id, notes=data.notes if data else None
        )
    except ValueError as exc:
        raise ConflictException(
            code=refusal_code(exc, 'PERIOD_CLOSED'),
            message=refusal_text(exc),
            details={'lang': get_current_lang()},
        ) from exc
    return period
