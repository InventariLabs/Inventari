from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ItemAttachmentSchema(BaseModel):
    id: UUID
    item_id: UUID
    file_path: str
    file_name: str
    file_type: str
    file_size: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
