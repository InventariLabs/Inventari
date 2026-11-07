from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.module_sdk import PaginatedResponse
from app.core.modules import require_module
from app.core.public_api import core_api

from ._over_receipt import asking_the_holder
from ._receipt_planning import (
    SOURCE_DOCUMENT,
    attach_receipt_plans,
    floor_shelf_offer_async,
)
from ._wms_session_access import (
    _get_owned_session_for_document_async,
    _get_session_for_document_async,
    _session_held_conflict,
    take_over_session_async,
)
from ._wms_session_ops import SessionHeldByOtherUserError
from ._wms_session_release import pause_session_async
from ._wms_shelf import confirmed_shelf_id, shelf_scan_required
from .document_query_service import get_document
from .models import WmsPickLine, WmsPickSession
from .wms_receiving_schemas import (
    ReceiveLineStatus,
    WmsReceiveLineOut,
    WmsReceiveScanRequest,
    WmsReceiveScanResponse,
    WmsReceiveSessionOut,
    WmsReceiveShortRequest,
    WmsReceiveUndoResponse,
)
from .wms_receiving_service import (
    cancel_receive_session_async,
    complete_receive_session_async,
    get_receive_session_async,
    list_receive_sessions_for_document_async,
    scan_receive_async,
    short_receive_async,
    skip_receive_line_async,
    start_receive_session_async,
    undo_receive_async,
)

router = APIRouter(dependencies=[Depends(require_module('warehouse'))])


#: Receiving reuses the picking machinery down to the table name, so a line
#: taken in full is stored as ``picked``. Nothing in receiving has ever had
#: that word: its screen, its summary and its label map are all written
#: against ``received``. Translating here — the one place a stored line
#: becomes a receiving line — is what stops a reloaded session from showing
#: a received line as pending, with the buttons to receive it a second time.
_STORED_TO_RECEIVING_STATUS: dict[str, ReceiveLineStatus] = {
    'pending': 'pending',
    'picked': 'received',
    'short': 'short',
    'skipped': 'skipped',
}


#: What a receiving line repeats from its document line: the plan, the
#: shelf somebody named by hand, and how much of the count is held back.
#: Listed once here, so a field added to the document line and forgotten
#: here shows up as a missing name rather than as a screen quietly short of
#: a sentence.
_PLAN_FIELDS = (
    'held_quantity',
    'discrepancy_code',
    'target_location_id',
    'planned_location_id',
    'planned_location_name',
    'planned_source',
    'planned_rule_match_key',
    'planned_rule_match_name',
    'planned_rule_warning',
    'planned_over_capacity',
    'planned_capacity_used',
    'planned_capacity_max',
    'planned_shelf_fill',
)


async def _receipt_plans(
    db: AsyncSession, org_id: UUID, document_id: UUID
) -> dict[UUID, dict[str, Any]]:
    """Planned shelf per document line, keyed by that line's id.

    With it rides what else the floor card reads off the document line:
    whether an order stands behind it.

    Goes through ``attach_receipt_plans`` — the one function the document
    read and the executor both use — and copies what it left on the ORM
    objects. A second decision function for the floor screen is precisely
    what would let the preview and the booking drift apart, which is why the
    planner was made shared to begin with.
    """
    doc = await get_document(db, org_id, document_id)
    if doc is None:
        return {}
    await attach_receipt_plans(db, doc)
    plans = {
        line.id: {f: getattr(line, f, None) for f in _PLAN_FIELDS} for line in doc.lines
    }
    for line in doc.lines:
        plan = plans[line.id]
        plan['from_order'] = line.source_po_line_id is not None
        plan['expected_is_count'] = line.expected_is_count
        if plan['planned_source'] != SOURCE_DOCUMENT or doc.target_location_id is None:
            continue
        offer = await floor_shelf_offer_async(
            db,
            org_id,
            doc.target_location_id,
            line.product_template_id
            or (line.item.template_id if line.item is not None else None),
        )
        if offer is None:
            continue
        shelf = await core_api.locations.get_async(db, org_id, offer[0])
        plan['suggested_location_id'] = offer[0]
        plan['suggested_location_name'] = shelf.name if shelf else None
        plan['suggested_source'] = offer[1]
    return plans


def _line_to_out(
    line: WmsPickLine, plans: dict[UUID, dict[str, Any]]
) -> WmsReceiveLineOut:
    return WmsReceiveLineOut(
        id=line.id,
        document_line_id=line.document_line_id,
        pick_order=line.pick_order,
        status=_STORED_TO_RECEIVING_STATUS[line.status],
        received_quantity=float(line.picked_quantity),
        product_name=line.product_name,
        lot_name=line.lot_name,
        expected_quantity=float(line.expected_quantity),
        uom_symbol=line.uom_symbol,
        **plans.get(line.document_line_id, {}),
    )


