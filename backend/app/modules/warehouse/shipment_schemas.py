from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, field_validator

Carrier = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class ShipmentCreate(BaseModel):
    """The hand-over a dispatch's completion records beside its stock."""

    carrier: Carrier
    #: Absent or blank for a hand-over that has none (the organization's own
    #: van, a pick-up at the counter).
    tracking_number: str | None = Field(default=None, max_length=100)
    #: Defaults to the moment of completion.
    shipped_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator('tracking_number')
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        value = value.strip() if value is not None else None
        return value or None


class DocumentShipmentSchema(BaseModel):
    carrier: str
    tracking_number: str | None = None
    #: The carrier's tracking page for this number — from the organization's
    #: templates, then the built-in ones; ``None`` when neither names the
    #: carrier or there is no number, and the number is shown as it is.
    tracking_url: str | None = None
    shipped_at: datetime
    shipped_by: UUID | None = None
    #: The hand that handed the parcel over, as the document's other actor
    #: fields name theirs.
    shipped_by_name: str | None = None
    notes: str | None = None
    package_count: int = 0


class CarrierSuggestions(BaseModel):
    #: The organization's carriers, the most recently used first.
    carriers: list[str] = []
