from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import StorageDTO
from app.core.contracts.dtos import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.module_sdk import PaginatedResponse
from app.core.modules import require_module
from app.core.public_api import core_api
from app.core.utils import build_pdf_response, sanitize_filename

from ._pick_coverage import uncovered_documents_async
from ._wms_line_utils import session_document_ids_async, shelf_caption
from ._wms_session_access import (
    _get_owned_session_for_document_async,
    _get_session_for_document_async,
    _session_held_conflict,
    take_over_session_async,
)
from ._wms_session_close import destination_awaited, destination_to_scan
from ._wms_session_ops import SessionHeldByOtherUserError
from ._wms_session_release import pause_session_async
from ._wms_shelf import confirmed_shelf_id, shelf_scan_required
from .models import Document, DocumentLine, WmsPickLine, WmsPickSession
from .pick_list_service import dispatch_pick_list_async, session_pick_list_async
from .wms_picking_schemas import (
    WmsPickCoverageOut,
    WmsPickDocumentProgressOut,
    WmsPickLineOut,
    WmsPickScanRequest,
    WmsPickScanResponse,
    WmsPickSessionOut,
    WmsPickStartRequest,
    WmsShortPickRequest,
    WmsUndoPickResponse,
)
from .wms_picking_service import (
    cancel_pick_session_async,
    complete_pick_session_async,
    confirm_short_pick_async,
    get_pick_session_async,
    list_pick_sessions_for_document_async,
    refuse_short_pick_unconfirmed_async,
    scan_pick_async,
    skip_pick_line_async,
    start_pick_session_async,
    start_pick_session_over_documents_async,
    undo_pick_async,
)

router = APIRouter(dependencies=[Depends(require_module('warehouse'))])


def _line_to_out(
    line: WmsPickLine,
    doc: Document | None,
    shelf: StorageDTO | None = None,
    shelf_code: str | None = None,
) -> WmsPickLineOut:
    return WmsPickLineOut(
        id=line.id,
        document_line_id=line.document_line_id,
        document_id=doc.id if doc else None,
        document_number=doc.number if doc else None,
        anchor_id=line.anchor_id,
        lot_id=line.lot_id,
        location_id=line.location_id,
        location_code=shelf_code if shelf else None,
        location_name=shelf.name if shelf else None,
        pick_order=line.pick_order,
        status=line.status,
        picked_quantity=float(line.picked_quantity),
        bin_location=line.bin_location,
        product_name=line.product_name,
        lot_name=line.lot_name,
        expiry_date=line.expiry_date,
        expected_quantity=float(line.expected_quantity),
        uom_symbol=line.uom_symbol,
    )


def _progress(lines: list[WmsPickLine]) -> dict[str, int]:
    return {
        'total_lines': len(lines),
        'picked_lines': sum(1 for ln in lines if ln.status in ('picked', 'short')),
        'pending_lines': sum(1 for ln in lines if ln.status == 'pending'),
    }


def _document_progress(
    doc: Document, lines: list[WmsPickLine]
) -> WmsPickDocumentProgressOut:
    """Where one document of the session stands — the session's rule, per document.

    Resolved the way a session over that document alone would close: short
    when a line came up short or was skipped (either leaves the dispatch
    without all of its goods), all picked otherwise.
    """
    if not lines or any(ln.status == 'pending' for ln in lines):
        status = 'picking'
    elif any(ln.status in ('short', 'skipped') for ln in lines):
        status = 'short'
    else:
        status = 'all_picked'
    return WmsPickDocumentProgressOut(
        document_id=doc.id,
        document_number=doc.number,
        document_status=doc.status,
        status=status,
        **_progress(lines),
    )


async def _shelves_async(
    db: AsyncSession, org_id: UUID, lines: list[WmsPickLine]
) -> list[StorageDTO]:
    """Every shelf the session's lines stand on, each fetched once."""
    seen: dict[UUID, StorageDTO] = {}
    for line in lines:
        if line.location_id is None or line.location_id in seen:
            continue
        shelf = await core_api.locations.get_async(db, org_id, line.location_id)
        if shelf is not None:
            seen[line.location_id] = shelf
    return list(seen.values())


