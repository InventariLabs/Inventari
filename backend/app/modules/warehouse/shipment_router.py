"""Shipping a dispatch — the carriers to suggest.

The shipment itself is written by ``PATCH /warehouse/documents/{id}/complete`` and read
with the document; this router answers what the completion dialog offers
while the carrier is typed.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_async_db, require_org
from app.core.modules import require_module

from . import shipment_service as svc
from .shipment_schemas import CarrierSuggestions

router = APIRouter(dependencies=[Depends(require_module('warehouse'))])


@router.get('/shipments/carriers', response_model=CarrierSuggestions)
async def list_carriers(
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> CarrierSuggestions:
    """The organization's carriers, the most recently used first."""
    return CarrierSuggestions(carriers=await svc.list_carriers_async(db, org_id))
