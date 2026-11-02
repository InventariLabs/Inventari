from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.announcement import AnnouncementType


class AnnouncementBase(BaseModel):
    title: str
    content: str
    type: AnnouncementType = AnnouncementType.INFO
    active_until: datetime | None = None


class AnnouncementCreate(AnnouncementBase):
    pass


class Announcement(AnnouncementBase):
    id: UUID
    active_from: datetime
    is_active: bool
    created_at: datetime
    created_by: UUID | None

    model_config = ConfigDict(from_attributes=True)
