"""Equipment bulk-import HTTP surface (analyze + execute).

The wizard at ``frontend/src/modules/equipment/components/ImportEquipmentModal.tsx``
already calls ``POST /equipment/import/analyze`` and
``POST /equipment/import/execute``; this router is the only missing piece
between the FE and the existing ``import_service`` functions.

Both endpoints require ``ITEMS_WRITE`` and the equipment module to be
enabled for the caller's organisation. ``analyze`` is read-only (no
``_require_org``), since it does not touch the DB; ``execute`` opens a
session-backed transaction via the org-scoped ``core_api.items.create_async``.
"""

from __future__ import annotations

import json
from json import JSONDecodeError
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import catalogue_refusal
from app.core.upload_validation import read_import_file
from app.i18n import Language
from app.i18n.service import get_current_lang

from .import_service import (
    analyze_equipment_import,
    execute_equipment_import,
)
from .schemas import ImportAnalyzeResult, ImportExecuteResult

router = APIRouter()


@router.post(
    '/import/analyze',
    response_model=ImportAnalyzeResult,
    summary='Parse uploaded CSV/XLSX and return headers + preview rows + total row count (dry-run, no DB writes).',
)
async def analyze_equipment_import_endpoint(
    file: UploadFile = File(...),
    current_user: UserContextDTO = Depends(get_current_user_context),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
) -> ImportAnalyzeResult:
    """Read-only parse step of the equipment import wizard."""
    lang: Language = get_current_lang()
    content = await read_import_file(file, lang)
    raw = await analyze_equipment_import(content, file.filename or '')
    return ImportAnalyzeResult.model_validate(raw)


@router.post(
    '/import/execute',
    response_model=ImportExecuteResult,
    summary='Commit the equipment bulk import batch.',
)
async def execute_equipment_import_endpoint(
    file: UploadFile = File(...),
    mapping_json: str = Form(...),
    default_location_id: str | None = Form(None),
    default_category_id: str | None = Form(None),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> ImportExecuteResult:
    """Commit step of the equipment import wizard."""
    lang: Language = get_current_lang()

    try:
        mapping = json.loads(mapping_json)
    except JSONDecodeError as exc:
        raise catalogue_refusal('invalid_mapping_json') from exc

    content = await read_import_file(file, lang)
    raw = await execute_equipment_import(
        db=db,
        content=content,
        filename=file.filename or '',
        mapping=mapping,
        org_id=org_id,
        user=current_user,
        default_location_id=default_location_id,
        default_category_id=default_category_id,
    )
    return ImportExecuteResult.model_validate(raw)