async def _session_to_out(
    db: AsyncSession, org_id: UUID, session: WmsPickSession
) -> WmsReceiveSessionOut:
    lines = session.lines or []
    plans = await _receipt_plans(db, org_id, session.document_id)
    codes: dict[UUID, str | None] = {}
    for plan in plans.values():
        shelf_id = plan.get('planned_location_id')
        if shelf_id is not None and shelf_id not in codes:
            codes[shelf_id] = await core_api.locations.scannable_code_async(
                db, org_id, shelf_id
            )
        plan['planned_location_code'] = codes.get(shelf_id) if shelf_id else None
    return WmsReceiveSessionOut(
        id=session.id,
        document_id=session.document_id,
        assigned_to=session.assigned_to,
        status=session.status,
        started_at=session.started_at,
        completed_at=session.completed_at,
        lines=[_line_to_out(ln, plans) for ln in lines],
        total_lines=len(lines),
        received_lines=sum(1 for ln in lines if ln.status in ('picked', 'short')),
        pending_lines=sum(1 for ln in lines if ln.status == 'pending'),
        shelf_scan_required=shelf_scan_required(session),
        confirmed_shelf_id=confirmed_shelf_id(session),
    )


def _is_session_complete(session: WmsPickSession | None) -> bool:
    if not session:
        return False
    all_lines = session.lines or []
    if not all_lines:
        return False
    return all(ln.status in ('picked', 'short', 'skipped') for ln in all_lines)


@router.post(
    '/documents/{document_id}/receiving/start',
    response_model=WmsReceiveSessionOut,
    status_code=201,
)
async def start_receiving(
    document_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)

    try:
        session = await start_receive_session_async(
            db, document_id, org_id, current_user.id
        )
        return await _session_to_out(db, org_id, session)
    except SessionHeldByOtherUserError as exc:
        # Same envelope as every other operation on a held session: the id
        # the take-over and release doors take and the holder's name the
        # dialog shows.
        raise _session_held_conflict(exc) from exc


@router.post(
    '/documents/{document_id}/receiving/{session_id}/scan',
    response_model=WmsReceiveScanResponse,
)
async def scan_receiving(
    document_id: UUID,
    session_id: UUID,
    data: WmsReceiveScanRequest,
    confirm_surplus: bool = Query(False),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)

    await _get_owned_session_for_document_async(
        db,
        session_id=session_id,
        document_id=document_id,
        org_id=org_id,
        user_id=current_user.id,
        resource='receiving_session',
    )

    may_exceed = current_user.has_permission('warehouse:receive_over_tolerance')
    with asking_the_holder(may_exceed):
        result = await scan_receive_async(
            db,
            session_id,
            org_id,
            barcode=data.barcode,
            quantity=data.quantity,
            batch_number=data.batch_number,
            expiry_date=data.expiry_date,
            may_exceed_over_receipt=may_exceed and confirm_surplus,
            identify=data.identify,
        )
    return WmsReceiveScanResponse(**result)


@router.post(
    '/documents/{document_id}/receiving/{session_id}/short-receive',
    response_model=WmsReceiveScanResponse,
)
async def short_receive(
    document_id: UUID,
    session_id: UUID,
    data: WmsReceiveShortRequest,
    confirm_surplus: bool = Query(False),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)

    await _get_owned_session_for_document_async(
        db,
        session_id=session_id,
        document_id=document_id,
        org_id=org_id,
        user_id=current_user.id,
        resource='receiving_session',
    )

    may_exceed = current_user.has_permission('warehouse:receive_over_tolerance')
    with asking_the_holder(may_exceed):
        updated = await short_receive_async(
            db,
            session_id,
            org_id,
            data.line_id,
            data.received_quantity,
            batch_number=data.batch_number,
            expiry_date=data.expiry_date,
            discrepancy_code=data.discrepancy_code,
            discrepancy_reason=data.discrepancy_reason,
            may_exceed_over_receipt=may_exceed and confirm_surplus,
            replace_scans=data.replace_scans,
            held_quantity=data.held_quantity or Decimal('0'),
        )
    if isinstance(updated, dict):
        return WmsReceiveScanResponse(**updated)
    session_obj = await get_receive_session_async(db, session_id, org_id)
    return WmsReceiveScanResponse(
        status='short_receive_confirmed',
        line_id=updated.id,
        product_name=updated.product_name,
        received_quantity=float(updated.picked_quantity),
        expected_quantity=float(updated.expected_quantity),
        uom_symbol=updated.uom_symbol,
        session_complete=_is_session_complete(session_obj),
        message=f'Short receive: {updated.picked_quantity}/{updated.expected_quantity}',
    )


@router.post(
    '/documents/{document_id}/receiving/{session_id}/complete',
    response_model=WmsReceiveSessionOut,
)
async def complete_receiving(
    document_id: UUID,
    session_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)

    await _get_owned_session_for_document_async(
        db,
        session_id=session_id,
        document_id=document_id,
        org_id=org_id,
        user_id=current_user.id,
        resource='receiving_session',
    )

    session = await complete_receive_session_async(db, session_id, org_id)
    return await _session_to_out(db, org_id, session)


