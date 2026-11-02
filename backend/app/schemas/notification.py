from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotificationBase(BaseModel):
    title: str
    content: str
    type: str = 'info'
    link: str | None = None
    meta_data: dict[str, Any] | None = None


class NotificationUpdate(BaseModel):
    is_read: bool


class Notification(NotificationBase):
    id: UUID
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
