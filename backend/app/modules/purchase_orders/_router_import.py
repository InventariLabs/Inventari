from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import (
    NotFoundException,
    catalogue_refusal,
)
from app.i18n.service import get_current_lang

from ._journal import journal_order_act
from ._service_crud import get_purchase_order as get_po


def register_import_routes(router: APIRouter) -> None:
    @router.post(
        '/import/analyze',
    )
    async def analyze_import(
        file: UploadFile,
        current_user: UserContextDTO = Depends(get_current_user_context),
    ) -> dict[str, Any]:
        from app.core.upload_validation import read_import_file

        from .po_import_service import analyze_po_import_file

        content = await read_import_file(file)
        result = await analyze_po_import_file(content, file.filename or '')
        return result

    @router.post(
        '/{po_id}/import-lines',
    )
    async def import_lines(
        po_id: UUID,
        file: UploadFile,
        column_mapping: dict[str, Any] | None = None,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> dict[str, Any]:
        from app.core.upload_validation import read_import_file

        from .po_import_service import import_lines_into_po

        po = await get_po(db, org_id, po_id)
        if not po:
            raise NotFoundException('purchase_order', get_current_lang())
        if po.status != 'DRAFT':
            raise catalogue_refusal('po_import_not_draft')

        content = await read_import_file(file)
        mapping = column_mapping or {}
        lines_before = len(po.lines)
        result = await import_lines_into_po(
            db, po_id, content, file.filename or '', mapping, org_id
        )
        # An import that landed no line moved nothing: no entry, as an edit
        # that changed nothing writes none.
        if result['imported']:
            await journal_order_act(
                db,
                org_id,
                current_user.id,
                po,
                before={'line_count': lines_before},
                after={'line_count': len(po.lines)},
                act={
                    'imported_from': file.filename or None,
                    'skipped': result['skipped'],
                },
            )
        return result