@router.post(
    '/documents/{document_id}/receiving/{session_id}/undo',
    response_model=WmsReceiveUndoResponse,
)
async def undo_receiving(
    document_id: UUID,
    session_id: UUID,
    line_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)

    await _get_owned_session_for_document_async(
        db,
        session_id=session_id,
        document_id=document_id,
        org_id=org_id,
        user_id=current_user.id,
        resource='receiving_session',
    )

    restored = await undo_receive_async(
        db, session_id, org_id, line_id, current_user.id
    )
    return WmsReceiveUndoResponse(
        line_id=restored.id,
        product_name=restored.product_name,
        restored_quantity=float(restored.picked_quantity)
        if restored.status == 'pending'
        else 0,
    )


@router.post(
    '/documents/{document_id}/receiving/{session_id}/skip',
    response_model=WmsReceiveScanResponse,
)
async def skip_receiving(
    document_id: UUID,
    session_id: UUID,
    line_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)

    await _get_owned_session_for_document_async(
        db,
        session_id=session_id,
        document_id=document_id,
        org_id=org_id,
        user_id=current_user.id,
        resource='receiving_session',
    )

    skipped = await skip_receive_line_async(db, session_id, org_id, line_id)
    session_obj = await get_receive_session_async(db, session_id, org_id)
    return WmsReceiveScanResponse(
        status='skipped',
        line_id=skipped.id,
        product_name=skipped.product_name,
        expected_quantity=float(skipped.expected_quantity),
        uom_symbol=skipped.uom_symbol,
        session_complete=_is_session_complete(session_obj),
        message=f'{skipped.product_name or "Item"} skipped',
    )


@router.post(
    '/documents/{document_id}/receiving/{session_id}/cancel',
    status_code=204,
)
async def cancel_receiving(
    document_id: UUID,
    session_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> None:
    org_id = require_org(current_user)
    # The holder's own act: a screen that no longer holds this session — a
    # stale tab after a handover — must not discard the scans somebody else
    # is working. Letting go of another person's session is the release door.
    await _get_owned_session_for_document_async(
        db,
        session_id=session_id,
        document_id=document_id,
        org_id=org_id,
        user_id=current_user.id,
        resource='receiving_session',
    )
    await cancel_receive_session_async(db, session_id, org_id, current_user.id)


@router.post(
    '/documents/{document_id}/receiving/{session_id}/pause',
    status_code=204,
)
async def pause_receiving(
    document_id: UUID,
    session_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> None:
    org_id = require_org(current_user)
    # The holder closing the sheet: the scans stay and the document is free
    # to be completed or continued by anyone. A stale tab after a handover
    # must not pause the session somebody else is working in.
    session = await _get_owned_session_for_document_async(
        db,
        session_id=session_id,
        document_id=document_id,
        org_id=org_id,
        user_id=current_user.id,
        resource='receiving_session',
    )
    await pause_session_async(db, session, current_user.id)


@router.post(
    '/documents/{document_id}/receiving/{session_id}/release',
    status_code=204,
)
async def release_receiving(
    document_id: UUID,
    session_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> None:
    org_id = require_org(current_user)
    # The release path: anyone may put a session back — the button says it
    # discards the holder's scans — but only through the document the
    # session is actually under.
    await _get_session_for_document_async(
        db,
        session_id=session_id,
        document_id=document_id,
        org_id=org_id,
        resource='receiving_session',
    )
    await cancel_receive_session_async(db, session_id, org_id, current_user.id)


@router.post(
    '/documents/{document_id}/receiving/{session_id}/take-over',
    response_model=WmsReceiveSessionOut,
)
async def take_over_receiving(
    document_id: UUID,
    session_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    # The handover path: the session moves to the caller with its scans, so
    # unlike the operations it asks for the document and not for the holder.
    session = await _get_session_for_document_async(
        db,
        session_id=session_id,
        document_id=document_id,
        org_id=org_id,
        resource='receiving_session',
    )
    await take_over_session_async(db, session, current_user.id)
    return await _session_to_out(db, org_id, session)


@router.get(
    '/documents/{document_id}/receiving',
    response_model=PaginatedResponse[WmsReceiveSessionOut],
)
async def list_receiving_sessions(
    document_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    sessions = await list_receive_sessions_for_document_async(db, document_id, org_id)
    page = [
        await _session_to_out(db, org_id, sess)
        for sess in sessions[offset : offset + limit]
    ]
    return PaginatedResponse.from_slice(page, offset, limit, len(sessions))


@router.get(
    '/documents/{document_id}/receiving/{session_id}',
    response_model=WmsReceiveSessionOut,
)
async def get_receiving_session(
    document_id: UUID,
    session_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    session = await _get_session_for_document_async(
        db,
        session_id=session_id,
        document_id=document_id,
        org_id=org_id,
        resource='receiving_session',
    )
    return await _session_to_out(db, org_id, session)
