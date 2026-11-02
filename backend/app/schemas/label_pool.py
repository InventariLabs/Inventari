from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.contracts._documents_dtos import LabelScanDTO
from app.core.label_codes import LABEL_PREFIX_MAX_LENGTH, LABEL_PREFIX_PATTERN
from app.schemas.pagination import PaginatedResponse
from app.schemas.validators import empty_string_to_none


class LabelPoolBase(BaseModel):
    short_code: str


class LabelPoolCreate(BaseModel):
    count: int = Field(50, ge=1, le=500, description='Number of labels to generate')
    # The character class and the cap come from the same module the
    # scanner reads its pattern out of: this field's own example ('B12')
    # used to produce codes the scanner refused, because the two were
    # written apart and disagreed about digits.
    prefix: str = Field(
        'STM',
        min_length=1,
        max_length=LABEL_PREFIX_MAX_LENGTH,
        pattern=LABEL_PREFIX_PATTERN,
        description=(
            f'Alphanumeric prefix for the short code '
            f'(1–{LABEL_PREFIX_MAX_LENGTH} chars, e.g. STM, A, B12)'
        ),
    )
    label_type: str = 'GENERIC'
    description: str | None = None
    target_location_id: UUID | None = None
    context_tag: str | None = None

    @field_validator('target_location_id', mode='before')
    @classmethod
    def empty_string_to_none(cls, v):
        return empty_string_to_none(v)


class LabelCodeItem(BaseModel):
    """A single explicit short_code to register in the LabelPool."""

    short_code: str = Field(min_length=1, max_length=20)
    description: str | None = None


class LabelFromCodesRequest(BaseModel):
    """Create labels with explicit short_codes (e.g. equipment serials).

    Uniqueness is enforced per organization; a short_code already used in the
    org (or duplicated within this request) is rejected with 409.
    """

    codes: list[LabelCodeItem] = Field(min_length=1, max_length=500)
    label_type: str = 'GENERIC'
    context_tag: str | None = None


class LabelPoolResponse(LabelPoolBase):
    id: UUID
    is_assigned: bool
    assigned_at: datetime | None = None
    item_id: UUID | None = None
    organization_id: UUID
    label_type: str
    description: str | None = None
    target_location_id: UUID | None = None
    created_at: datetime
    printed_at: datetime | None = None
    scan_count: int
    context_tag: str | None = None
    is_item_deleted: bool | None = None
    assigned_item_name: str | None = None
    assigned_item_quantity: float | None = None
    assigned_item_unit: str | None = None
    assigned_item_context_tag: str | None = None

    model_config = ConfigDict(from_attributes=True)


class LabelPoolListResponse(PaginatedResponse[LabelPoolResponse]):
    """Paginated response for the label pool list endpoint."""


class LabelScanResponse(LabelScanDTO):
    """The scan endpoint's published answer.

    Same fields as the contract the providers build (``LabelScanDTO``); the
    subclass keeps the component name this API has always published.
    """


class LabelAssignRequest(BaseModel):
    """Data for quick product addition via scan"""

    location_id: UUID
    category_id: UUID | None = None
    name: str
    brand: str | None = None
    description: str | None = None
    quantity: float = Field(default=1.0, ge=0)
    uom_id: UUID | None = None
    # Weight of a single unit; it is kept on the product template, not on the
    # item (ADR-015).
    weight_value: float | None = None
    weight_uom_id: UUID | None = None
    expiry_date: str | None = None
    freeze_date: str | None = None
    image_url: str | None = None
    metadata: dict | None = None
    # The form after a scan is the product form, so it renders these four
    # as well — and a request that cannot carry them made the reader type
    # into fields whose content was dropped on the way, under a 200. Every
    # one of them is a column on the record; what the form asks for, the
    # request carries.
    serial_number: str | None = None
    purchase_price: Decimal | None = None
    shelf_location: str | None = None
    #: The product's code, when the scanned code is a pool label and not one.
    #: A scanned barcode is the product's code itself and wins over this.
    barcode: str | None = None
    #: The form after a scan is the product form, so it asks this too — a
    #: unit that differs from the matched template's is a deliberate choice
    #: and has to be confirmed (``app.services.items._unit_choice``). The
    #: field used to live only on ``ItemCreate``: the form settled it on the
    #: payload, this model dropped it on the floor, and the scan door kept
    #: its own opinion about the rule.
    unit_confirmed_over_template: bool = False
