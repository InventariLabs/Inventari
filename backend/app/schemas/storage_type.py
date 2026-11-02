from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.category import CategoryFieldDefinition


class StorageTypeBase(BaseModel):
    name: str
    type_code: str
    behavior_mode: str = 'STOCK'
    icon: str | None = None
    default_settings: dict[str, Any] | None = None
    context_schema: list[str] | None = None
    # tightens from list[dict[str, Any]] to the typed
    # CategoryFieldDefinition (same closed-set + per-type validators as Category).
    field_definitions: list[CategoryFieldDefinition] | None = None


class StorageTypeCreate(StorageTypeBase):
    """Create payload — the owning organization is taken from the caller."""


class StorageTypeUpdate(BaseModel):
    name: str | None = None
    icon: str | None = None
    behavior_mode: str | None = None
    default_settings: dict[str, Any] | None = None
    context_schema: list[str] | None = None
    # typed list[CategoryFieldDefinition].
    field_definitions: list[CategoryFieldDefinition] | None = None


class StorageType(StorageTypeBase):
    id: UUID
    organization_id: UUID | None = None
    is_system: bool = False
    created_by: UUID | None = None

    model_config = ConfigDict(from_attributes=True)
