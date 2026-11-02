"""GET /api/v1/stock-lots/{lot_id} — one batch, and what is left of it.

A recall gives a warehouse hours to answer three questions: what came in
under that batch number, where the rest of it is now, and where the part
that left went to. All three facts were already recorded — the receipt, the
records, the dispatches — and nothing put them together, so answering meant
opening a database session.

This endpoint answers the first two. The third is the movement ledger,
which already narrows by batch (``GET /api/v1/stock-moves?lot_id=``), and
keeping them apart is deliberate: the trail is a page of rows that grows
without limit, and the batch is one small record.

Read-only. A batch changes state through the quarantine and release
operations the stock service owns, never through this route.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    LotStatus,
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
from app.i18n.service import get_current_lang
from app.schemas.pagination import PaginatedResponse

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

    Every picking path already obeys the status; until now nobody could set
    it. The reason is kept with the batch, because "quarantined" without
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
