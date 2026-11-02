import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ItemAttachment(Base):
    """
    File attached to an item (e.g., manual, receipt, photo).
    """

    __tablename__ = 'item_attachments'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('items.id', ondelete='CASCADE'), index=True
    )

    file_path: Mapped[str] = mapped_column(
        String(500)
    )  # Path on disk relative to uploads root
    file_name: Mapped[str] = mapped_column(String(255))  # Original filename
    file_type: Mapped[str] = mapped_column(String(100))  # MIME type
    file_size: Mapped[int] = mapped_column(Integer)  # Size in bytes

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    # Relationships
    item: Mapped['Item'] = relationship(back_populates='attachments')  # type: ignore[name-defined]

    def __repr__(self):
        return f'<ItemAttachment(name="{self.file_name}", type="{self.file_type}")>'
