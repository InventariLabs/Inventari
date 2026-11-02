from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import AppException, NotFoundException
from app.core.upload_validation import (
    FileSignatureMismatchError,
    FileTooLargeError,
    FileTypeNotAllowedError,
)
from app.i18n.service import get_current_lang
from app.schemas._common import AttachmentDeleteResponse
from app.schemas.item_attachment import ItemAttachmentSchema
from app.schemas.pagination import PaginatedResponse
from app.services.attachment_service import AttachmentService

router = APIRouter()


@router.post(
    '/items/{item_id}/attachments',
    response_model=ItemAttachmentSchema,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    item_id: UUID,
    file: UploadFile = File(...),
    current_user: UserContextDTO = Depends(get_current_user_context),
    # On the route, not the router: the ``APIRouter()`` above carries no
    # ``dependencies=``, so nothing is inherited — the delete route below
    # repeats this parameter, and a write route added here tomorrow must
    # too. It cannot move up to the router either: the list route between
    # them is a read every viewer may make. Attaching or removing a file on
    # a product is a write to the product register (``items:write``), and
    # the service below only ever sees an already-authorized request.
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    db=Depends(get_async_db, scope='function'),
):
    """
    Upload a file as an attachment to an item.
    """
    lang = get_current_lang()
    org_id = require_org(current_user)

    item = await AttachmentService.get_item_with_storage_async(
        db, item_id, organization_id=org_id
    )
    if not item:
        raise NotFoundException('item', lang)

    try:
        return await AttachmentService.create_attachment(
            db, org_id, item_id, file, lang, user_id=current_user.id
        )
    except FileTooLargeError as e:
        raise AppException(
            status_code=413, code='FILE_TOO_LARGE', message=str(e)
        ) from e
    except FileSignatureMismatchError as e:
        # Subclass first: the bytes contradict the declared type (400), which
        # is not the same as a type we refuse outright (415 below).
        raise AppException(
            status_code=400, code='FILE_SIGNATURE_MISMATCH', message=str(e)
        ) from e
    except FileTypeNotAllowedError as e:
        raise AppException(
            status_code=415, code='FILE_TYPE_NOT_ALLOWED', message=str(e)
        ) from e


@router.get(
    '/items/{item_id}/attachments',
    response_model=PaginatedResponse[ItemAttachmentSchema],
)
async def list_item_attachments(
    item_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
):
    """
    List all attachments for an item.
    """
    lang = get_current_lang()
    org_id = require_org(current_user)
    item = await AttachmentService.get_item_with_storage_async(
        db, item_id, organization_id=org_id
    )
    if not item:
        raise NotFoundException('item', lang)

    # Queried, not read off the relationship: a lazy load on the async
    # session raises instead of loading.
    attachments = await AttachmentService.list_for_item_async(db, item_id)
    return PaginatedResponse.from_full_list(attachments, offset=offset, limit=limit)


@router.delete('/attachments/{attachment_id}', response_model=AttachmentDeleteResponse)
async def delete_attachment(
    attachment_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    db=Depends(get_async_db, scope='function'),
):
    """
    Delete an attachment.
    """
    lang = get_current_lang()
    org_id = require_org(current_user)
    attachment = await AttachmentService.get_attachment_with_item_async(
        db, attachment_id, organization_id=org_id
    )
    if not attachment:
        raise NotFoundException('attachment', lang)

    await AttachmentService.delete_attachment(db, attachment, org_id, current_user.id)
    return AttachmentDeleteResponse(message='Attachment deleted')