async def _session_to_out(
    db: AsyncSession, session: WmsPickSession
) -> WmsPickSessionOut:
    lines = session.lines or []
    rows = await db.execute(
        select(DocumentLine.id, Document)
        .join(Document, Document.id == DocumentLine.document_id)
        .where(DocumentLine.id.in_([ln.document_line_id for ln in lines]))
    )
    doc_of_line = dict(rows.tuples().all())
    docs = {doc.id: doc for doc in doc_of_line.values()}
    by_doc: dict[UUID, list[WmsPickLine]] = {}
    for ln in lines:
        line_doc = doc_of_line.get(ln.document_line_id)
        if line_doc is not None:
            by_doc.setdefault(line_doc.id, []).append(ln)
    destination = (
        destination_to_scan(session) if session.status in ('active', 'paused') else None
    )
    shelf = (
        await core_api.locations.get_async(db, session.organization_id, destination)
        if destination
        else None
    )
    # Each line's shelf, fetched once per distinct shelf: the card reads the
    # label's code and the name under it, and the location may have been
    # renamed since the session started.
    shelves = {
        loc.id: loc for loc in await _shelves_async(db, session.organization_id, lines)
    }
    # The code a worker scans for each: the shelf's own, or its pool label's.
    # The card shows it and the shelf confirmation follows it, so a place with
    # only a label is still asked for.
    shelf_codes = {
        shelf_id: await core_api.locations.scannable_code_async(
            db, session.organization_id, shelf_id
        )
        for shelf_id in shelves
    }
    return WmsPickSessionOut(
        id=session.id,
        document_id=session.document_id,
        assigned_to=session.assigned_to,
        status=session.status,
        started_at=session.started_at,
        completed_at=session.completed_at,
        lines=[
            _line_to_out(
                ln,
                doc_of_line.get(ln.document_line_id),
                shelves.get(ln.location_id) if ln.location_id else None,
                shelf_codes.get(ln.location_id) if ln.location_id else None,
            )
            for ln in lines
        ],
        documents=[
            _document_progress(docs[doc_id], by_doc.get(doc_id, []))
            for doc_id in await session_document_ids_async(db, session)
            if doc_id in docs
        ],
        **_progress(lines),
        shelf_scan_required=shelf_scan_required(session),
        confirmed_shelf_id=confirmed_shelf_id(session),
        destination_shelf_id=destination,
        destination_shelf=shelf_caption(shelf) if shelf else None,
        destination_shelf_code=shelf.short_code if shelf else None,
    )


def _is_session_complete(session: WmsPickSession | None) -> bool:
    if not session:
        return False
    all_lines = session.lines or []
    if not all_lines:
        return False
    return (
        all(ln.status in ('picked', 'short', 'skipped') for ln in all_lines)
        and destination_awaited(session, all_lines) is None
    )


@router.post(
    '/documents/{document_id}/picking/start',
    response_model=WmsPickSessionOut,
    status_code=201,
)
async def start_picking(
    document_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)

    try:
        session = await start_pick_session_async(
            db, document_id, org_id, current_user.id
        )
        return await _session_to_out(db, session)
    except SessionHeldByOtherUserError as exc:
        # Same envelope as every other operation on a held session: the id
        # the take-over and release doors take and the holder's name the
        # dialog shows.
        raise _session_held_conflict(exc) from exc


