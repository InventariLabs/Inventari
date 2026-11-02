"""
Pydantic schemas for the stock take module.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import (
    AliasPath,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.core.exceptions import ServiceRejectionError
from app.schemas.validators import decimal_from_int_float

from .models import (
    FREE_TEXT_DISCREPANCY_CODE,
    CycleCountFrequency,
    CycleCountScope,
    StockTakeDiscrepancyCode,
    StockTakeStatus,
)

#: The counted quantities' shape — the stock_take_items columns are
#: numeric(10, 3), a third narrower than the items table's, so their
#: ceiling is their own and not the wider QUANTITY_MAX. The ceiling is the
#: largest value the column holds: mirrored as ``le=`` on the input
#: counting schemas (StockTakeItemCountUpdate, StockTakeItemUpdate,
#: StockTakeItemCreate — never on StockTakeItemBase, which the response
#: schemas share: a read must not refuse) and refused at the writer
#: (``count_item_and_commit``, its bulk twin and the surplus row) with the
#: bound named, where the driver would otherwise answer with the overflow.
COUNTED_QUANTITY_MAX = Decimal('9999999.999')


class StockTakeCountRead(BaseModel):
    """One pass of counting over one row, as the screens read it."""

    sequence: int
    quantity: Decimal
    counted_at: datetime
    counted_by_name: str | None = Field(
        None, validation_alias=AliasPath('counter', 'full_name')
    )

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class DiscrepancyReasonFields(BaseModel):
    """Why a counted quantity differs from what the system held.

    The code is what reports count; the note says what the code cannot, and
    becomes the reason itself when the code is OTHER.
    """

    discrepancy_reason_code: StockTakeDiscrepancyCode | None = None
    discrepancy_reason: str | None = Field(
        default=None,
        max_length=255,
        description='What the code does not say (required when the code is OTHER)',
    )

    @model_validator(mode='after')
    def other_needs_a_note(self) -> 'DiscrepancyReasonFields':
        if (
            self.discrepancy_reason_code == FREE_TEXT_DISCREPANCY_CODE
            and not (self.discrepancy_reason or '').strip()
        ):
            raise ServiceRejectionError('discrepancy_reason_required')
        return self


class StockTakeItemBase(BaseModel):
    """Base schema for stock take items."""

    item_name: str = Field('', description='Product name')
    item_brand: str | None = None
    system_quantity: Decimal | None = None
    # No ``le=`` here: the response schemas share this base, and a read of
    # a row that predates the bound must not refuse. The input schemas
    # carry the mirror (StockTakeItemCreate, StockTakeItemUpdate,
    # StockTakeItemCountUpdate).
    counted_quantity: Decimal | None = Field(
        None, ge=0, description='Counted quantity (0 or more)'
    )
    #: The shelf the row counts. On a surplus, the shelf the counter found
    #: the goods on — a record of them is opened there when none stands on
    #: it yet; left out, the shelf of the record named.
    location_id: UUID | None = None
    shelf_location: str | None = None
    notes: str | None = None
    assignee_id: UUID | None = None
    lot_id: UUID | None = None
    #: The batch the row counts, as its label reads — two rows of one product
    #: on one shelf are told apart by it.
    lot_name: str | None = Field(None, validation_alias=AliasPath('lot', 'name'))
    discrepancy_reason_code: StockTakeDiscrepancyCode | None = None
    discrepancy_reason: str | None = None
    recount_requested: bool = False
    counts: list[StockTakeCountRead] = Field(default_factory=list)

    @field_validator('system_quantity', 'counted_quantity', mode='before')
    @classmethod
    def to_decimal(cls, v: Any) -> Any:
        return decimal_from_int_float(v)


class StockTakeItemCreate(StockTakeItemBase):
    """Schema for creating stock take items."""

    item_id: UUID | None = None
    counted_quantity: Decimal | None = Field(
        None,
        ge=0,
        le=COUNTED_QUANTITY_MAX,
        description='Counted quantity (0 or more)',
    )


class StockTakeItemUpdate(DiscrepancyReasonFields):
    """Schema for updating stock take items."""

    counted_quantity: Decimal | None = Field(None, ge=0, le=COUNTED_QUANTITY_MAX)
    shelf_location: str | None = None
    notes: str | None = None
    assignee_id: UUID | None = None
    lot_id: UUID | None = None

    @field_validator('counted_quantity', mode='before')
    @classmethod
    def to_decimal(cls, v: Any) -> Any:
        return decimal_from_int_float(v)


class StockTakeItemResponse(StockTakeItemBase):
    """Response schema for stock take items."""

    id: UUID
    stock_take_id: UUID
    item_id: UUID | None = None
    #: Set when the row was counted away from where its record stands: the
    #: location the record is expected at (``storage_location_id`` is where
    #: it was found).
    expected_location_id: UUID | None = None
    assignee_id: UUID | None = None
    lot_id: UUID | None = None
    is_discrepancy: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StockTakeItemWithDetails(StockTakeItemResponse):
    """Stock take item schema with additional details."""

    item_name: str
    item_brand: str | None = None
    uom_symbol: str | None = Field(None, validation_alias=AliasPath('uom', 'symbol'))
    #: How finely this row may be counted — ``uom.rounding``, the same step the
    #: write checks with ``validate_quantity_precision_async``. The counting
    #: screen is a door where a person types a quantity, so it needs the rule
    #: before the save rather than a refusal after it; given only the symbol it
    #: invented one, and rounded every count to a whole number.
    uom_rounding: Decimal | None = Field(
        None, validation_alias=AliasPath('uom', 'rounding')
    )
    system_quantity: Decimal | None = None
    counted_quantity: Decimal | None = None
    difference: Decimal | None = None
    is_discrepancy: int = 0
    assignee_id: UUID | None = None
    lot_id: UUID | None = None
    discrepancy_reason_code: StockTakeDiscrepancyCode | None = None
    discrepancy_reason: str | None = None
    recount_requested: bool = False
    counts: list[StockTakeCountRead] = Field(default_factory=list)
    shelf_location: str | None = None
    notes: str | None = None


class StockTakeBase(BaseModel):
    """Base schema for stock takes."""

    name: str = Field(..., min_length=1, max_length=255, description='Stock take name')
    description: str | None = None
    notes: str | None = None


class StockTakeCreate(StockTakeBase):
    """Schema for creating stock takes."""

    location_id: UUID = Field(
        ..., description='ID of the storage location for stock take'
    )
    blind_mode: bool = Field(
        default=False, description='Hide system quantities during counting'
    )
    tolerance_percent: Decimal | None = Field(
        default=None,
        ge=0,
        le=100,
        description='Ignore discrepancies up to this percent',
    )
    require_full_count: bool = Field(
        default=True, description='Require all items counted before finalize'
    )


class StockTakeUpdate(BaseModel):
    """Schema for updating stock takes."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    notes: str | None = None
    status: StockTakeStatus | None = None


