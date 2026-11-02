import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AnnouncementType(StrEnum):
    INFO = 'info'
    WARNING = 'warning'
    CRITICAL = 'critical'
    DOWNTIME = 'downtime'


class Announcement(Base):
    """Installation-wide announcements (maintenance, updates, etc.).

    Deliberately tenant-less: one row is read by every organisation on the
    installation, which is why writing one is a superuser act (see
    ``app/api/announcements.py``). An organisation that wants to talk to its
    own members needs a different, tenant-scoped surface — do not reach for
    this table by adding an ``organization_id`` to it without also filtering
    both read paths in ``AnnouncementService``.
    """

    __tablename__ = 'announcements'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(50), default=AnnouncementType.INFO)

    # Scheduling
    active_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    active_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)  # Admin ID

    def __repr__(self):
        return f'<Announcement(title="{self.title}", type="{self.type}")>'
