"""Maker module upload path resolver.

Registers an :class:`UploadPathResolver` so the core ``/uploads/{path}``
serving route can verify ownership of a production run's files, which live
in the module-local ``maker_production_attachments`` table.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.module_sdk import OwnedFileMeta, UploadPathResolver

from .models import ProductionAttachment


class ProductionAttachmentResolver(UploadPathResolver):
    """Resolve ``<org_id>/maker/<order_id>/<uuid>.<ext>`` — a run's files.

    The row keeps the org-relative path (``<order_id>/<uuid>.<ext>``); the
    first segment must be the asking organization's id, and the rest
    resolves, org-scoped, against the module's own table.
    """

    async def resolve(
        self,
        db: AsyncSession,
        file_path: str,
        organization_id: UUID,
    ) -> OwnedFileMeta | None:
        parts = file_path.split('/')
        if len(parts) != 4 or parts[0] != str(organization_id) or parts[1] != 'maker':
            return None
        row = await db.scalar(
            select(ProductionAttachment).where(
                ProductionAttachment.file_path == f'{parts[2]}/{parts[3]}',
                ProductionAttachment.organization_id == organization_id,
            )
        )
        if row is None:
            return None
        return OwnedFileMeta(
            content_type=row.content_type,
            display_name=row.original_name,
        )
