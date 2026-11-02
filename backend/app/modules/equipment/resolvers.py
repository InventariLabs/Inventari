"""Equipment module upload path resolver.

Registers an :class:`UploadPathResolver` so the core ``/uploads/{path}``
serving route can verify ownership of equipment attachment files, which live in
the module-local ``equipment_attachments`` table (the core serving route only
consults core tables by default).
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contributions import OwnedFileMeta, UploadPathResolver

from .models import EquipmentAttachment


class EquipmentAttachmentResolver(UploadPathResolver):
    """Resolve ``<org_id>/equipment/<item_id>/<uuid>.<ext>`` — equipment
    attachments.

    The row stores the org-relative path (``<item_id>/<uuid>.<ext>``); the
    ``<org>/equipment/`` prefix is added by every storage call, so the first
    URL segment must be the asking organization's id and the rest resolves,
    org-scoped, against the module-local table — no cross-module lookup
    needed.

    A row written before the org-scoped move holds ``equipment/<item_id>/<file>``
    and is not resolved here: it names no organization, and serving it would
    reach outside the caller's namespace. Those rows are not migrated —
    development and demo stores are reset, not upgraded — so this read
    closes instead of opening a legacy branch.
    """

    async def resolve(
        self,
        db: AsyncSession,
        file_path: str,
        organization_id: UUID,
    ) -> OwnedFileMeta | None:
        parts = file_path.split('/')
        # Expected shape: <org_id>/equipment/<item_id>/<file>
        if (
            len(parts) != 4
            or parts[0] != str(organization_id)
            or parts[1] != 'equipment'
        ):
            return None
        row = (
            await db.scalars(
                select(EquipmentAttachment).where(
                    EquipmentAttachment.file_path == f'{parts[2]}/{parts[3]}',
                    EquipmentAttachment.organization_id == organization_id,
                )
            )
        ).first()
        if row is None:
            return None
        return OwnedFileMeta(
            content_type=row.content_type,
            display_name=row.original_name,
        )
