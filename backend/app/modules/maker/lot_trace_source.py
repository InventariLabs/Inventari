"""Name a production run in a batch's trace, and let the trace follow it.

A run posts the ingredients it consumed and the batch it made under
``reference_type='maker_production'`` and the order's id. For a recall the run
is a hop: the flour that went into it is now in the bread it made, and the
bread's customers are the flour's customers too. So the source says it
``transforms``, and Core's trace follows each batch that came in under the run.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import LotTraceReferenceDTO
from app.core.module_sdk import LotTraceSource

from .models import ProductionOrder


class ProductionLotTraceSource(LotTraceSource):
    """Maker's production runs, as a recall reads them."""

    reference_type = 'maker_production'
    transforms = True

    async def describe_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        reference_ids: Sequence[UUID],
    ) -> dict[UUID, LotTraceReferenceDTO]:
        rows = (
            await db.execute(
                select(ProductionOrder.id, ProductionOrder.number).where(
                    ProductionOrder.organization_id == organization_id,
                    ProductionOrder.id.in_(reference_ids),
                )
            )
        ).all()
        # A run from before runs were numbered has no number to print; the
        # trace still lists it, as a production run on its date.
        return {
            order_id: LotTraceReferenceDTO(label=number) for order_id, number in rows
        }
