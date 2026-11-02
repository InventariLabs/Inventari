from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MaintenanceLogCreate(BaseModel):
    item_id: UUID
    maintenance_type: str = Field(
        pattern='^(REPAIR|CLEANING|UPGRADE|INSPECTION|OTHER)$'
    )
    title: str = Field(max_length=255)
    description: str | None = None
    cost: Decimal | None = Field(None, ge=0)
    currency: str | None = Field(None, max_length=3)
    performed_at: date
    performed_by: str | None = Field(None, max_length=255)
    service_partner_id: UUID | None = None
    next_maintenance_at: date | None = None


class MaintenanceLogUpdate(BaseModel):
    maintenance_type: str | None = Field(
        None, pattern='^(REPAIR|CLEANING|UPGRADE|INSPECTION|OTHER)$'
    )
    title: str | None = Field(None, max_length=255)
    description: str | None = None
    cost: Decimal | None = None
    currency: str | None = None
    performed_at: date | None = None
    performed_by: str | None = None
    service_partner_id: UUID | None = None
    next_maintenance_at: date | None = None


class MaintenanceLogSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_id: UUID
    item_name: str
    maintenance_type: str
    title: str
    description: str | None
    cost: Decimal | None
    currency: str | None
    performed_at: date
    performed_by: str | None
    service_partner_id: UUID | None
    next_maintenance_at: date | None
    created_by: UUID
    created_at: datetime
