"""Receiving's session start and reads — thin bindings of the machine.

Receiving accepts any receipt document type, plans no shelf on its lines
(nothing is drawn down when the line is built), marks its sessions
``direction: inbound`` and lists only those. The shared machine lives in
``_wms_session_ops``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from . import document_types as dt
from ._wms_direction import RECEIVING
from ._wms_line_utils import (  # noqa: F401  (re-exported for existing importers)
    _get_active_session_async,
    _resolve_lot_name,
    _resolve_product_name,
    _resolve_uom_symbol,
)
from ._wms_session_ops import (
    get_session_async,
    list_sessions_for_document_async,
    start_session_async,
)
from .models import Document, DocumentLine, WmsPickSession


async def start_receive_session_async(
    db: AsyncSession,
    document_id: UUID,
    org_id: UUID,
    user_id: UUID,
) -> WmsPickSession:
    session = await start_session_async(
        db,
        RECEIVING,
        document_id,
        org_id,
        user_id,
        is_supported=_supports_receiving,
        line_fields=_no_line_fields,
    )
    await db.flush()
    await db.refresh(session, ['lines'])
    return session


async def get_receive_session_async(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
) -> WmsPickSession | None:
    return await get_session_async(db, session_id, org_id)


async def list_receive_sessions_for_document_async(
    db: AsyncSession,
    document_id: UUID,
    org_id: UUID,
) -> list[WmsPickSession]:
    return await list_sessions_for_document_async(
        db, document_id, org_id, inbound_only=True
    )


def _supports_receiving(doc_type: str) -> bool:
    return dt.is_receipt(doc_type)


async def _no_line_fields(
    db: AsyncSession, line: DocumentLine, doc: Document
) -> dict[str, Any]:
    """Receiving plans no stock movement when the line is built."""
    return {'bin_location': None}
