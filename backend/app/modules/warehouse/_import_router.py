"""Document import endpoints (file upload + line mapping) — extracted from main router."""

import json
from datetime import date
from json import JSONDecodeError
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import SystemPermission
from app.core.contracts.dtos import UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import (
    ForbiddenException,
    ServiceRejectionError,
    catalogue_refusal,
    map_service_errors,
)
from app.core.modules import require_module
from app.core.upload_validation import read_import_file
from app.i18n.service import get_current_lang, get_error_message

from .schemas import (
    DocumentImportAnalyzeResponse,
    DocumentImportLinesResponse,
    OpeningStockImportResponse,
)

router = APIRouter(dependencies=[Depends(require_module('warehouse'))])


def _refuse_stubs_without_items_write(
    create_stubs_for_unmatched: bool,
    current_user: UserContextDTO,
) -> None:
    """Founding product templates stays items:write work, flag or no flag.

    The import itself is documents work and stays open to a documents-only
    account — but the checkbox is the one word in the request that founds
    templates, so it is the one word the permission gates. Refused, not
    silently downgraded: the caller asked for creation, and importing
    without it would be a half-true answer.
    """
    if create_stubs_for_unmatched and not current_user.has_permission(
        SystemPermission.ITEMS_WRITE
    ):
        raise ForbiddenException(
            message=get_error_message(
                'import_stubs_forbidden',
                get_current_lang(),
                permissions=SystemPermission.ITEMS_WRITE.value,
            )
        )


class ParsePasteRequest(BaseModel):
    """Request body for POST /import/parse-paste."""

    text: str = Field(
        default='',
        description='Raw text pasted from clipboard (Excel/Sheets). '
        'Delimiter (tab, comma, semicolon) is auto-detected.',
    )


