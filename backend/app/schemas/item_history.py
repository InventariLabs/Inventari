from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ItemHistorySchema(BaseModel):
    """Schema for item history entry"""

    id: UUID
    item_id: UUID
    organization_id: UUID | None
    user_id: UUID | None
    action: str  # ItemAction enum value
    changes: dict | None
    created_at: datetime

    # Enriched data for display
    item_name: str | None = None
    user_name: str | None = None
    source_document_id: UUID | None = None

    model_config = ConfigDict(from_attributes=True)
