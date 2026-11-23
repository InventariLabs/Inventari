"""GET /api/v1/stock-lots/{lot_id} — one batch, and what is left of it.

A recall gives a warehouse hours to answer three questions: what came in
under that batch number, where the rest of it is now, and where the part
that left went to. All three facts were already recorded — the receipt, the
records, the dispatches — and nothing put them together, so answering meant
opening a database session.

This endpoint answers the first two. The third is the trace
(``GET /api/v1/stock-lots/{lot_id}/trace``): the ledger read by source rather
than by row — who supplied the batch and who it went to, with dates and
quantities, and the same for each batch a production run made of it. The raw
rows stay in the movement ledger, which already narrows by batch
(``GET /api/v1/stock-moves?lot_id=``).

Read-only. A batch changes state through the quarantine and release
operations the stock service owns, never through this route.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.stock_moves import client_timezone
from app.core.contracts import (
    LotStatus,
    LotTraceDTO,
    StockLotDetailDTO,
    StockLotDTO,
    SystemPermission,
    UserContextDTO,
)
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import NotFoundException, ServiceRejectionError
from app.core.public_api import core_api
from app.core.xlsx_export import to_xlsx_response
from app.i18n.service import get_current_lang
from app.schemas.pagination import PaginatedResponse
from app.services.analytics._common import org_timezone_async
from app.services.lot_trace_service import trace_to_export_frame

router = APIRouter()


class LotStatusUpdate(BaseModel):
    """Where the batch stands, and what the person was told.

    The reason is required, for releases as much as for holds. Both halves
    of that were argued: releasing a batch is a decision somebody will be
    asked about, and one rule is easier to keep than a table of which
    transitions need explaining. The friction is a sentence of typing, and
    it buys the one thing a status alone cannot say — why.

    Enforced here rather than in the service, because the module paths
    (``quarantine_lot_async`` / ``release_lot_async``) are code acting on a
    rule, not a person making a call, and have nobody to ask.
    """

    status: LotStatus
    reason: str = Field(min_length=1, max_length=500)

    @field_validator('reason')
    @classmethod
    def _not_only_spaces(cls, value: str) -> str:
        """A space bar is not a reason."""
        stripped = value.strip()
        if not stripped:
            raise ServiceRejectionError('reason_blank')
        return stripped


@router.get('/stock-lots', response_model=PaginatedResponse[StockLotDetailDTO])
async def list_stock_lots(
    product_template_id: UUID | None = Query(None),
    lot_status: LotStatus | None = Query(
        None,
        alias='status',
        description='Only batches in this state — the recall-day question.',
    ),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: object = require_permission(SystemPermission.ITEMS_READ),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> Any:
    """This organization's batches, newest first, with what is left of each."""
    org_id = require_org(current_user)
    items, total = await core_api.stock.list_lot_rows_async(
        db,
        org_id,
        product_template_id=product_template_id,
        status=lot_status.value if lot_status else None,
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse.from_slice(
        items=items, offset=offset, limit=limit, total=total
    )


@router.patch('/stock-lots/{lot_id}', response_model=StockLotDTO)
async def set_stock_lot_status(
    lot_id: UUID,
    payload: LotStatusUpdate,
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> Any:
    """Hold a batch back, or let it go again.

    Every picking path obeys the status, and this endpoint is the only place
    it is set. The reason is kept with the batch, because "quarantined" without
    "supplier notice 41/26" is a decision nobody can review.
    """
    org_id = require_org(current_user)
    lot = await core_api.stock.set_lot_status_async(
        db,
        org_id,
        lot_id,
        payload.status.value,
        payload.reason,
        user_id=current_user.id,
    )
    if lot is None:
        raise NotFoundException('stock_lot', get_current_lang())
    return lot


@router.get('/stock-lots/{lot_id}', response_model=StockLotDetailDTO)
async def get_stock_lot(
    lot_id: UUID,
    _: object = require_permission(SystemPermission.ITEMS_READ),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> Any:
    """One batch: what it is, what state it is in, and where it still is."""
    org_id = require_org(current_user)
    lot = await core_api.stock.get_lot_detail_async(db, org_id, lot_id)
    if lot is None:
        # Another organization's batch is not a permission problem to
        # explain — it is a batch this organization does not have.
        raise NotFoundException('stock_lot', get_current_lang())
    return lot


async def _trace_or_404(
    db: AsyncSession, current_user: UserContextDTO, lot_id: UUID
) -> LotTraceDTO:
    org_id = require_org(current_user)
    trace = await core_api.stock.trace_lot_async(
        db, org_id, lot_id, lang=get_current_lang()
    )
    if trace is None:
        raise NotFoundException('stock_lot', get_current_lang())
    return trace


@router.get(
    '/stock-lots/{lot_id}/trace',
    response_model=LotTraceDTO,
    dependencies=[require_permission(SystemPermission.PARTNERS_READ)],
)
async def trace_stock_lot(
    lot_id: UUID,
    _: object = require_permission(SystemPermission.ITEMS_READ),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> Any:
    """Who supplied the batch and who it went to — and the same for what was made of it.

    One step back and one step forward, the way a recall asks: each document
    or run that brought the batch in or sent it out, with its partner, date
    and quantity. A production run that consumed the batch leads to the batch
    it made, whose own trace follows.
    """
    return await _trace_or_404(db, current_user, lot_id)


@router.get(
    '/stock-lots/{lot_id}/trace/export/xlsx',
    response_model=None,
    dependencies=[require_permission(SystemPermission.PARTNERS_READ)],
)
async def export_stock_lot_trace_xlsx(
    lot_id: UUID,
    tz: str | None = Query(
        None,
        max_length=64,
        description=(
            "The reader's own IANA time zone, so the sheet agrees with the "
            'screen it was exported from. Falls back to the organization.'
        ),
    ),
    _: object = require_permission(SystemPermission.ITEMS_READ),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> Any:
    """The trace as a spreadsheet to hand to an inspector.

    The data sheet is a row per crossing; the second sheet says which batch
    the file is about and when it was made, because a file forwarded twice
    loses the screen it came from.
    """
    import pandas as pd

    trace = await _trace_or_404(db, current_user, lot_id)
    clock = client_timezone(tz) or await org_timezone_async(
        db, require_org(current_user)
    )
    root = trace.lots[0]
    about = [
        ('Batch', root.lot_name),
        ('Product', root.product_name),
        ('Expiry date', root.expiry_date.isoformat() if root.expiry_date else None),
        ('Batches made from it', str(len(trace.lots) - 1)),
        ('Generated', datetime.now(clock).strftime('%Y-%m-%d %H:%M')),
    ]
    if trace.truncated:
        about.append(
            (
                'Incomplete',
                'More batches were made from it than one trace follows; '
                'trace each listed batch on its own for the rest.',
            )
        )
    return to_xlsx_response(
        trace_to_export_frame(trace, clock),
        sheet_name='Trace',
        filename_stem='inventari_batch_trace',
        readme=pd.DataFrame(about, columns=['Field', 'Value']),
        readme_sheet='Batch',
    )
