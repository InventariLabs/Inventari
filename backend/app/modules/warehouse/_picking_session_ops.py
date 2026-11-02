"""Picking's session operations — thin bindings of the shared machine.

The machine itself lives in ``_wms_session_ops``; this module holds
picking's public names and nothing else, so routers, the module service
and the tests keep importing what they always did.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ._wms_direction import PICKING
from ._wms_session_ops import (
    cancel_session_async,
    complete_session_async,
    confirm_short_async,
    skip_line_async,
    undo_line_async,
)
from .models import WmsPickLine, WmsPickSession


async def confirm_short_pick_async(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
    line_id: UUID,
    picked_quantity: Decimal,
    discrepancy_code: str | None = None,
    discrepancy_reason: str | None = None,
    *,
    replace_scans: bool = False,
) -> WmsPickLine:
    return await confirm_short_async(
        db,
        PICKING,
        session_id,
        org_id,
        line_id,
        picked_quantity,
        discrepancy_code,
        discrepancy_reason,
        replace_scans=replace_scans,
    )


async def complete_pick_session_async(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
) -> WmsPickSession:
    return await complete_session_async(db, PICKING, session_id, org_id)


async def undo_pick_async(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
    line_id: UUID,
    user_id: UUID | None = None,
) -> WmsPickLine:
    return await undo_line_async(db, PICKING, session_id, org_id, line_id, user_id)


async def skip_pick_line_async(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
    line_id: UUID,
) -> WmsPickLine:
    return await skip_line_async(db, PICKING, session_id, org_id, line_id)


async def cancel_pick_session_async(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
    user_id: UUID | None = None,
) -> None:
    await cancel_session_async(db, PICKING, session_id, org_id, user_id)
