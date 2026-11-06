"""Describe an equipment checkout to the approvals queue.

The approvals queue renders a card per request. A checkout request used to
render as eight characters of a UUID because the engine only knew how to
describe documents and purchase orders — the module that raises the request
is the one that knows what it points at, so this module claims the
``equipment_checkout`` target type the same way ``warehouse`` and
``purchase_orders`` claim theirs.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


async def get_target_summaries_by_ids_async(
    db: AsyncSession,
    org_id: UUID,
    target_ids: list[UUID],
) -> dict[UUID, Any]:
    """Lightweight equipment summaries for the approvals queue.

    Returns ``{item_id: EquipmentCheckoutTargetSummaryDTO}`` keyed by the
    item id that is the approval target. Items outside this organisation, or
    unknown, are omitted rather than raising. Empty input returns an empty
    dict.

    Items are Core entities, resolved through ``core_api.items.get_async``
    rather than by importing the Core table directly. The queue's equipment
    working set is bounded — one request per asset — so the per-id lookup is
    a bounded N, not an N+1 over a large table.
    """
    from app.core.public_api import core_api

    from ._schemas_equipment import EquipmentCheckoutTargetSummaryDTO
    from ._serial import serial_of

    if not target_ids:
        return {}

    summaries: dict[UUID, Any] = {}
    for item_id in target_ids:
        item = await core_api.items.get_async(db, org_id, item_id)
        if item is None:
            continue
        summaries[item_id] = EquipmentCheckoutTargetSummaryDTO(
            id=item.id,
            number=item.name,
            serial_number=serial_of(item),
        )
    return summaries
