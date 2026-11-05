"""The approval doors of a warehouse document, served by the module that decides.

They lived under ``/documents`` and were the warehouse's own: it raised the
request, called the decision and moved the document itself. They are the
approvals module's now, at ``/approvals/documents/{doc_id}/...``, and reach the
document only through ``warehouse_api`` — a request raised here holds it, and
the decision listener (``document_gate``) moves it when the request is
decided, from here or from the approvals queue alike.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import DocumentStateDTO, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
    require_read_write,
)
from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    refusal_code,
    rejection_code,
)
from app.core.modules import require_module
from app.i18n.service import get_current_lang, get_error_message

from .approvals_api import approvals_api
from .document_gate import (
    MODULE,
    document_needs_approval_async,
    warehouse_documents,
)
from .exceptions import ApprovalError
from .schemas import (
    ApprovalRequestSchema,
    ApproveRequest,
    AskForApproval,
    DocumentApprovalRequirement,
    RejectRequest,
)

#: The doors moved here from the warehouse router and keep its guard: reading a
#: document's approval needs ``warehouse:read``, raising or deciding one holds
#: or releases the document and needs ``warehouse:write`` — a decision needs
#: ``approvals:approve`` on top.
router = APIRouter(
    prefix='/documents',
    dependencies=[
        Depends(require_module('warehouse')),
        require_read_write('warehouse:read', 'warehouse:write'),
    ],
)


async def _document(db: AsyncSession, org_id: UUID, doc_id: UUID) -> DocumentStateDTO:
    state = await warehouse_documents().get_document_state_async(db, org_id, doc_id)
    if state is None:
        raise NotFoundException('document')
    return state


def _no_pending_request() -> ConflictException:
    key = 'document_no_pending_approval_request'
    return ConflictException(
        code=rejection_code(key),
        message=get_error_message(key, get_current_lang()),
    )


@router.post('/{doc_id}/request-approval', response_model=ApprovalRequestSchema)
async def request_document_approval(
    doc_id: UUID,
    body: AskForApproval = AskForApproval(),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """Ask for a sign-off on a document no rule demanded it for.

    The document waits for the answer like one the rule held: a request that
    left it CONFIRMED kept it out of the "Pending Approval" filter while the
    queue asked about it. A workflow whose every stage is the requester's own
    is decided the moment it is raised, and the document is not held for an
    answer it already has.
    """
    org_id = require_org(current_user)
    doc = await _document(db, org_id, doc_id)
    if doc.status not in ('CONFIRMED', 'PENDING_APPROVAL'):
        raise ConflictException(
            code='INVALID_STATUS',
            message=get_error_message(
                'document_request_approval_invalid_status', get_current_lang()
            ),
        )
    try:
        request = await approvals_api.request_approval(
            db,
            org_id,
            'document',
            doc_id,
            current_user.id,
            meta_data={'notes': body.notes} if body.notes else None,
        )
    except ApprovalError as exc:
        raise ConflictException(
            code=refusal_code(exc, 'APPROVAL_ERROR'), message=str(exc)
        ) from exc
    if request.status in ('PENDING', 'IN_PROGRESS'):
        await warehouse_documents().hold_document_async(db, org_id, doc_id, MODULE)
    return request


@router.post(
    '/{doc_id}/approve',
    response_model=ApprovalRequestSchema,
    dependencies=[require_permission('approvals:approve')],
)
async def approve_document(
    doc_id: UUID,
    body: ApproveRequest = ApproveRequest(),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """Decide the open stage of the document's request; the last one releases it."""
    org_id = require_org(current_user)
    await _document(db, org_id, doc_id)
    active = await approvals_api.find_active_request(db, org_id, 'document', doc_id)
    if active is None:
        raise _no_pending_request()
    try:
        return await approvals_api.approve_stage(
            db, org_id, active.id, current_user.id, notes=body.notes
        )
    except ApprovalError as exc:
        raise ConflictException(
            code=refusal_code(exc, 'APPROVAL_ERROR'), message=str(exc)
        ) from exc


@router.post(
    '/{doc_id}/reject',
    response_model=ApprovalRequestSchema,
    dependencies=[require_permission('approvals:approve')],
)
async def reject_document(
    doc_id: UUID,
    body: RejectRequest = RejectRequest(),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """Reject the document's request; the document goes back to a draft.

    So the requester can correct it and submit it again, and is told why. The
    reason travels in the body: a query string is what proxies and access logs
    keep, and this one is free text about a colleague's document.
    """
    org_id = require_org(current_user)
    await _document(db, org_id, doc_id)
    active = await approvals_api.find_active_request(db, org_id, 'document', doc_id)
    if active is None:
        raise _no_pending_request()
    try:
        return await approvals_api.reject_request(
            db, org_id, active.id, current_user.id, notes=body.notes
        )
    except ApprovalError as exc:
        raise ConflictException(
            code=refusal_code(exc, 'APPROVAL_ERROR'), message=str(exc)
        ) from exc


@router.get('/{doc_id}/approval', response_model=ApprovalRequestSchema | None)
async def get_document_approval(
    doc_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """The newest request about the document, enriched as the queue shows it.

    Enriched, because the list read drops the workflow's stages and a
    multi-stage workflow then rendered as "Single approval".
    """
    org_id = require_org(current_user)
    await _document(db, org_id, doc_id)
    matching = await approvals_api.list_requests(
        db, org_id, target_type='document', target_id=doc_id
    )
    if not matching:
        return None
    return await approvals_api.get_request_enriched(
        db, org_id, matching[0].id, viewer_id=current_user.id
    )


@router.get(
    '/{doc_id}/approval-requirement',
    response_model=DocumentApprovalRequirement,
)
async def get_document_approval_requirement(
    doc_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> DocumentApprovalRequirement:
    """Whether confirming this document would send it to the approval queue.

    The dialog behind the confirm button has to name the consequence before
    the button is pressed. A draft is weighed here as the document it is about
    to become: the sentence the reader is shown and the thing the confirmation
    then does are one rule, asked twice.

    The answer also says whether the stage the document would wait at has
    anybody who could decide it for the person asking: the dialog used to
    promise the queue for a request that no queue would ever show.
    """
    org_id = require_org(current_user)
    doc = await _document(db, org_id, doc_id)
    draft = doc.status == 'DRAFT'
    required = await document_needs_approval_async(
        db,
        org_id,
        doc_id,
        # A draft is about to be submitted by whoever is asking — two people
        # looking at one draft can get two answers, because the workflow
        # holds one of them. A submitted document was submitted by somebody.
        requester_id=current_user.id if draft else doc.confirmed_by,
        as_status='CONFIRMED' if draft else None,
    )
    workflow = await approvals_api.get_active_workflow(db, org_id, 'document')
    verdict = (
        await approvals_api.first_stage_verdict(db, org_id, 'document', current_user.id)
        if required and workflow is not None
        else None
    )
    return DocumentApprovalRequirement(
        approval_required=required,
        workflow_configured=workflow is not None,
        approval_solvable=verdict is None or verdict.solvable,
        undecidable_reason=None if verdict is None else verdict.undecidable_reason,
        undecidable_stage=(
            None if verdict is None or verdict.solvable else verdict.stage_label
        ),
    )
