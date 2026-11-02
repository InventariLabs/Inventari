"""Confirming the shelf by scan — the rule both WMS directions answer to.

With the profile's ``confirm_shelf_by_scan`` on, a session expects the
shelf's label before the product standing on it. The setting is read once,
when the session starts, and kept on the session: a worker halfway through a
document does not find the rules changed under them, and a scan does not pay
a profile read.

Which shelf a line expects differs by direction — picking plans it when the
session is built, receiving takes it from the putaway plan, which moves while
the session runs — so the caller hands the expectation in. What lives here is
the part that does not differ: recognising a shelf label, remembering the
shelf the worker stands at, and refusing a product that is not waiting there.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api

from ._wms_direction import WmsDirection
from ._wms_line_utils import shelf_caption
from ._wms_scan_ops import scan_response
from ._wms_session_close import DESTINATION_SCANNED_KEY, close_session_if_complete_async
from .models import WmsPickLine, WmsPickSession

#: Session ``meta_data`` keys: the setting as the session started, and the
#: shelf the last accepted shelf scan named.
CONFIRM_KEY = 'confirm_shelf'
SHELF_KEY = 'shelf_id'


def shelf_scan_required(session: WmsPickSession) -> bool:
    return bool((session.meta_data or {}).get(CONFIRM_KEY))


def confirmed_shelf_id(session: WmsPickSession) -> UUID | None:
    raw = (session.meta_data or {}).get(SHELF_KEY)
    return UUID(raw) if raw else None


async def _shelf_caption_async(db: AsyncSession, org_id: UUID, shelf_id: UUID) -> str:
    shelf = await core_api.locations.get_async(db, org_id, shelf_id)
    return shelf_caption(shelf) if shelf else str(shelf_id)


async def _scannable_shelves_async(
    db: AsyncSession, org_id: UUID, shelf_ids: list[UUID | None]
) -> list[UUID]:
    """The shelves among *shelf_ids* that carry a code a worker can scan.

    A place counts when it has a code of its own or a STORAGE pool label
    printed for it: the label scans as the place. A place with neither has
    nothing to scan, so asking for one would strand the line: Receive may put
    stock straight on the organization's codeless main warehouse. Such a shelf
    is not asked for; the product is taken on the worker's word, as with the
    setting off.
    """
    scannable: list[UUID] = []
    for shelf_id in dict.fromkeys(s for s in shelf_ids if s is not None):
        if await core_api.locations.scannable_code_async(db, org_id, shelf_id):
            scannable.append(shelf_id)
    return scannable


async def answer_shelf_scan_async(
    db: AsyncSession,
    direction: WmsDirection,
    session: WmsPickSession,
    org_id: UUID,
    barcode: str,
    expected: list[UUID | None],
) -> dict[str, Any] | None:
    """Answer a scan that names a shelf, or ``None`` when it names none.

    *expected* is the shelf of each pending line, in the order the worker is
    sent through them; a shelf without a code is left out (see
    ``_scannable_shelves_async``). A shelf some pending line waits at is
    remembered; any other shelf is refused with the one the next line waits at,
    and forgets the shelf confirmed before it.
    """
    if not shelf_scan_required(session):
        return None
    scanned = await core_api.locations.find_by_scanned_code_async(db, org_id, barcode)
    if scanned is None:
        return None
    coded = set(await _scannable_shelves_async(db, org_id, expected))
    wanted = [shelf for shelf in expected if shelf in coded]
    if not wanted:
        return None

    if scanned.id in wanted:
        session.meta_data = {**(session.meta_data or {}), SHELF_KEY: str(scanned.id)}
        await db.flush()
        return scan_response(
            direction,
            'shelf_confirmed',
            shelf=shelf_caption(scanned),
            shelf_id=scanned.id,
            message=f'Location {shelf_caption(scanned)} confirmed',
        )
    # The worker now stands somewhere else: the earlier confirmation no longer
    # holds, and the next product waits for the right label again.
    session.meta_data = {
        key: value
        for key, value in (session.meta_data or {}).items()
        if key != SHELF_KEY
    }
    await db.flush()
    waiting = await _shelf_caption_async(db, org_id, wanted[0])
    return scan_response(
        direction,
        'wrong_shelf',
        shelf=waiting,
        shelf_id=wanted[0],
        message=f'Wrong location: scan {waiting}',
    )


async def answer_destination_scan_async(
    db: AsyncSession,
    direction: WmsDirection,
    session: WmsPickSession,
    org_id: UUID,
    barcode: str,
    destination: UUID,
) -> dict[str, Any]:
    """Answer a scan once every line is answered and the destination is awaited.

    The destination's label ends the session; any other code is refused with
    the one expected, and the session stays open.
    """
    scanned = await core_api.locations.find_by_scanned_code_async(db, org_id, barcode)
    if scanned is None or scanned.id != destination:
        waiting = await _shelf_caption_async(db, org_id, destination)
        return scan_response(
            direction,
            'wrong_shelf',
            shelf=waiting,
            shelf_id=destination,
            message=f'Wrong location: scan {waiting}',
        )
    session.meta_data = {**(session.meta_data or {}), DESTINATION_SCANNED_KEY: True}
    await close_session_if_complete_async(
        db, session, short_status=direction.short_status
    )
    await db.flush()
    return scan_response(
        direction,
        'shelf_confirmed',
        shelf=shelf_caption(scanned),
        shelf_id=scanned.id,
        session_complete=True,
        message=f'Location {shelf_caption(scanned)} confirmed',
    )


async def refuse_unconfirmed_shelf_async(
    db: AsyncSession,
    direction: WmsDirection,
    session: WmsPickSession,
    org_id: UUID,
    line: WmsPickLine,
    expected_shelf_id: UUID | None,
) -> dict[str, Any] | None:
    """The refusal for a product scanned before its shelf, or ``None`` to go on."""
    if not shelf_scan_required(session) or expected_shelf_id is None:
        return None
    if confirmed_shelf_id(session) == expected_shelf_id:
        return None
    if not await _scannable_shelves_async(db, org_id, [expected_shelf_id]):
        return None
    waiting = await _shelf_caption_async(db, org_id, expected_shelf_id)
    return scan_response(
        direction,
        'shelf_required',
        line_id=line.id,
        product_name=line.product_name,
        expected_quantity=float(line.expected_quantity),
        uom_symbol=line.uom_symbol,
        shelf=waiting,
        shelf_id=expected_shelf_id,
        message=f'Scan the location first: {waiting}',
    )
