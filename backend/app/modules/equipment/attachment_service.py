import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType
from app.core.db_utils import get_org_owned_or_404_async
from app.core.exceptions import NotFoundException, ServiceRejectionError
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.core.upload_validation import UploadMessages, UploadPolicy
from app.i18n.service import get_current_lang

from ._unit_identity import audit_identity
from .models import EquipmentAttachment
from .schemas import AttachmentSchema

logger = get_logger(__name__)

ALLOWED_CONTENT_TYPES = {
    'application/pdf',
    'image/jpeg',
    'image/png',
    'image/gif',
    'image/webp',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'text/plain',
}

MAX_FILE_SIZE = 20 * 1024 * 1024

#: Twenty megabytes rather than the ten an item attachment gets, and
#: ``.doc`` among the accepted types: a warranty scan arrives as whatever
#: the supplier sent. The filename is not gated at all here — the name goes
#: into the record, the extension on disk comes from the validated type.
ATTACHMENT_POLICY = UploadPolicy(
    max_bytes=MAX_FILE_SIZE,
    content_types=frozenset(ALLOWED_CONTENT_TYPES),
)

VALID_FILE_TYPES = {'INVOICE', 'WARRANTY', 'PHOTO', 'MANUAL', 'OTHER'}


async def upload_attachment(
    db: AsyncSession,
    org_id: UUID,
    item_id: UUID,
    user_id: UUID,
    file_content: bytes,
    original_name: str,
    content_type: str,
    file_type: str,
) -> AttachmentSchema:
    item = await core_api.items.get_async(db, org_id, item_id)
    if not item:
        raise NotFoundException('item', get_current_lang())

    if file_type not in VALID_FILE_TYPES:
        raise ServiceRejectionError('attachment_file_type_invalid', file_type=file_type)

    accepted = ATTACHMENT_POLICY.check(
        file_content,
        declared_type=content_type,
        messages=UploadMessages(
            type_not_allowed=f'Unsupported file type: {content_type}',
            too_large='File too large (max 20 MB)',
            signature_mismatch=(
                f'File content does not match declared type {content_type}'
            ),
        ),
    )

    # The row keeps the org-relative path (<item_id>/<uuid>.<ext>); the
    # ``<org>/equipment/`` prefix is rebuilt by every storage call, so no
    # caller can peel the namespace off a stored value.
    file_path = f'{item_id}/{uuid.uuid4().hex}.{accepted.extension}'

    # What the bytes are, not what was claimed for them — this value is
    # served back to browsers.
    await core_api.file_storage.save_for_org_async(
        org_id, 'equipment', file_path, file_content, accepted.stored_type
    )
    url = await core_api.file_storage.get_url_for_org_async(
        org_id, 'equipment', file_path
    )

    attachment = EquipmentAttachment(
        organization_id=org_id,
        item_id=item_id,
        file_path=file_path,
        original_name=original_name,
        file_type=file_type,
        content_type=accepted.stored_type,
        size_bytes=len(file_content),
        uploaded_by=user_id,
    )
    db.add(attachment)
    await db.flush()
    await db.refresh(attachment)
    await _journal_attachment(
        db, org_id, user_id, item_id, item, before=None, after=original_name
    )

    return AttachmentSchema(
        id=attachment.id,
        item_id=attachment.item_id,
        original_name=attachment.original_name,
        file_type=attachment.file_type,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        url=url,
        uploaded_by=attachment.uploaded_by,
        created_at=attachment.created_at,
    )


async def list_attachments(
    db: AsyncSession, org_id: UUID, item_id: UUID
) -> list[AttachmentSchema]:
    # A read on the card: an archived asset keeps the papers filed under it
    # — they are exactly what a restore decision is made on. Only the
    # upload path stays live-only below.
    item = await core_api.items.get_any_async(db, org_id, item_id)
    if not item:
        raise NotFoundException('item', get_current_lang())

    rows = (
        await db.scalars(
            select(EquipmentAttachment)
            .where(
                EquipmentAttachment.organization_id == org_id,
                EquipmentAttachment.item_id == item_id,
            )
            .order_by(EquipmentAttachment.created_at.desc())
        )
    ).all()

    result = []
    for row in rows:
        try:
            url = await core_api.file_storage.get_url_for_org_async(
                org_id, 'equipment', row.file_path
            )
        except FileNotFoundError:
            # A row written before the org-scoped move keeps the path it had
            # then (``equipment/<item_id>/<file>``): the scoped read resolves
            # it under a ``<org>/equipment/`` prefix that never existed, and
            # paths written before the move are deliberately not migrated
            # (development and demo data is reset; the legacy bytes stay as
            # orphans). One such row must not take the whole list down with
            # it — the endpoint answers the rows it can serve and names the
            # skipped one in the log, instead of a 500 for every attachment
            # on the item.
            logger.warning(
                'Skipping attachment %s: file missing from storage (%s)',
                row.id,
                row.file_path,
            )
            continue
        result.append(
            AttachmentSchema(
                id=row.id,
                item_id=row.item_id,
                original_name=row.original_name,
                file_type=row.file_type,
                content_type=row.content_type,
                size_bytes=row.size_bytes,
                url=url,
                uploaded_by=row.uploaded_by,
                created_at=row.created_at,
            )
        )
    return result


async def delete_attachment(
    db: AsyncSession, org_id: UUID, attachment_id: UUID, user_id: UUID
) -> str:
    """Drop the attachment's row and return the path of its stored file.

    The journal entry goes in with the row: the file is about to be gone for
    good, and the entry is all that says the asset ever had it.

    The file is not touched here: the row's removal is only durable once the
    caller commits, and a file deleted ahead of a rollback leaves a row that
    points at nothing. The caller removes the file with
    :func:`discard_stored_file` once the commit has gone through.
    """
    attachment = await get_org_owned_or_404_async(
        db,
        EquipmentAttachment,
        attachment_id,
        org_id,
        resource='attachment',
        lang=get_current_lang(),
    )

    file_path = attachment.file_path
    # An archived asset keeps its papers, so its papers can be removed too.
    item = await core_api.items.get_any_async(db, org_id, attachment.item_id)
    await _journal_attachment(
        db,
        org_id,
        user_id,
        attachment.item_id,
        item,
        before=attachment.original_name,
        after=None,
    )
    await db.delete(attachment)
    await db.flush()
    return file_path


async def _journal_attachment(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    item_id: UUID,
    item: Any,
    *,
    before: str | None,
    after: str | None,
) -> None:
    """A paper filed under an asset, or taken off it, is an edit to the asset."""
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.EQUIPMENT_ASSET,
        target_id=item_id,
        snapshot={
            **audit_identity(item),
            'before': {'attachment': before},
            'after': {'attachment': after},
        },
    )


async def discard_stored_file(org_id: UUID, file_path: str) -> None:
    """Remove a stored attachment file; one that cannot be removed is only logged."""
    try:
        await core_api.file_storage.delete_for_org_async(org_id, 'equipment', file_path)
    except (OSError, AttributeError):
        logger.warning('Orphaned file in storage: %s', file_path)
