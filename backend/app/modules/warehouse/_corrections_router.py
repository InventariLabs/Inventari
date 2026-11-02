"""Document corrections / returns endpoints — extracted from main router."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import map_service_errors
from app.core.module_sdk import PaginatedResponse
from app.core.modules import require_module

from .document_correction_service import (
    create_correction,
    get_corrections_for_document,
    undo_document,
)
from .document_return_service import create_return
from .schemas import (
    CorrectionCreate,
    DocumentSchema,
    DocumentSummary,
    ReturnCreate,
)

router = APIRouter(dependencies=[Depends(require_module('warehouse'))])


@router.post(
    '/corrections', response_model=DocumentSchema, status_code=status.HTTP_201_CREATED
)
async def create_correction_document(
    data: CorrectionCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    correction = await create_correction(
        db,
        corrects_document_id=data.corrects_document_id,
        correction_lines=[
            {
                'original_line_number': line.original_line_number,
                'quantity_delta': line.quantity_delta,
                'notes': line.notes,
            }
            for line in data.lines
        ],
        org_id=org_id,
        user_id=current_user.id,
        notes=data.notes,
        reason_code=data.reason_code,
        may_exceed_over_receipt=current_user.has_permission(
            'warehouse:receive_over_tolerance'
        ),
    )
    return correction


@router.get(
    '/documents/{doc_id}/corrections', response_model=PaginatedResponse[DocumentSummary]
)
async def list_document_corrections(
    doc_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    corrections = await get_corrections_for_document(db, doc_id, org_id)
    return PaginatedResponse.from_full_list(corrections, offset=offset, limit=limit)


@router.post('/documents/{doc_id}/undo', response_model=DocumentSchema)
@map_service_errors
async def undo_document_endpoint(
    doc_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Reverse a just-posted receipt, issue or move in one transaction.

    Answers with the reversing correction: it is a document of the register
    in its own right, and its number is what the original's history names.
    Where an approval stands in front of the correction, the reversal waits at
    PENDING_APPROVAL and posts when the approval is granted.
    """
    return await undo_document(
        db,
        org_id,
        doc_id,
        current_user.id,
        may_exceed_over_receipt=current_user.has_permission(
            'warehouse:receive_over_tolerance'
        ),
    )


@router.post(
    '/documents/{document_id}/return',
    response_model=DocumentSchema,
    status_code=status.HTTP_201_CREATED,
)
async def create_return_document(
    document_id: UUID,
    data: ReturnCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    return await create_return(
        db,
        original_id=document_id,
        lines=[
            {
                'original_line_number': line.original_line_number,
                'return_quantity': line.return_quantity,
                'reason': line.reason,
            }
            for line in data.lines
        ],
        org_id=org_id,
        user_id=current_user.id,
        notes=data.notes,
        reason_code=data.reason_code,
    )
