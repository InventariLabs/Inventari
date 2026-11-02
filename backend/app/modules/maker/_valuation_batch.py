"""Collapse duplicate ingredient IDs before asking Core's batch cost policy."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cost_estimates import UnitCostEstimate
from app.core.public_api import core_api


async def fetch_estimates_batch(
    db: AsyncSession,
    organization_id: UUID,
    flat: list[tuple[UUID, Decimal, str]],
) -> dict[UUID, UnitCostEstimate]:
    """Estimate each distinct stock-unit cost once, including its source."""
    child_ids = list(dict.fromkeys(child_id for child_id, _, _ in flat))
    return await core_api.valuation.estimate_unit_cost_async(
        db, organization_id, child_ids
    )
