"""
Module-safe access to global announcements (read and write).

Modules should not query ``Announcement`` directly — they should use this API
to stay within the public contract.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AnnouncementCreateDTO, AnnouncementDTO, UserContextDTO
from app.core.logging import get_logger
from app.core.public_api._scope import without_org_scope
from app.services.announcement_service import AnnouncementService

logger = get_logger(__name__)


class CoreAnnouncementsAPI:
    """Public Core API for module-safe announcement reads and writes."""

    async def list_all_async(self, db: AsyncSession) -> list[AnnouncementDTO]:
        """Return all announcements (active, expired, future) ordered newest first."""
        announcements = await AnnouncementService.list_all_async(db)
        return [AnnouncementDTO.model_validate(a) for a in announcements]

    async def list_active_async(self, db: AsyncSession) -> list[AnnouncementDTO]:
        """Return currently active announcements (now within active window)."""
        announcements = await AnnouncementService.list_active_async(db)
        return [AnnouncementDTO.model_validate(a) for a in announcements]

    @without_org_scope('global rows: an announcement has no organization column')
    async def get_by_id_async(
        self, db: AsyncSession, announcement_id: UUID
    ) -> AnnouncementDTO | None:
        """Return a single announcement by ID, or ``None``."""
        announcement = await AnnouncementService.get_by_id_async(db, announcement_id)
        return AnnouncementDTO.model_validate(announcement) if announcement else None

    async def create_async(
        self,
        db: AsyncSession,
        announcement_in: AnnouncementCreateDTO,
        user: UserContextDTO,
    ) -> AnnouncementDTO:
        """Create a new global announcement. Returns the AnnouncementDTO."""
        from app.schemas.announcement import AnnouncementCreate

        internal = AnnouncementCreate(
            title=announcement_in.title,
            content=announcement_in.content,
            type=announcement_in.type,
            active_until=announcement_in.active_until,
        )
        announcement = await AnnouncementService.create_announcement_async(
            db, internal, user
        )
        return AnnouncementDTO.model_validate(announcement)

    @without_org_scope('global rows: an announcement has no organization column')
    async def delete_async(self, db: AsyncSession, announcement_id: UUID) -> bool:
        """Delete an announcement by ID. Returns ``True`` if deleted, ``False`` if not found."""
        announcement = await AnnouncementService.get_by_id_async(db, announcement_id)
        if announcement is None:
            return False
        await AnnouncementService.delete_announcement_async(db, announcement)
        return True
