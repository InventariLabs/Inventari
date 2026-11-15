"""The value of the production runs that are started and not yet finished.

What a started run took off the records stays the organization's until the
run closes, so the stock value adds it back (``app.core.work_in_progress``).
A portion already put on the shelf carries its share of that cost into the
cost layers, so the run holds only what the portions have not taken.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import quantise

from .models import ProductionOrder, ProductionPortion


async def work_in_progress_value_async(
    db: AsyncSession, organization_id: UUID, as_of: datetime | None
) -> Decimal:
    """What the runs under way at *as_of* (now when ``None``) hold, in the org's money.

    A run is under way from the moment it started until it completed or was
    cancelled, so a past date asks the same question of the same rows.
    """
    held = [
        ProductionOrder.organization_id == organization_id,
        ProductionOrder.started_at.is_not(None),
        ProductionOrder.material_cost.is_not(None),
    ]
    if as_of is None:
        held.append(ProductionOrder.status == 'IN_PROGRESS')
    else:
        held += [
            ProductionOrder.started_at <= as_of,
            or_(
                ProductionOrder.completed_at.is_(None),
                ProductionOrder.completed_at > as_of,
            ),
        ]
    runs = (
        await db.execute(
            select(
                ProductionOrder.id,
                ProductionOrder.material_cost,
                ProductionOrder.planned_qty,
            ).where(*held)
        )
    ).all()
    if not runs:
        return Decimal('0')
    portioned_stmt = select(
        ProductionPortion.production_order_id, func.sum(ProductionPortion.qty)
    ).where(ProductionPortion.production_order_id.in_([run.id for run in runs]))
    if as_of is not None:
        portioned_stmt = portioned_stmt.where(ProductionPortion.created_at <= as_of)
    portioned: dict[UUID, Decimal] = {
        row[0]: row[1]
        for row in (
            await db.execute(
                portioned_stmt.group_by(ProductionPortion.production_order_id)
            )
        ).all()
    }
    total = Decimal('0')
    for run in runs:
        share = (
            min(Decimal('1'), portioned.get(run.id, Decimal('0')) / run.planned_qty)
            if run.planned_qty > 0
            else Decimal('0')
        )
        total += run.material_cost * (Decimal('1') - share)
    return quantise(total)