@router.post('/picking/coverage', response_model=WmsPickCoverageOut)
async def picking_coverage(
    data: WmsPickStartRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """The dispatches of a selection whose lines stock cannot cover.

    Asked before a session starts, so the person learns at the start — not at
    the shelf — which documents will come back short and by how much.
    """
    org_id = require_org(current_user)
    found = await uncovered_documents_async(db, org_id, data.document_ids)
    return WmsPickCoverageOut(
        documents=[
            {
                'document_id': doc.document_id,
                'document_number': doc.document_number,
                'lines': [
                    {
                        'product_name': ln.product_name,
                        'uom_symbol': ln.uom_symbol,
                        'ordered': float(ln.ordered),
                        'available': float(ln.available),
                    }
                    for ln in doc.lines
                ],
            }
            for doc in found
        ]
    )


@router.post('/picking/start', response_model=WmsPickSessionOut, status_code=201)
async def start_picking_documents(
    data: WmsPickStartRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """One picking session over several confirmed dispatches.

    The session is reached afterwards through any of its documents, under
    the same per-document routes a single-document session uses.
    """
    org_id = require_org(current_user)
    session = await start_pick_session_over_documents_async(
        db, data.document_ids, org_id, current_user.id
    )
    return await _session_to_out(db, session)


@router.post(
    '/documents/{document_id}/picking/{session_id}/scan',
    response_model=WmsPickScanResponse,
)
async def scan_picking(
    document_id: UUID,
    session_id: UUID,
    data: WmsPickScanRequest,
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
        resource='picking_session',
    )

    result = await scan_pick_async(
        db,
        session_id,
        org_id,
        barcode=data.barcode,
        quantity=data.quantity,
        lot_name=data.lot_name,
    )
    return WmsPickScanResponse(**result)


@router.post(
    '/documents/{document_id}/picking/{session_id}/short-pick',
    response_model=WmsPickScanResponse,
)
async def short_pick(
    document_id: UUID,
    session_id: UUID,
    data: WmsShortPickRequest,
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
        resource='picking_session',
    )

    refusal = await refuse_short_pick_unconfirmed_async(
        db, session_id, org_id, data.line_id, data.picked_quantity
    )
    if refusal is not None:
        return WmsPickScanResponse(**refusal)

    updated = await confirm_short_pick_async(
        db,
        session_id,
        org_id,
        data.line_id,
        data.picked_quantity,
        discrepancy_code=data.discrepancy_code,
        discrepancy_reason=data.discrepancy_reason,
        replace_scans=data.replace_scans,
    )
    session_obj = await get_pick_session_async(db, session_id, org_id)
    return WmsPickScanResponse(
        status='short_pick_confirmed',
        line_id=updated.id,
        product_name=updated.product_name,
        picked_quantity=float(updated.picked_quantity),
        expected_quantity=float(updated.expected_quantity),
        uom_symbol=updated.uom_symbol,
        bin_location=updated.bin_location,
        session_complete=_is_session_complete(session_obj),
        message=f'Short pick: {updated.picked_quantity}/{updated.expected_quantity}',
    )


@router.post(
    '/documents/{document_id}/picking/{session_id}/complete',
    response_model=WmsPickSessionOut,
)
async def complete_picking(
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
        resource='picking_session',
    )

    session = await complete_pick_session_async(db, session_id, org_id)
    return await _session_to_out(db, session)


@router.post(
    '/documents/{document_id}/picking/{session_id}/undo',
    response_model=WmsUndoPickResponse,
)
async def undo_picking(
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
        resource='picking_session',
    )

    restored = await undo_pick_async(db, session_id, org_id, line_id, current_user.id)
    return WmsUndoPickResponse(
        line_id=restored.id,
        product_name=restored.product_name,
        restored_quantity=float(restored.picked_quantity)
        if restored.status == 'pending'
        else 0,
    )


@router.post(
    '/documents/{document_id}/picking/{session_id}/skip',
    response_model=WmsPickScanResponse,
)
async def skip_picking(
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
        resource='picking_session',
    )

    skipped = await skip_pick_line_async(db, session_id, org_id, line_id)
    session_obj = await get_pick_session_async(db, session_id, org_id)
    return WmsPickScanResponse(
        status='skipped',
        line_id=skipped.id,
        product_name=skipped.product_name,
        expected_quantity=float(skipped.expected_quantity),
        uom_symbol=skipped.uom_symbol,
        session_complete=_is_session_complete(session_obj),
        message=f'{skipped.product_name or "Item"} skipped',
    )


@router.post(
    '/documents/{document_id}/picking/{session_id}/cancel',
    status_code=204,
)
async def cancel_picking(
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
        resource='picking_session',
    )
    await cancel_pick_session_async(db, session_id, org_id, current_user.id)


@router.post(
    '/documents/{document_id}/picking/{session_id}/pause',
    status_code=204,
)
async def pause_picking(
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
        resource='picking_session',
    )
    await pause_session_async(db, session, current_user.id)


@router.post(
    '/documents/{document_id}/picking/{session_id}/release',
    status_code=204,
)
async def release_picking(
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
        resource='picking_session',
    )
    await cancel_pick_session_async(db, session_id, org_id, current_user.id)


@router.post(
    '/documents/{document_id}/picking/{session_id}/take-over',
    response_model=WmsPickSessionOut,
)
async def take_over_picking(
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
        resource='picking_session',
    )
    await take_over_session_async(db, session, current_user.id)
    return await _session_to_out(db, session)


@router.get(
    '/documents/{document_id}/picking',
    response_model=PaginatedResponse[WmsPickSessionOut],
)
async def list_picking_sessions(
    document_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    sessions = await list_pick_sessions_for_document_async(db, document_id, org_id)
    page = [
        await _session_to_out(db, sess) for sess in sessions[offset : offset + limit]
    ]
    return PaginatedResponse.from_slice(page, offset, limit, len(sessions))


@router.get(
    '/documents/{document_id}/picking/{session_id}',
    response_model=WmsPickSessionOut,
)
async def get_picking_session(
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
        resource='picking_session',
    )
    return await _session_to_out(db, session)


@router.get('/documents/{document_id}/pick-list', response_class=Response)
async def download_dispatch_pick_list(
    document_id: UUID,
    lang: str = Query(default='en', pattern='^[a-z]{2}(-[A-Z]{2})?$'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Response:
    """The paper pick list of a dispatch waiting to be picked, in walk order."""
    org_id = require_org(current_user)
    name, pdf = await dispatch_pick_list_async(db, org_id, document_id, lang)
    return build_pdf_response(pdf, sanitize_filename(name, prefix='pick_list'))


@router.get(
    '/documents/{document_id}/picking/{session_id}/pick-list',
    response_class=Response,
)
async def download_session_pick_list(
    document_id: UUID,
    session_id: UUID,
    lang: str = Query(default='en', pattern='^[a-z]{2}(-[A-Z]{2})?$'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Response:
    """The paper pick list of a session — over all its dispatches, in the screen's order.

    Printing belongs to nobody in particular: the sheet is a read of the
    session, so it is not held to the session's owner.
    """
    org_id = require_org(current_user)
    session = await _get_session_for_document_async(
        db,
        session_id=session_id,
        document_id=document_id,
        org_id=org_id,
        resource='picking_session',
    )
    name, pdf = await session_pick_list_async(db, org_id, session, lang)
    return build_pdf_response(pdf, sanitize_filename(name, prefix='pick_list'))
