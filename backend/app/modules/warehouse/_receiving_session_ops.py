"""Receiving's session operations — thin bindings of the shared machine.

The machine itself lives in ``_wms_session_ops``; this module holds
receiving's public names and nothing else, so routers, the module service
and the tests keep importing what they always did. The close wrapper is the
one exception: it binds the receiving short status for its own callers.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ._wms_direction import RECEIVING
from ._wms_session_close import (
    close_session_if_complete_async as _close_if_complete,
)
from ._wms_session_ops import (
    cancel_session_async,
    complete_session_async,
    confirm_short_async,
    skip_line_async,
    undo_line_async,
)
from .models import WmsPickLine, WmsPickSession


async def close_session_if_complete_async(
    db: AsyncSession, session: WmsPickSession
) -> None:
    """Mark the receiving session terminal once every line is resolved."""
    await _close_if_complete(db, session, short_status=RECEIVING.short_status)


async def confirm_short_receive_async(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
    line_id: UUID,
    received_quantity: Decimal,
    discrepancy_code: str | None = None,
    discrepancy_reason: str | None = None,
    may_exceed_over_receipt: bool = False,
    *,
    replace_scans: bool = False,
    held_quantity: Decimal = Decimal('0'),
) -> WmsPickLine:
    return await confirm_short_async(
        db,
        RECEIVING,
        session_id,
        org_id,
        line_id,
        received_quantity,
        discrepancy_code,
        discrepancy_reason,
        may_exceed_over_receipt=may_exceed_over_receipt,
        replace_scans=replace_scans,
        held_quantity=held_quantity,
    )


async def complete_receive_session_async(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
) -> WmsPickSession:
    return await complete_session_async(db, RECEIVING, session_id, org_id)


async def undo_receive_async(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
    line_id: UUID,
    user_id: UUID | None = None,
) -> WmsPickLine:
    return await undo_line_async(db, RECEIVING, session_id, org_id, line_id, user_id)


async def skip_receive_line_async(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
    line_id: UUID,
) -> WmsPickLine:
    return await skip_line_async(db, RECEIVING, session_id, org_id, line_id)


async def cancel_receive_session_async(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
    user_id: UUID | None = None,
) -> None:
    await cancel_session_async(db, RECEIVING, session_id, org_id, user_id)
