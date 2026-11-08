import os
import uuid
from io import BytesIO
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.db_utils import after_commit
from app.core.demo_upload_cap import demo_upload_admission
from app.core.file_storage.service import FileStorageService
from app.core.logging import get_logger
from app.core.upload_validation import (
    ATTACHMENT_CONTENT_TYPES,
    UploadMessages,
    UploadPolicy,
)
from app.i18n import Language
from app.i18n.service import get_error_message
from app.models.audit_log import AuditAction, AuditTargetType
from app.models.item import Item
from app.models.item_attachment import ItemAttachment
from app.services.audit_service import log_action_async

logger = get_logger(__name__)


MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB

#: The storage segment below the organization: ``<org>/attachments/<item>/<file>``.
_ATTACHMENTS = 'attachments'


#: The filename gate in front of ``ATTACHMENT_CONTENT_TYPES``, one extension
#: per type on that list (no ``.doc``, for the reason given there).
ALLOWED_EXTENSIONS = {
    '.jpg',
    '.jpeg',
    '.png',
    '.gif',
    '.webp',
    '.pdf',
    '.txt',
    '.zip',
    '.docx',
    '.xls',
    '.xlsx',
}

#: What an item attachment may be. The extension list gates the filename as
#: well as the declared type, because that is the promise the upload dialog
#: on the item screen makes.
ITEM_ATTACHMENT_POLICY = UploadPolicy(
    max_bytes=MAX_UPLOAD_SIZE,
    content_types=ATTACHMENT_CONTENT_TYPES,
    extensions=frozenset(ALLOWED_EXTENSIONS),
)


