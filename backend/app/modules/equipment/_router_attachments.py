from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Query,
    UploadFile,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import map_service_errors
from app.core.module_sdk import PaginatedResponse

from . import attachment_service
from .schemas import AttachmentSchema

router = APIRouter()


@router.get(
    '/{item_id}/attachments', response_model=PaginatedResponse[AttachmentSchema]
)
@map_service_errors
async def list_attachments(
    item_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    attachments = await attachment_service.list_attachments(db, org_id, item_id)
    return PaginatedResponse.from_full_list(attachments, offset=offset, limit=limit)


@router.post('/{item_id}/attachments', response_model=AttachmentSchema, status_code=201)
@map_service_errors
async def upload_attachment(
    item_id: UUID,
    file: UploadFile = File(...),
    file_type: str = Form('OTHER'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> Any:
    content = await file.read()
    return await attachment_service.upload_attachment(
        db,
        org_id,
        item_id,
        current_user.id,
        file_content=content,
        original_name=file.filename or 'upload',
        content_type=file.content_type or 'application/octet-stream',
        file_type=file_type,
    )


@router.delete('/{item_id}/attachments/{attachment_id}', status_code=204)
@map_service_errors
async def delete_attachment(
    item_id: UUID,
    attachment_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> None:
    file_path = await attachment_service.delete_attachment(
        db, org_id, item_id, attachment_id, current_user.id
    )
    # After the response, which is after the session committed the row away:
    # a request that fails first never deletes the file its row still names.
    background_tasks.add_task(attachment_service.discard_stored_file, org_id, file_path)