class StockTakeStatusUpdate(BaseModel):
    """Schema for changing stock take status."""

    status: StockTakeStatus


class StockTakeResponse(StockTakeBase):
    """Response schema for stock takes."""

    id: UUID
    user_id: UUID
    location_id: UUID
    status: StockTakeStatus
    blind_mode: bool = False
    tolerance_percent: Decimal | None = None
    require_full_count: bool = True
    started_at: datetime
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    items_count: int = 0
    counted_items_count: int = 0
    discrepancies_count: int = 0
    location_name: str | None = None
    #: Who started the count — the list is how people return to their own.
    started_by_name: str | None = None
    progress_percent: float | None = None

    model_config = ConfigDict(from_attributes=True)


class CountedLocation(BaseModel):
    """A location the count covers, named by its whole path ("Rack A / Shelf 1")."""

    id: UUID
    path: str


class LocationCountState(BaseModel):
    """Where a location stands as a thing to count.

    ``last_counted_at`` is when the latest closed count that counted it
    closed (empty: never counted); ``stock_take_id`` names the open count
    covering it, when one is under way.
    """

    location_id: UUID
    last_counted_at: datetime | None = None
    stock_take_id: UUID | None = None


class ClosedLocation(BaseModel):
    """A shelf the counter closed, and who closed it.

    ``empty`` says nothing was on it — no row, or every row counted as none —
    which is how a shelf found empty is confirmed as counted.
    """

    location_id: UUID | None = None
    path: str
    empty: bool
    closed_by_name: str | None = None
    closed_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ShelfClosed(ClosedLocation):
    """The answer to closing a shelf: how many rows it counted as none."""

    counted_as_zero: int