class AttachmentService:
    @staticmethod
    async def find_by_file_path_async(
        db: AsyncSession, file_path: str, organization_id: UUID | None = None
    ) -> ItemAttachment | None:
        """Async: find an attachment by its stored file_path with eager loads."""
        from app.models.item import Item
        from app.models.storage_location import StorageLocation

        stmt = (
            select(ItemAttachment)
            .where(ItemAttachment.file_path == file_path)
            .options(joinedload(ItemAttachment.item).joinedload(Item.storage_location))
        )
        if organization_id is not None:
            stmt = (
                stmt.join(ItemAttachment.item)
                .join(Item.storage_location)
                .where(StorageLocation.organization_id == organization_id)
            )
        result = await db.scalars(stmt)
        return result.first()

    @staticmethod
    async def get_item_with_storage_async(
        db: AsyncSession, item_id: UUID, organization_id: UUID | None = None
    ) -> Item | None:
        """Async: return an Item with eager-loaded storage_location, or None."""
        from app.models.item import Item
        from app.models.storage_location import StorageLocation

        stmt = (
            select(Item)
            .options(joinedload(Item.storage_location))
            .where(Item.id == item_id)
        )
        if organization_id is not None:
            stmt = stmt.join(Item.storage_location).where(
                StorageLocation.organization_id == organization_id
            )
        result = await db.scalar(stmt)
        return result

    @staticmethod
    async def list_for_item_async(
        db: AsyncSession, item_id: UUID
    ) -> list[ItemAttachment]:
        """The item's attachments, oldest first. The caller has already
        established that the item is the reader's."""
        result = await db.scalars(
            select(ItemAttachment)
            .where(ItemAttachment.item_id == item_id)
            .order_by(ItemAttachment.created_at, ItemAttachment.id)
        )
        return list(result.all())

    @staticmethod
    async def get_attachment_with_item_async(
        db: AsyncSession, attachment_id: UUID, organization_id: UUID | None = None
    ) -> ItemAttachment | None:
        """Async: return an ItemAttachment with eager-loaded item.storage_location, or None."""
        from app.models.item import Item
        from app.models.storage_location import StorageLocation

        stmt = (
            select(ItemAttachment)
            .options(joinedload(ItemAttachment.item).joinedload(Item.storage_location))
            .where(ItemAttachment.id == attachment_id)
        )
        if organization_id is not None:
            stmt = (
                stmt.join(ItemAttachment.item)
                .join(Item.storage_location)
                .where(StorageLocation.organization_id == organization_id)
            )
        result = await db.scalar(stmt)
        return result

    @staticmethod
    async def create_attachment(
        db: AsyncSession,
        organization_id: UUID,
        item_id: UUID,
        file: UploadFile,
        lang: Language = 'en',
        *,
        user_id: UUID | None,
    ) -> ItemAttachment:
        """Validate an upload, store it, and create the attachment record.

        Validation lives here rather than in the router so that every caller
        gets it — a second caller added later cannot bypass the checks by not
        repeating them. The rules themselves are ``ITEM_ATTACHMENT_POLICY``;
        it raises ``FileTypeNotAllowedError`` (415),
        ``FileSignatureMismatchError`` (400) or ``FileTooLargeError`` (413),
        and the router maps those onto the codes in parentheses.

        The bytes go through file storage under ``<org>/attachments/``, the
        same abstraction ``/uploads/`` serves from — whatever the backend. The
        object is written before the row, and removed again when the row
        cannot be, so a record never points at nothing. The journal entry
        rides the row's commit: a file nobody can account for is not filed.
        """
        original_filename = os.path.basename(file.filename or 'unnamed')
        declared_type = file.content_type or 'application/octet-stream'

        # Read once and keep the bytes: what we validate is exactly what we
        # store, so the file cannot change between the check and the save.
        content = await file.read()
        await file.seek(0)

        accepted = ITEM_ATTACHMENT_POLICY.check(
            content,
            declared_type=declared_type,
            filename=original_filename,
            messages=UploadMessages(
                type_not_allowed=get_error_message('file_type_not_allowed', lang),
                too_large=get_error_message('file_too_large', lang),
                signature_mismatch=get_error_message('file_signature_mismatch', lang),
            ),
        )
        stored_type = accepted.stored_type
        safe_name = f'{uuid.uuid4().hex}.{accepted.extension}'

        try:
            stored_path = f'{organization_id}/{_ATTACHMENTS}/{item_id}/{safe_name}'
            async with demo_upload_admission(len(content)):
                await FileStorageService().save(
                    stored_path, BytesIO(content), stored_type
                )
        except OSError as e:
            logger.error(f'Failed to store attachment for item {item_id}: {e}')
            raise RuntimeError(get_error_message('internal_error', lang)) from e

        attachment = ItemAttachment(
            item_id=item_id,
            file_path=stored_path,
            file_name=original_filename,
            file_type=stored_type,
            file_size=len(content),
        )
        db.add(attachment)
        try:
            # The router has just loaded the item in this session, so this is
            # the identity map, not a second query.
            item = await db.get(Item, item_id)
            await _journal_attachment(
                db,
                organization_id,
                user_id,
                item_id,
                getattr(item, 'name', None),
                before=None,
                after=original_filename,
            )
            await db.flush()
        except SQLAlchemyError:
            await _discard_stored(stored_path)
            raise
        await db.refresh(attachment)
        return attachment

    @staticmethod
    async def delete_attachment(
        db: AsyncSession,
        attachment: ItemAttachment,
        organization_id: UUID,
        user_id: UUID | None,
    ) -> None:
        """Remove the record, then the stored object.

        In that order: an object left behind by a failed delete is invisible
        and harmless, a record left pointing at a deleted object is a 404
        on the item screen. So the object goes only once the caller's
        transaction has committed the delete. The journal entry goes in with
        the row's removal: the file is gone for good, and the entry is all
        that says it was there.
        """
        stored_path = attachment.file_path
        await _journal_attachment(
            db,
            organization_id,
            user_id,
            attachment.item_id,
            attachment.item.name if attachment.item else None,
            before=attachment.file_name,
            after=None,
        )
        await db.delete(attachment)
        await db.flush()
        after_commit(db, lambda: _discard_stored(stored_path))


async def _journal_attachment(
    db: AsyncSession,
    organization_id: UUID,
    user_id: UUID | None,
    item_id: UUID,
    item_name: str | None,
    *,
    before: str | None,
    after: str | None,
) -> None:
    """A file added to or taken off a product is an edit to that product."""
    await log_action_async(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.ITEM,
        target_id=item_id,
        snapshot={
            'name': item_name,
            'before': {'attachment': before},
            'after': {'attachment': after},
        },
    )


async def _discard_stored(stored_path: str) -> None:
    """Delete a stored attachment object; a missing one is already gone."""
    try:
        await FileStorageService().delete(stored_path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning('Failed to delete attachment object %s: %s', stored_path, exc)