@router.post('/import/analyze', response_model=DocumentImportAnalyzeResponse)
async def analyze_document_import(
    file: UploadFile = File(...),
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> Any:
    # The core upload validation (50 MB cap, extension allowlist,
    # magic bytes) must run BEFORE pandas touches attacker-supplied bytes —
    # an xlsx is a ZIP and decompresses far beyond its transfer size.
    content = await read_import_file(file, get_current_lang())
    from app.core.file_import import analyze_import_file

    return await analyze_import_file(content, file.filename or '')


@router.post('/import/parse-paste', response_model=DocumentImportAnalyzeResponse)
async def parse_pasted_lines(
    payload: ParsePasteRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> Any:
    """Parse pasted clipboard text and return a preview.

    Shares the response schema with :path:`/import/analyze` so the frontend
    can reuse the same preview UI for both file uploads and pasted text.
    """
    from .document_import_service import analyze_pasted_text

    return await analyze_pasted_text(payload.text)


@router.post('/import/opening-stock', response_model=OpeningStockImportResponse)
@map_service_errors
async def import_opening_stock_from_file(
    file: UploadFile = File(...),
    mapping_json: str = Form(...),
    target_location_id: UUID = Form(...),
    # Founding a template per unmatched row is items work; the caller now
    # both holds the permission for it and owns the decision itself.
    create_stubs_for_unmatched: bool = Form(default=True),
    scheduled_date: date | None = Form(default=None),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """One draft receipt, flagged as opening stock, out of a whole sheet.

    Every row finds its product by barcode, SKU or name or founds one, so the
    draft can be posted as it stands; refused rows come back with reasons.
    """
    lang = get_current_lang()
    try:
        mapping = json.loads(mapping_json)
    except (JSONDecodeError, ValueError) as e:
        raise catalogue_refusal('invalid_mapping_json') from e

    content = await read_import_file(file, lang)
    from .opening_stock_service import import_opening_stock

    return await import_opening_stock(
        db,
        org_id,
        current_user.id,
        file_content=content,
        filename=file.filename or '',
        mapping=mapping,
        target_location_id=target_location_id,
        create_stubs_for_unmatched=create_stubs_for_unmatched,
        scheduled_date=scheduled_date,
    )


@router.post('/import/lines', response_model=DocumentImportLinesResponse)
@map_service_errors
async def read_lines_from_file(
    file: UploadFile = File(...),
    mapping_json: str = Form(...),
    type: str = Form(..., max_length=20),
    source_location_id: UUID | None = Form(default=None),
    create_stubs_for_unmatched: bool = Form(default=False),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Read a sheet into lines for a document not saved yet; writes no line."""
    _refuse_stubs_without_items_write(create_stubs_for_unmatched, current_user)
    try:
        mapping = json.loads(mapping_json)
    except (JSONDecodeError, ValueError) as e:
        raise ServiceRejectionError('invalid_mapping_json') from e

    content = await read_import_file(file, get_current_lang())
    from app.core.import_sheet import read_rows

    from .document_import_service import read_lines_for_new_document

    return await read_lines_for_new_document(
        db,
        org_id,
        read_rows(content, file.filename or ''),
        mapping,
        doc_type=type,
        source_location_id=source_location_id,
        create_stubs_for_unmatched=create_stubs_for_unmatched,
        user_id=current_user.id,
    )


class ReadPastedLinesRequest(BaseModel):
    """Request body for POST /import/lines/paste."""

    text: str = Field(default='', description='Raw pasted clipboard text.')
    mapping_json: dict[str, Any] = Field(default_factory=dict)
    type: str = Field(max_length=20, description='The document type being written.')
    source_location_id: UUID | None = None
    create_stubs_for_unmatched: bool = False


@router.post('/import/lines/paste', response_model=DocumentImportLinesResponse)
@map_service_errors
async def read_pasted_lines(
    payload: ReadPastedLinesRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Read pasted rows into lines for a document not saved yet; writes no line."""
    _refuse_stubs_without_items_write(payload.create_stubs_for_unmatched, current_user)
    from .document_import_service import parse_pasted_text, read_lines_for_new_document

    df = parse_pasted_text(payload.text)
    if df.empty:
        raise ServiceRejectionError('paste_empty')
    return await read_lines_for_new_document(
        db,
        org_id,
        df,
        payload.mapping_json,
        doc_type=payload.type,
        source_location_id=payload.source_location_id,
        create_stubs_for_unmatched=payload.create_stubs_for_unmatched,
        user_id=current_user.id,
    )


@router.post(
    '/documents/{doc_id}/import-lines', response_model=DocumentImportLinesResponse
)
async def import_document_lines(
    doc_id: UUID,
    file: UploadFile = File(...),
    mapping_json: str = Form(...),
    create_stubs_for_unmatched: bool = Form(default=False),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    _refuse_stubs_without_items_write(create_stubs_for_unmatched, current_user)
    lang = get_current_lang()
    try:
        mapping = json.loads(mapping_json)
    except (JSONDecodeError, ValueError) as e:
        raise catalogue_refusal('invalid_mapping_json') from e

    content = await read_import_file(file, lang)
    from .document_import_service import import_lines_from_file

    return await import_lines_from_file(
        db=db,
        doc_id=doc_id,
        file_content=content,
        filename=file.filename or '',
        column_mapping=mapping,
        org_id=org_id,
        create_stubs_for_unmatched=create_stubs_for_unmatched,
        user_id=current_user.id,
    )


class ImportPasteRequest(BaseModel):
    """Request body for POST /{doc_id}/import-paste."""

    text: str = Field(default='', description='Raw pasted clipboard text.')
    mapping_json: dict[str, Any] = Field(
        default_factory=dict,
        description='Column mapping (same shape as import-lines mapping_json).',
    )
    create_stubs_for_unmatched: bool = Field(
        default=False,
        description='When True, unmatched barcodes auto-create '
        'a stub ProductTemplate so the line imports as matched.',
    )


@router.post(
    '/documents/{doc_id}/import-paste', response_model=DocumentImportLinesResponse
)
async def import_pasted_lines(
    doc_id: UUID,
    payload: ImportPasteRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Import lines from pasted clipboard text into a DRAFT document.

    Mirrors :path:`/{doc_id}/import-lines` but accepts raw text instead of
    a file upload. Reuses the same column-mapping and line-building pipeline.
    """
    _refuse_stubs_without_items_write(payload.create_stubs_for_unmatched, current_user)
    from .document_import_service import import_lines_from_text

    return await import_lines_from_text(
        db=db,
        doc_id=doc_id,
        text=payload.text,
        column_mapping=payload.mapping_json,
        org_id=org_id,
        create_stubs_for_unmatched=payload.create_stubs_for_unmatched,
        user_id=current_user.id,
    )
