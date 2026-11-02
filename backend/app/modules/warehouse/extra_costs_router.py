"""Freight, duty and insurance on a receipt — CRUD and a preview of the effect.

The preview is the point of the screen: a person has to see that the unit
cost becomes 12.00 instead of 10.00 *before* they post, because after that
the answer is a refusal.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import catalogue_refusal
from app.core.modules import require_module

from . import document_types as dt
from . import extra_costs_service as svc
from ._document_workflow_crud import _get_doc_for_update
from .extra_costs_service import _planned_quantity
from .schemas import (
    ExtraCostCreate,
    ExtraCostLinePreview,
    ExtraCostOut,
    ExtraCostsView,
)

router = APIRouter(dependencies=[Depends(require_module('warehouse'))])


async def _view(db: AsyncSession, doc: Any) -> ExtraCostsView:
    costs = await svc.list_async(db, doc.organization_id, doc.id)
    surcharges, fell_back = await svc.surcharges_async(db, doc, planned=True)

    lines = []
    for line in doc.lines:
        quantity = _planned_quantity(line)
        if quantity <= 0:
            continue
        surcharge = surcharges.get(line.id, Decimal('0'))
        unit_after: Decimal | None = None
        if quantity > 0 and (line.unit_price is not None or surcharge):
            unit_after = (line.unit_price or Decimal('0')) + surcharge / quantity
        lines.append(
            ExtraCostLinePreview(
                line_id=line.id,
                product_name=line.name,
                quantity=quantity,
                unit_price=line.unit_price,
                surcharge=surcharge,
                unit_cost_after=unit_after,
            )
        )

    return ExtraCostsView(
        costs=[
            ExtraCostOut.model_validate(cost, from_attributes=True) for cost in costs
        ],
        total=sum((Decimal(cost.amount) for cost in costs), start=Decimal('0')),
        currency=doc.currency,
        editable=doc.status in svc.OPEN_STATES,
        fell_back=fell_back,
        lines=lines,
    )


@router.get('/{doc_id}/extra-costs', response_model=ExtraCostsView)
async def list_extra_costs(
    doc_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """The costs on this receipt, and what they do to each line."""
    doc = await _get_doc_for_update(db, org_id, doc_id)
    return await _view(db, doc)


@router.post(
    '/{doc_id}/extra-costs',
    response_model=ExtraCostsView,
    status_code=status.HTTP_201_CREATED,
)
async def add_extra_cost(
    doc_id: UUID,
    data: ExtraCostCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
    _: None = require_permission('warehouse:manage'),
) -> Any:
    """Add a cost to an unposted receipt."""
    doc = await _get_doc_for_update(db, org_id, doc_id)
    if not dt.is_receipt(doc.type):
        raise catalogue_refusal('extra_cost_not_a_receipt')
    # A refusal of the service (``ExtraCostRefusedError``) is keyed; the
    # global handler answers it with its code.
    await svc.add_async(
        db,
        org_id,
        doc,
        kind=data.kind.value,
        amount=data.amount,
        currency=data.currency,
        allocation_method=data.allocation_method.value,
        note=data.note,
        user_id=current_user.id,
    )
    await db.commit()
    doc = await _get_doc_for_update(db, org_id, doc_id)
    return await _view(db, doc)


@router.delete('/{doc_id}/extra-costs/{cost_id}', response_model=ExtraCostsView)
async def delete_extra_cost(
    doc_id: UUID,
    cost_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
    _: None = require_permission('warehouse:manage'),
) -> Any:
    """Take a cost off an unposted receipt."""
    doc = await _get_doc_for_update(db, org_id, doc_id)
    await svc.delete_async(db, org_id, doc, cost_id, user_id=current_user.id)
    await db.commit()
    doc = await _get_doc_for_update(db, org_id, doc_id)
    return await _view(db, doc)
