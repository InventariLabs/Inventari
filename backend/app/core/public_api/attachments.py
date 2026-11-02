"""
CoreAttachmentsAPI — module-safe access to ItemAttachment records.

DTO-only surface: ORM-level access (eager-loaded relationships
for file serving and mutations) stays inside Core — ``AttachmentService``
is used directly by ``app/api/attachments.py`` and upload resolvers.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ItemAttachmentDTO, ItemDTO
from app.core.logging import get_logger

logger = get_logger(__name__)


class CoreAttachmentsAPI:
    """Public Core API for module-safe ItemAttachment access."""

    async def find_by_file_path_async(
        self, db: AsyncSession, file_path: str, organization_id: UUID
    ) -> ItemAttachmentDTO | None:
        """Find an ItemAttachment DTO by its stored file_path.

        Only returns attachments belonging to *organization_id*
        (via item.storage_location).
        """
        from app.services.attachment_service import AttachmentService

        attachment = await AttachmentService.find_by_file_path_async(
            db, file_path, organization_id=organization_id
        )
        return ItemAttachmentDTO.model_validate(attachment) if attachment else None

    async def get_item_with_storage_async(
        self, db: AsyncSession, item_id: UUID, organization_id: UUID
    ) -> ItemDTO | None:
        """Return an Item DTO with eager-loaded storage_location, or None.

        Only returns items belonging to *organization_id*
        (via storage_location).
        """
        from app.services.attachment_service import AttachmentService

        item = await AttachmentService.get_item_with_storage_async(
            db, item_id, organization_id=organization_id
        )
        return ItemDTO.model_validate(item) if item else None

    async def get_attachment_with_item_async(
        self, db: AsyncSession, attachment_id: UUID, organization_id: UUID
    ) -> ItemAttachmentDTO | None:
        """Return an ItemAttachment DTO with eager-loaded item.storage_location, or None.

        Only returns attachments belonging to *organization_id*
        (via item.storage_location).
        """
        from app.services.attachment_service import AttachmentService

        attachment = await AttachmentService.get_attachment_with_item_async(
            db, attachment_id, organization_id=organization_id
        )
        return ItemAttachmentDTO.model_validate(attachment) if attachment else None
