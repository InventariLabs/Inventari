"""Photos and files filed under a production run.

A batch is documented with what was seen while it was made — a photo of the
filled jars, a thermometer reading, a supplier's certificate for an
ingredient. They are filed under the run, not under the record its output
went into: a record is consumed, split and moved, a run stays.

The limits are the ones an attachment on a product has (ten megabytes, the
attachment types, the bytes checked against the declared type), and each
file filed or removed is an entry in the run's journal, as on a product.
"""

from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType, UserContextDTO
from app.core.exceptions import EntityNotFoundError
from app.core.logging import get_logger
from app.core.module_sdk import (
    ATTACHMENT_CONTENT_TYPES,
    UploadMessages,
    UploadPolicy,
    served_url,
)
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message

from ._schemas_batches import ProductionAttachmentRead
from .models import ProductionAttachment, ProductionOrder

logger = get_logger(__name__)

#: The folder under the organization's storage the files go to.
STORAGE_FOLDER = 'maker'

#: What a product's attachment may be, and as large.
ATTACHMENT_POLICY = UploadPolicy(
    max_bytes=10 * 1024 * 1024,
    content_types=ATTACHMENT_CONTENT_TYPES,
)


def served_address(organization_id: UUID, file_path: str) -> str:
    """Where a client loads the file: the app's own ``/uploads/``, ownership-checked."""
    return str(served_url(f'{organization_id}/{STORAGE_FOLDER}/{file_path}'))


def to_read(
    organization_id: UUID, row: ProductionAttachment
) -> ProductionAttachmentRead:
    return ProductionAttachmentRead(
        id=row.id,
        production_order_id=row.production_order_id,
        original_name=row.original_name,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        url=served_address(organization_id, row.file_path),
        uploaded_by=row.uploaded_by,
        created_at=row.created_at,
    )


async def _order_or_404(
    db: AsyncSession, organization_id: UUID, order_id: UUID
) -> ProductionOrder:
    order = await db.scalar(
        select(ProductionOrder).where(
            ProductionOrder.organization_id == organization_id,
            ProductionOrder.id == order_id,
        )
    )
    if order is None:
        raise EntityNotFoundError('production_order', str(order_id))
    return order


async def list_attachments(
    db: AsyncSession, organization_id: UUID, order_id: UUID
) -> list[ProductionAttachment]:
    """The run's files, newest first."""
    await _order_or_404(db, organization_id, order_id)
    rows = await db.scalars(
        select(ProductionAttachment)
        .where(
            ProductionAttachment.organization_id == organization_id,
            ProductionAttachment.production_order_id == order_id,
        )
        .order_by(ProductionAttachment.created_at.desc())
    )
    return list(rows.all())


async def upload_attachment(
    db: AsyncSession,
    organization_id: UUID,
    order_id: UUID,
    user: UserContextDTO,
    *,
    content: bytes,
    original_name: str,
    content_type: str,
) -> ProductionAttachment:
    """File one photo or document under the run; refused past the product limits."""
    order = await _order_or_404(db, organization_id, order_id)
    lang = get_current_lang()
    accepted = ATTACHMENT_POLICY.check(
        content,
        declared_type=content_type,
        messages=UploadMessages(
            type_not_allowed=get_error_message('file_type_not_allowed', lang),
            too_large=get_error_message('file_too_large', lang),
            signature_mismatch=get_error_message('file_signature_mismatch', lang),
        ),
    )
    file_path = f'{order_id}/{uuid.uuid4().hex}.{accepted.extension}'
    await core_api.file_storage.save_for_org_async(
        organization_id, STORAGE_FOLDER, file_path, content, accepted.stored_type
    )
    row = ProductionAttachment(
        organization_id=organization_id,
        production_order_id=order_id,
        file_path=file_path,
        original_name=original_name[:255],
        content_type=accepted.stored_type,
        size_bytes=len(content),
        uploaded_by=user.id,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    await _journal(db, order, user, before=None, after=row.original_name)
    return row


async def delete_attachment(
    db: AsyncSession,
    organization_id: UUID,
    order_id: UUID,
    attachment_id: UUID,
    user: UserContextDTO,
) -> str:
    """Drop the row and return the stored path; the caller removes the file after commit."""
    order = await _order_or_404(db, organization_id, order_id)
    row = await db.scalar(
        select(ProductionAttachment)
        .where(
            ProductionAttachment.organization_id == organization_id,
            ProductionAttachment.production_order_id == order_id,
            ProductionAttachment.id == attachment_id,
        )
        .with_for_update()
    )
    if row is None:
        raise EntityNotFoundError('attachment', str(attachment_id))
    await _journal(db, order, user, before=row.original_name, after=None)
    file_path = row.file_path
    await db.delete(row)
    await db.flush()
    return file_path


async def discard_stored_file(organization_id: UUID, file_path: str) -> None:
    """Remove a stored file; one that cannot be removed is only logged."""
    try:
        await core_api.file_storage.delete_for_org_async(
            organization_id, STORAGE_FOLDER, file_path
        )
    except (OSError, AttributeError):
        logger.warning('Orphaned file in storage: %s', file_path)


async def _journal(
    db: AsyncSession,
    order: ProductionOrder,
    user: UserContextDTO,
    *,
    before: str | None,
    after: str | None,
) -> None:
    """A file filed under a run, or taken off it, is an edit to the run."""
    await core_api.audit_log.log_action_async(
        db,
        organization_id=order.organization_id,
        user_id=user.id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.MAKER_PRODUCTION_ORDER,
        target_id=order.id,
        snapshot={
            'name': order.number,
            'before': {'attachment': before},
            'after': {'attachment': after},
        },
    )
