"""Every delivery cost that reached no product, listed and added up."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_async_db, require_org
from app.core.modules import require_module

from . import cost_variance_service as svc
from .schemas import CostVarianceRow, CostVariancesList

router = APIRouter(dependencies=[Depends(require_module('warehouse'))])


@router.get('', response_model=CostVariancesList)
async def list_cost_variances(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """A page of the organization's variances in a period, newest first.

    Part of no stock value: the list and its sums are the whole of what the
    figures do. The sums cover the whole period, not the page, and are kept
    per currency because a variance is never converted.
    """
    rows, total = await svc.list_for_organization_async(
        db, org_id, date_from=date_from, date_to=date_to, limit=limit, offset=offset
    )
    items = [
        CostVarianceRow(
            id=variance.id,
            document_id=variance.document_id,
            kind=variance.kind,
            amount=variance.amount,
            currency=variance.currency or document_currency,
            reason=variance.reason,
            occurred_on=variance.occurred_on,
            document_number=number,
        )
        for variance, number, document_currency in rows
    ]
    page = CostVariancesList.from_slice(items, offset=offset, limit=limit, total=total)
    page.totals = await svc.totals_by_currency_async(
        db, org_id, date_from=date_from, date_to=date_to
    )
    return page
