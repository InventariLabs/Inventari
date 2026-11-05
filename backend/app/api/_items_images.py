from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_user_storage_ids
from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import AppException, catalogue_refusal
from app.core.file_reference import cover_leaf, cover_leaf_of, served_url
from app.core.file_signature import validate_signature
from app.core.public_api import core_api
from app.core.upload_validation import read_capped_upload
from app.i18n.service import get_current_lang, get_error_message
from app.schemas._common import ImageUploadResponse
from app.schemas.item import ItemUpdate
from app.services.items import update_item
from app.services.items._query_special import get_item_or_404_async

#: Hand-synced with the frontend gate (see the unit test that pins the
#: number) and with the other interface-image limits: ten megabytes,
#: because phones take bigger photos than five.
_MAX_IMAGE_BYTES = 10 * 1024 * 1024

router = APIRouter()


#: The extension comes from the validated MIME, never from the
#: client-supplied filename.
_MIME_TO_EXT = {
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/gif': 'gif',
    'image/webp': 'webp',
}


@router.post('/{item_id}/image', response_model=ImageUploadResponse)
async def upload_item_image(
    item_id: UUID,
    image: UploadFile = File(...),
    user_storage_ids: list[UUID] = Depends(get_user_storage_ids),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
):
    """Upload a cover image for an item."""
    org_id = require_org(current_user)
    item = await get_item_or_404_async(db, item_id, user_storage_ids)

    if not image.content_type or image.content_type not in _MIME_TO_EXT:
        raise catalogue_refusal('only_image_files_allowed')

    # Capped while reading, not measured afterwards: `await image.read()`
    # buffers the whole body first, so a body far over the limit is already
    # in memory by the time the limit refuses it.
    try:
        content = await read_capped_upload(image, get_current_lang(), _MAX_IMAGE_BYTES)
    except ValueError as exc:
        from app.core.upload_validation import format_size_limit

        raise AppException(
            status_code=413,
            code='FILE_TOO_LARGE',
            message=get_error_message(
                'image_too_large',
                get_current_lang(),
                limit=format_size_limit(_MAX_IMAGE_BYTES),
            ),
        ) from exc
    # Content_type is client-supplied; check the bytes too. Three
    # other upload paths already do — this was the inconsistency, not a
    # missing idea.
    validate_signature(content, image.content_type)

    # Derive the extension from the validated MIME type rather than
    # from the client-supplied filename — the name is attacker data and only
    # LocalStorageProvider's is_relative_to check stood between it and the
    # filesystem.
    ext = _MIME_TO_EXT[image.content_type]

    # The row keeps the org-scoped storage key — what the storage layer
    # returns, never the address it would build:
    # ``<org>/items/<id>/cover.<digest>.<ext>``. The digest makes a replaced
    # picture a new address; the old file goes once the row names the new one.
    # The address is built when the row is read (``Item.image_url``), so
    # moving the files or switching backends rewrites nothing.
    previous_leaf = cover_leaf_of(item.image_url)
    leaf = cover_leaf(content, ext)
    stored_key = await core_api.file_storage.save_for_org_async(
        org_id, 'items', f'{item_id}/{leaf}', content, image.content_type
    )
    url = served_url(stored_key)

    await update_item(
        db=db, item=item, item_in=ItemUpdate(image_url=url), user=current_user
    )
    if previous_leaf and previous_leaf != leaf:
        try:
            await core_api.file_storage.delete_for_org_async(
                org_id, 'items', f'{item_id}/{previous_leaf}'
            )
        except FileNotFoundError:
            pass
    return {'image_url': url}


@router.delete('/{item_id}/image', status_code=status.HTTP_204_NO_CONTENT)
async def delete_item_image(
    item_id: UUID,
    user_storage_ids: list[UUID] = Depends(get_user_storage_ids),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
):
    """Delete the cover image for an item."""
    org_id = require_org(current_user)
    item = await get_item_or_404_async(db, item_id, user_storage_ids)

    # The row is writable through the item form, so it never names the object
    # this deletes: a reference naming another item's cover would otherwise
    # pick that object. Only the cover's file name is read, and the key is
    # rebuilt from this organization and this item — the facade owns the
    # ``<org>/items/`` prefix. A picture on somebody else's server answers no
    # file name, so removing the reference is all this endpoint does about it.
    leaf = cover_leaf_of(item.image_url)
    if leaf:
        try:
            await core_api.file_storage.delete_for_org_async(
                org_id, 'items', f'{item_id}/{leaf}'
            )
        except FileNotFoundError:
            pass

    await update_item(
        db=db, item=item, item_in=ItemUpdate(image_url=None), user=current_user
    )
