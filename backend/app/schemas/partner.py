import re
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.contracts import (
    CUSTOMER_ROLE_TYPES as CUSTOMER_ROLE_TYPES,
)
from app.core.contracts import (
    SUPPLIER_ROLE_TYPES as SUPPLIER_ROLE_TYPES,
)
from app.core.contracts._core_dtos import ISO_3166_ALPHA2_CODES
from app.core.exceptions import ServiceRejectionError

ALLOWED_PARTNER_TYPES = frozenset(
    {'SUPPLIER', 'CUSTOMER', 'BOTH', 'SERVICE_PROVIDER', 'MANUFACTURER', 'EMPLOYEE'}
)

# Canonical role sets: the contract owns them, so every consumer — document
# validation, the purchase-order workflow, the pricelist and both partner
# dropdowns — answers "who is a supplier?" the same way, including modules
# kept out of the core schemas by the import lint. Re-exported here for the
# core callers that already import this module.


class PartnerAddress(BaseModel):
    """Structured partner address accepted on create/update.

    ``extra='forbid'`` rejects unknown keys so dead data never reaches the
    JSONB column. ``country`` is an ISO 3166-1 alpha-2 code (two uppercase
    letters); :class:`PartnerAddressOut` is the lenient read shape that
    tolerates legacy free-text country values already stored in the DB.
    """

    model_config = ConfigDict(extra='forbid')

    street: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=255)
    postal_code: str | None = Field(None, max_length=20)
    country: str | None = Field(None, max_length=2)

    @field_validator('country', mode='before')
    @classmethod
    def validate_country_code(cls, v: object) -> str | None:
        if v is None or v == '':
            return None
        code = str(v).strip().upper()
        if code not in ISO_3166_ALPHA2_CODES:
            raise ServiceRejectionError('invalid_country_code')
        return code


class PartnerAddressOut(BaseModel):
    """Lenient read shape for a partner address.

    ``extra='allow'`` preserves unknown legacy keys instead of rejecting them,
    and ``country`` may be a free-text value (e.g. "Polska") written before the
    ISO alpha-2 migration. The frontend renders such values as "other: <value>".
    """

    model_config = ConfigDict(extra='allow')

    street: str | None = None
    city: str | None = None
    postal_code: str | None = None
    country: str | None = None


class PartnerBase(BaseModel):
    name: str = Field(max_length=255)
    code: str | None = Field(None, max_length=50)
    type: str = Field(max_length=30)
    # Free text by design (max 50, no format validation) — domain/geo-neutral
    # platform; per-country validation deferred to (see
    # decision trd12-partner-tax-id-2026-08-22).
    tax_id: str | None = Field(None, max_length=50)
    # A private person, who has no tax id; the documents' tax-id requirement
    # does not apply to them.
    is_consumer: bool = False
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    website: str | None = Field(None, max_length=500)
    contact_person: str | None = Field(None, max_length=255)
    notes: str | None = None

    @field_validator('type')
    @classmethod
    def validate_type(cls, v: str) -> str:
        upper = v.upper()
        if upper not in ALLOWED_PARTNER_TYPES:
            raise ServiceRejectionError('invalid_partner_type')
        return upper

    @field_validator('website')
    @classmethod
    def validate_website(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not re.match(r'^https?://', v):
            return f'https://{v}'
        return v


class PartnerCreate(PartnerBase):
    address: PartnerAddress | None = None


class PartnerUpdate(BaseModel):
    """All fields optional — supports partial (PATCH-style) updates via PUT."""

    name: str | None = Field(None, max_length=255)
    code: str | None = Field(None, max_length=50)
    type: str | None = Field(None, max_length=30)
    # Free text by design (max 50, no format validation) — domain/geo-neutral
    # platform; per-country validation deferred to (see
    # decision trd12-partner-tax-id-2026-08-22).
    tax_id: str | None = Field(None, max_length=50)
    is_consumer: bool | None = None
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    website: str | None = Field(None, max_length=500)
    contact_person: str | None = Field(None, max_length=255)
    address: PartnerAddress | None = None
    notes: str | None = None

    @field_validator('type')
    @classmethod
    def validate_type(cls, v: str | None) -> str | None:
        if v is None:
            return v
        upper = v.upper()
        if upper not in ALLOWED_PARTNER_TYPES:
            raise ServiceRejectionError('invalid_partner_type')
        return upper


class PartnerSchema(PartnerBase):
    """Full response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    is_active: bool
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    address: PartnerAddressOut | None = None


class PartnerListItem(PartnerSchema):
    """List item with document collaboration stats.

    Aggregated in ``partner_service.list_partners_async`` from the
    ``documents`` table; zero-valued when no documents reference the partner.
    """

    document_count: int = 0
    total_amount: Decimal | None = None
    # Currency of ``total_amount`` — set only when the partner's non-draft
    # documents fall under exactly one currency; None means no turnover or
    # multiple currencies, and the UI says so instead of guessing.
    turnover_currency: str | None = None
    last_activity_at: datetime | None = None
    # Every status counts (DRAFT and CANCELLED included): the sheet link this
    # number backs opens the purchase-order list, whose status filter defaults
    # to ALL. ``document_count`` beside it deliberately excludes DRAFT — the
    # two semantics are both intentional, not an oversight.
    purchase_order_count: int = 0


class PartnerImportResponse(BaseModel):
    """What one partner import did; ``errors`` names the row and the reason."""

    total: int
    imported: int
    failed: int
    errors: list[dict] = []
