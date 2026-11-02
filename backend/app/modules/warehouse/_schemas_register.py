"""Register, Inventory Period, and Type Config Pydantic schemas.

Extracted from ``schemas.py`` — these are leaf schemas with no cross-references
to core document schemas.
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ─── Register schemas ─────────────────────────────────────────────────────────


class RegisterDocumentRow(BaseModel):
    """Single document row in a register group."""

    id: UUID
    number: str
    type: str
    status: str
    date: date
    partner_name: str | None
    source_location_name: str | None
    target_location_name: str | None
    total_net: Decimal | None
    total_tax: Decimal | None
    total_gross: Decimal | None
    currency: str | None
    # The dispatch's hand-over, flattened into the row the register prints:
    # a column each for the carrier and the tracking link. Flat rather than
    # the shipment schema because this leaf module keeps no cross-reference
    # to the document schemas, and the register shows no package count,
    # time or notes.
    carrier: str | None = None
    tracking_number: str | None = None
    tracking_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class RegisterCurrencyTotal(BaseModel):
    """Aggregated totals for one currency — sums are never mixed across currencies."""

    currency: str | None
    total_net: Decimal | None
    total_tax: Decimal | None
    total_gross: Decimal | None


class RegisterGroup(BaseModel):
    """One group in the register summary (grouped by type/partner/location/month).

    Carries the sums for the whole window, no rows — the documents come from
    ``GET /warehouse/register/rows`` one page at a time.
    """

    key: str
    # None for the bucket of documents with no partner / no location: the
    # group has no name of its own, and inventing one here would ship an
    # untranslated display string as data.
    label: str | None
    document_count: int
    total_net: Decimal | None
    total_tax: Decimal | None
    total_gross: Decimal | None
    # flat totals are the sum of a single currency only; when the group
    # spans multiple currencies they are None and `totals_by_currency` carries
    # the per-currency sums instead.
    currency: str | None = None
    totals_by_currency: list[RegisterCurrencyTotal] = []


class RegisterSummary(BaseModel):
    """Aggregate totals across all groups."""

    total_documents: int
    total_net: Decimal | None
    total_tax: Decimal | None
    total_gross: Decimal | None
    currency: str | None = None
    totals_by_currency: list[RegisterCurrencyTotal] = []
    #: Whether anything in the window was handed to a carrier. The register
    #: offers its carrier and tracking columns only when something did —
    #: two empty columns over an organization that never ships are noise.
    has_shipments: bool = False
    #: Scrap documents in the window. Their value is what the write-off cost,
    #: and it is inside the totals above — a month total that does not say
    #: so reads as the value of what came and went, not of what was lost.
    scrap_documents: int = 0
    #: Completed-or-not documents of the window that should carry a value
    #: and carry none (a receipt posted without a price). They add nothing
    #: to the totals above, so a total with a count here is a lower bound.
    #: Zero where the profile tracks no value at all.
    documents_without_value: int = 0


class RegisterResponse(BaseModel):
    """Response from GET /warehouse/register/summary."""

    date_from: date
    date_to: date
    group_by: str
    groups: list[RegisterGroup]
    summary: RegisterSummary


# ─── Inventory Period schemas ─────────────────────────────────────────────────


class InventoryPeriodSchema(BaseModel):
    id: UUID
    year: int
    month: int
    #: Whether the month is locked right now. Stated rather than inferred
    #: from ``closed_at``, which is a stamp of the last closure and stays put
    #: when the month is reopened.
    is_closed: bool
    closed_at: datetime | None
    closed_by: str | None
    reopened_at: datetime | None
    reopened_by: str | None
    notes: str | None

    model_config = ConfigDict(from_attributes=True)


class InventoryPeriodCreate(BaseModel):
    year: int = Field(..., ge=2000, le=2100)
    month: int = Field(..., ge=1, le=12)
    notes: str | None = None


# ── Document Type Config ────────────────────────────────────────────────────


class DocumentTypeConfigCreate(BaseModel):
    document_type: str = Field(max_length=15)
    default_source_location_id: UUID | None = None
    default_target_location_id: UUID | None = None
    sequence_format: str = Field(default='{TYPE}/{YEAR}/{SEQ:05d}', max_length=50)
    require_partner: bool = False


class DocumentTypeConfigUpdate(BaseModel):
    default_source_location_id: UUID | None = None
    default_target_location_id: UUID | None = None
    sequence_format: str | None = Field(default=None, max_length=50)
    require_partner: bool | None = None


class DocumentTypeConfigOut(BaseModel):
    id: UUID
    organization_id: UUID
    document_type: str
    default_source_location_id: UUID | None = None
    default_target_location_id: UUID | None = None
    sequence_format: str
    require_partner: bool

    model_config = ConfigDict(from_attributes=True)
