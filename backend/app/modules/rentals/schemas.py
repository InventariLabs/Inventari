"""Request and response shapes of the rentals module.

A booking is created from a window and lines; the sheet checks the lines
before it writes (`BookingCheckRequest` answers the same conflicts a create
would), and every refusal that names what is in the way does so as data
(`ConflictDetail`), not only as a sentence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.module_sdk import ServiceRejectionError

BookingStatus = Literal['RESERVED', 'PICKED_UP', 'RETURNED', 'CANCELLED']
Condition = Literal['GOOD', 'DAMAGED', 'NEEDS_REPAIR']
BlockSource = Literal['MANUAL', 'SERVICE']
BarKind = Literal['reserved', 'out', 'late', 'returned', 'block', 'buffer']
BorrowerKind = Literal['partner', 'user', 'external']


class BookingLineIn(BaseModel):
    """One thing a booking asks for: an asset, a model and a count, or a kit."""

    item_id: UUID | None = None
    model: str | None = Field(default=None, max_length=255)
    kit_id: UUID | None = None
    quantity: int = Field(default=1, ge=1, le=999)

    @model_validator(mode='after')
    def _one_kind(self) -> BookingLineIn:
        named = sum(
            value is not None for value in (self.item_id, self.model, self.kit_id)
        )
        if named != 1:
            raise ServiceRejectionError('rental_line_names_one_kind')
        if self.item_id is not None and self.quantity != 1:
            raise ServiceRejectionError('rental_asset_line_quantity')
        if self.kit_id is not None and self.quantity != 1:
            raise ServiceRejectionError('rental_kit_line_quantity')
        if self.model is not None:
            self.model = self.model.strip()
            if not self.model:
                raise ServiceRejectionError('rental_model_line_needs_model')
        return self


class BookingCreate(BaseModel):
    borrower_partner_id: UUID | None = None
    borrower_user_id: UUID | None = None
    borrower_name: str | None = Field(default=None, max_length=255)
    borrower_email: str | None = Field(default=None, max_length=255)

    starts_at: datetime
    ends_at: datetime
    note: str | None = Field(default=None, max_length=2000)
    lines: list[BookingLineIn] = Field(..., min_length=1)

    @model_validator(mode='after')
    def _one_borrower_and_a_window(self) -> BookingCreate:
        kinds = sum(
            value is not None
            for value in (
                self.borrower_partner_id,
                self.borrower_user_id,
                self.borrower_name,
            )
        )
        if kinds != 1:
            raise ServiceRejectionError('rental_booking_needs_one_borrower')
        if self.borrower_name is not None and not self.borrower_name.strip():
            raise ServiceRejectionError('rental_borrower_needs_name')
        if self.ends_at <= self.starts_at:
            raise ServiceRejectionError('rental_window_order')
        # A unit named twice reads as free to both lines, and no hand-out can
        # scan it twice.
        units = [line.item_id for line in self.lines if line.item_id is not None]
        if len(set(units)) != len(units):
            raise ServiceRejectionError('rental_unit_on_two_lines')
        return self


class ConflictDetail(BaseModel):
    """What stands in the way of a line, said unit by unit."""

    item_id: UUID | None = None
    item_name: str | None = None
    item_serial_number: str | None = None
    kind: str
    label: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    booking_id: UUID | None = None
    reason: str | None = None
    # When the thing really holds the unit: a hand-out made before the
    # window, or a loan left open past its due date (held_until is empty
    # then, because the return is what ends the hold).
    held_from: datetime | None = None
    held_until: datetime | None = None


class WindowSuggestion(BaseModel):
    starts_at: datetime
    ends_at: datetime


class LineCheck(BaseModel):
    index: int
    ok: bool
    label: str
    requested: int
    available: int
    conflicts: list[ConflictDetail] = Field(default_factory=list)
    # The two ways out the sheet offers: fewer units, or the nearest window
    # of the same length that fits.
    max_quantity: int = 0
    nearest_window: WindowSuggestion | None = None


class BookingCheckRequest(BaseModel):
    # The same body as a create, so the sheet sends one shape both times.
    starts_at: datetime
    ends_at: datetime
    lines: list[BookingLineIn] = Field(..., min_length=1)
    booking_id: UUID | None = None


class BookingCheckResponse(BaseModel):
    ok: bool
    lines: list[LineCheck]


class UnitSchema(BaseModel):
    id: UUID
    item_id: UUID
    item_name: str
    model: str | None = None
    serial_number: str | None = None
    asset_tag: str | None = None
    assignment_id: UUID | None = None
    condition: Condition | None = None
    note: str | None = None
    returned_at: datetime | None = None
    is_out: bool = True


class LineSchema(BaseModel):
    id: UUID
    item_id: UUID | None = None
    item_name: str | None = None
    model: str | None = None
    quantity: int
    resolved_count: int
    kit_id: UUID | None = None
    kit_name: str | None = None
    units: list[UnitSchema] = Field(default_factory=list)


class BookingSchema(BaseModel):
    id: UUID
    status: BookingStatus
    # Derived, never stored: the window is past and the booking is out.
    is_late: bool
    late_days: int
    borrower_kind: BorrowerKind
    borrower_partner_id: UUID | None = None
    borrower_user_id: UUID | None = None
    borrower_name: str
    borrower_email: str | None = None
    starts_at: datetime
    ends_at: datetime
    note: str | None = None
    lines: list[LineSchema]
    created_at: datetime
    created_by_name: str | None = None
    can_pickup: bool
    can_return: bool
    can_cancel: bool
    can_extend: bool
    # A partly returned booking keeps its status and its late flag while any
    # unit is still out; these counts make the state legible.
    returned_count: int = 0
    outstanding_count: int = 0
    # History for the detail screen: reserved, handed out, returned.
    handed_out_at: datetime | None = None
    returned_at: datetime | None = None


class BookingListRow(BaseModel):
    id: UUID
    status: BookingStatus
    is_late: bool
    late_days: int
    borrower_name: str
    borrower_kind: BorrowerKind
    borrower_partner_id: UUID | None = None
    starts_at: datetime
    ends_at: datetime
    units_count: int
    summary: str


class PickupRequest(BaseModel):
    # Each scanned or chosen asset, in scan order. A model line takes the
    # units that match its model until its count is met.
    item_ids: list[UUID] = Field(default_factory=list)


class ReturnUnitIn(BaseModel):
    unit_id: UUID
    condition: Condition
    note: str | None = Field(default=None, max_length=2000)
    service_reason: str | None = Field(default=None, max_length=2000)
    service_until: datetime | None = None

    @model_validator(mode='after')
    def _service_has_a_reason_and_a_date(self) -> ReturnUnitIn:
        if self.condition != 'NEEDS_REPAIR':
            return self
        if not (self.service_reason or '').strip() or self.service_until is None:
            raise ServiceRejectionError('rental_service_needs_reason_and_date')
        # The block opens at the return, so an end before it would store an
        # inverted window and leave the unit bookable at once.
        until = self.service_until
        if until.tzinfo is None:
            until = until.replace(tzinfo=UTC)
        if until <= datetime.now(UTC):
            raise ServiceRejectionError('rental_service_until_in_past')
        return self


class MoveIn(BaseModel):
    """Move a later booking of the returned unit to another unit of its model."""

    line_id: UUID
    from_item_id: UUID
    to_item_id: UUID


class ReturnRequest(BaseModel):
    units: list[ReturnUnitIn] = Field(..., min_length=1)
    moves: list[MoveIn] = Field(default_factory=list)


class ExtendRequest(BaseModel):
    ends_at: datetime


class BlockCreate(BaseModel):
    item_id: UUID
    starts_at: datetime
    ends_at: datetime
    reason: str = Field(..., min_length=1, max_length=2000)

    @model_validator(mode='after')
    def _ends_after_start(self) -> BlockCreate:
        if self.ends_at <= self.starts_at:
            raise ServiceRejectionError('rental_block_window_order')
        return self


class BlockUpdate(BaseModel):
    starts_at: datetime
    ends_at: datetime
    reason: str = Field(..., min_length=1, max_length=2000)

    @model_validator(mode='after')
    def _ends_after_start(self) -> BlockUpdate:
        if self.ends_at <= self.starts_at:
            raise ServiceRejectionError('rental_block_window_order')
        return self


class BlockSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_id: UUID
    item_name: str
    item_serial_number: str | None = None
    model: str | None = None
    starts_at: datetime
    ends_at: datetime
    reason: str
    source: BlockSource
    booking_id: UUID | None = None
    borrower_name: str | None = None
    created_at: datetime


class BufferRuleIn(BaseModel):
    model: str | None = Field(default=None, max_length=255)
    category_id: UUID | None = None
    hours_before: int = Field(default=0, ge=0, le=336)
    hours_after: int = Field(default=0, ge=0, le=336)

    @model_validator(mode='after')
    def _one_target(self) -> BufferRuleIn:
        if (self.model is None) == (self.category_id is None):
            raise ServiceRejectionError('rental_buffer_needs_one_target')
        if self.model is not None:
            self.model = self.model.strip()
            if not self.model:
                raise ServiceRejectionError('rental_buffer_needs_model')
        return self


class CategoryOption(BaseModel):
    id: UUID
    #: The catalogue code: the display name lives in the shared `categories`
    #: catalogue under it, and `name` is the seed's fallback.
    code: str | None = None
    name: str


class BufferRuleSchema(BaseModel):
    id: UUID
    model: str | None = None
    category_id: UUID | None = None
    category_code: str | None = None
    category_name: str | None = None
    hours_before: int
    hours_after: int


class AssetOption(BaseModel):
    id: UUID
    name: str
    model: str | None = None
    category_id: UUID | None = None
    category_code: str | None = None
    category_name: str | None = None
    status: str
    serial_number: str | None = None
    asset_tag: str | None = None
    barcode: str | None = None


class ModelOption(BaseModel):
    model: str
    total_units: int


class BusyInterval(BaseModel):
    kind: BarKind
    starts_at: datetime
    ends_at: datetime
    label: str
    reason: str | None = None
    booking_id: UUID | None = None


class RentalAvailabilityResponse(BaseModel):
    item_id: UUID | None = None
    model: str | None = None
    starts_at: datetime
    ends_at: datetime
    total_units: int
    free_units: int
    busy: list[BusyInterval] = Field(default_factory=list)


class NearestWindowResponse(BaseModel):
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class TodayItem(BaseModel):
    booking_id: UUID
    borrower_name: str
    what: str
    at: datetime
    until: datetime | None = None
    late_days: int = 0


class TodayResponse(BaseModel):
    date: datetime
    pickups_count: int
    returns_count: int
    late_count: int
    expired_count: int = 0
    late: list[TodayItem]
    pickups: list[TodayItem]
    returns: list[TodayItem]
    expired: list[TodayItem] = Field(default_factory=list)
    in_service: list[BlockSchema]


class CalendarBar(BaseModel):
    kind: BarKind
    label: str
    starts_at: datetime
    ends_at: datetime
    booking_id: UUID | None = None


class CalendarUnit(BaseModel):
    item_id: UUID
    name: str
    serial_number: str | None = None
    asset_tag: str | None = None
    status: str
    bars: list[CalendarBar] = Field(default_factory=list)


class CalendarAnyUnit(BaseModel):
    booking_id: UUID
    borrower_name: str
    quantity: int
    starts_at: datetime
    ends_at: datetime
    status: str


class CalendarGroup(BaseModel):
    model: str | None = None
    total_units: int
    service_units: int
    units: list[CalendarUnit]
    any_unit: list[CalendarAnyUnit]


class CalendarResponse(BaseModel):
    starts_at: datetime
    ends_at: datetime
    groups: list[CalendarGroup]


class KitMemberIn(BaseModel):
    """One member of a kit: a specific asset, or a model and a count."""

    item_id: UUID | None = None
    model: str | None = Field(default=None, max_length=255)
    quantity: int = Field(default=1, ge=1, le=999)

    @model_validator(mode='after')
    def _one_kind(self) -> KitMemberIn:
        if (self.item_id is None) == (self.model is None):
            raise ServiceRejectionError('rental_kit_member_names_one_kind')
        if self.item_id is not None and self.quantity != 1:
            raise ServiceRejectionError('rental_asset_line_quantity')
        if self.model is not None:
            self.model = self.model.strip()
            if not self.model:
                raise ServiceRejectionError('rental_model_line_needs_model')
        return self


class KitCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    note: str | None = Field(default=None, max_length=2000)
    members: list[KitMemberIn] = Field(..., min_length=1)


class KitUpdate(KitCreate):
    pass


class KitMemberSchema(BaseModel):
    id: UUID
    item_id: UUID | None = None
    item_name: str | None = None
    model: str | None = None
    quantity: int


class KitSchema(BaseModel):
    id: UUID
    name: str
    code: str
    note: str | None = None
    members: list[KitMemberSchema] = Field(default_factory=list)
    created_at: datetime


class KitListRow(BaseModel):
    id: UUID
    name: str
    code: str
    member_count: int
    summary: str
