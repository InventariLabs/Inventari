from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# A closed set of values belongs in the schema, not only in the form that
# happens to offer it today: `max_length=30` accepted 'grass green' and the
# screen then had nothing to draw. The frontend mirrors this list in
# `hooks/types.ts`.
WidgetColor = Literal['blue', 'green', 'amber', 'red', 'violet', 'slate']


class WidgetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    color: WidgetColor = 'blue'
    quantity: int = Field(default=0, ge=0)


class WidgetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    color: WidgetColor | None = None
    quantity: int | None = Field(default=None, ge=0)


class WidgetSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    color: str
    quantity: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
