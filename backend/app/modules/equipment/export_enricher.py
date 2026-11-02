"""Export enrichment for the Core XLSX export.

Provides the "Assigned To" column — who or what holds each asset — without
Core importing the equipment module: this module registers the enricher in
:mod:`app.core.export_enrichers` at import time (see ``module.py``) and Core
calls it through the registry. The holder is resolved by the module's one
definition, so a deployed asset names the place it stands in instead of
exporting an empty cell.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Canonical absolute import on purpose: pytest loads the equipment conftest
# under the non-canonical name ``modules.equipment.*`` (no ``app.`` prefix),
# which re-executes this file; a relative ``from .models import`` would
# re-execute models.py under that alias and register every SQLAlchemy class
# twice ("Multiple classes found for path 'AuditResponse'"). The absolute
# path always resolves to the single canonical module object.
from app.modules.equipment._holder import holder_of_assignment
from app.modules.equipment.models import EquipmentAssignment

#: Column header used in the export sheet. English, like every core header
#: (Name, Quantity, …) — the import analyzer matches it back to the field.
ASSIGNED_TO_COLUMN = 'Assigned To'


async def get_active_assignments_map_async(
    db: AsyncSession, org_id: UUID
) -> dict[UUID, dict[str, object]]:
    """Active (not checked-in) holder names keyed by item id.

    A person's name or the place a deployment stands in — the column answers
    "who has it", and for a rack that is the rack.
    """
    result = await db.execute(
        select(EquipmentAssignment).where(
            EquipmentAssignment.organization_id == org_id,
            EquipmentAssignment.checked_in_at.is_(None),
        )
    )
    holders: dict[UUID, dict[str, object]] = {}
    for assignment in result.scalars().all():
        holder = holder_of_assignment(assignment)
        if holder is not None:
            holders[assignment.item_id] = {ASSIGNED_TO_COLUMN: holder.name}
    return holders
