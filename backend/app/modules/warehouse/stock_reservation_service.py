"""Stock reservation service for warehouse module — proxies to CoreAPI."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger(__name__)


async def reserve_for_document_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    location_id: UUID | None,
    needed_qty: Decimal,
    removal_strategy: str = 'FIFO',
    *,
    document_id: UUID,
    document_line_id: UUID | None = None,
    lot_id: UUID | None = None,
    require_active_lot: bool = True,
) -> Any:
    """Reserve available stock for a document line via CoreAPI.

    Per-document reservation records are created for safe per-document
    release.
    """
    from app.core.public_api import core_api

    return await core_api.stock.reserve_for_document_async(
        db,
        organization_id,
        product_template_id,
        location_id,
        needed_qty,
        removal_strategy=removal_strategy,
        document_id=document_id,
        document_line_id=document_line_id,
        lot_id=lot_id,
        require_active_lot=require_active_lot,
    )


async def release_for_document_async(
    db: AsyncSession,
    organization_id: UUID,
    document_id: UUID,
) -> None:
    """Release all reservations for a specific document via CoreAPI."""
    from app.core.public_api import core_api

    await core_api.stock.release_for_document_async(
        db,
        organization_id,
        document_id,
    )