class StockTakeWithDetails(StockTakeResponse):
    """Stock take schema with additional details."""

    location_type_name: str | None = None
    #: The counted location and every one below it. A scanned shelf label is
    #: read against these, so the counting screen can tell a shelf of this
    #: count from one outside it, and say which shelf is being counted.
    counted_locations: list[CountedLocation] = []
    #: The shelves closed so far, so the screen can say a shelf is done.
    closed_locations: list[ClosedLocation] = []
    #: The counting screen reads these rows, and it is where a person types a
    #: quantity — so they carry the unit and its step, not just the numbers.
    items: list[StockTakeItemWithDetails] = []


class StockTakeComplete(BaseModel):
    """Schema for finalizing stock take."""

    apply_adjustments: bool = Field(
        default=True, description='Whether to apply inventory adjustments'
    )
    notes: str | None = None
    # if True, allow counted_quantity to exceed the growth cap.
    # Supervisors must explicitly opt in for large deltas; otherwise the
    # adjustment is silently clamped at MAX_GROWTH_FACTOR × system_quantity.
    # Someone with the approval permission saying, deliberately, that these
    # differences are real. Without it a count outside the organization's own
    # tolerance does not reach the stock.
    force_over_tolerance: bool = Field(
        default=False,
        description='Accept differences beyond the stock take tolerance',
    )
    force_over_cap: bool = Field(
        default=False,
        description='Allow counted quantities to exceed the growth cap',
    )


class StockTakeReport(BaseModel):
    """Schema for stock take report."""

    stock_take_id: UUID
    stock_take_name: str
    location_name: str
    status: StockTakeStatus
    started_at: datetime
    completed_at: datetime | None = None
    # Who began the count — the report lands in a binder as counting
    # evidence, and evidence has to be attributable to a person.
    started_by_name: str | None = None

    # Summary
    total_items: int
    counted_items: int
    # Rows whose stock the completion overwrites — the same number the
    # confirmation dialog names. Not "rows needing an explanation": that is
    # what the item-level ``is_discrepancy`` flag means.
    discrepancies: int
    progress_percent: float

    # Statistics
    # Counted equals the system, exactly — not "the tolerance flagged
    # nothing". A difference inside the tolerance is real and lands in
    # ``tolerated_differences``.
    perfect_matches: int = 0
    overstock: int = 0  # more than in system, beyond the tolerance
    understock: int = 0  # less than in system, beyond the tolerance
    # Differing rows the tolerance accepted without an explanation.
    tolerated_differences: int = 0
    not_counted: int = 0

    # Details
    all_items: list[StockTakeItemWithDetails] = []
    # The stock adjustment the differences posted as, in the documents
    # register; empty when nothing changed or that module is off.
    adjustment_document_id: UUID | None = None
    adjustment_document_number: str | None = None
    discrepancy_items: list[StockTakeItemWithDetails] = []
    tolerated_items: list[StockTakeItemWithDetails] = []
    # Which shelves were closed, by whom — an empty one is a result too.
    closed_locations: list[ClosedLocation] = []


class StockTakeItemCountUpdate(DiscrepancyReasonFields):
    """Schema for quick counting of a single item."""

    item_id: UUID | None = Field(
        None, description='StockTakeItem ID for bulk operations'
    )
    counted_quantity: Decimal = Field(
        ..., ge=0, le=COUNTED_QUANTITY_MAX, description='Counted quantity'
    )
    shelf_location: str | None = None
    notes: str | None = None
    assignee_id: UUID | None = None
    lot_id: UUID | None = None

    @field_validator('counted_quantity', mode='before')
    @classmethod
    def to_decimal(cls, v: Any) -> Any:
        return decimal_from_int_float(v)


class CycleCountScheduleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    frequency: CycleCountFrequency = CycleCountFrequency.MONTHLY
    scope: CycleCountScope = CycleCountScope.ALL
    scope_filter: dict[str, Any] | None = None
    sample_size: int | None = Field(None, ge=1)
    tolerance_percent: Decimal | None = Field(None, ge=0, le=100)
    location_id: UUID | None = None


class CycleCountScheduleUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    frequency: CycleCountFrequency | None = None
    scope: CycleCountScope | None = None
    scope_filter: dict[str, Any] | None = None
    sample_size: int | None = Field(None, ge=1)
    tolerance_percent: Decimal | None = Field(None, ge=0, le=100)
    is_active: bool | None = None


class CycleCountScheduleResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    frequency: CycleCountFrequency
    scope: CycleCountScope
    scope_filter: dict[str, Any] | None = None
    sample_size: int | None = None
    tolerance_percent: Decimal | None = None
    is_active: bool = True
    last_run_at: datetime | None = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
