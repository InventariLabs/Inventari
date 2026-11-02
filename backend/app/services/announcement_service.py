from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.logging import get_logger
from app.models.announcement import Announcement
from app.schemas.announcement import AnnouncementCreate

logger = get_logger(__name__)


class AnnouncementService:
    @staticmethod
    async def list_all_async(db: AsyncSession) -> list[Announcement]:
        """Return all announcements (active, expired, future) ordered newest first."""
        result = await db.scalars(
            select(Announcement).order_by(Announcement.created_at.desc())
        )
        return list(result.all())

    @staticmethod
    async def list_active_async(db: AsyncSession) -> list[Announcement]:
        """Return currently active announcements (now within active window)."""
        now = datetime.now(UTC)
        result = await db.scalars(
            select(Announcement)
            .where(
                Announcement.is_active.is_(True),
                Announcement.active_from <= now,
                (Announcement.active_until.is_(None))
                | (Announcement.active_until >= now),
            )
            .order_by(Announcement.created_at.desc())
        )
        return list(result.all())

    @staticmethod
    async def get_by_id_async(
        db: AsyncSession, announcement_id: UUID
    ) -> Announcement | None:
        """Return a single announcement by ID, or ``None``."""
        result = await db.scalar(
            select(Announcement).where(Announcement.id == announcement_id)
        )
        return result

    @staticmethod
    async def create_announcement_async(
        db: AsyncSession, announcement_in: AnnouncementCreate, user: UserContextDTO
    ) -> Announcement:
        """Async: create a new global announcement."""
        announcement = Announcement(
            title=announcement_in.title,
            content=announcement_in.content,
            type=announcement_in.type,
            active_until=announcement_in.active_until,
            created_by=user.id,
        )
        db.add(announcement)
        await db.flush()
        await db.refresh(announcement)
        return announcement

    @staticmethod
    async def delete_announcement_async(
        db: AsyncSession, announcement: Announcement
    ) -> None:
        """Async: delete an announcement."""
        await db.delete(announcement)
        await db.flush()
