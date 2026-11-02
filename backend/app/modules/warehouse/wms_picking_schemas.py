from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.module_sdk import ScannedCode

from .models import DocumentDiscrepancyCode


class WmsPickStartResponse(BaseModel):
    session_id: UUID
    document_number: str
    document_type: str
    lines: list['WmsPickLineOut']
    total_lines: int


class WmsPickStartRequest(BaseModel):
    #: The dispatches to pick in one session, in the order they were chosen.
    document_ids: list[UUID] = Field(min_length=1)


class WmsPickUncoveredLineOut(BaseModel):
    """One product a dispatch orders more of than its shelf can give."""

    product_name: str | None = None
    uom_symbol: str | None = None
    ordered: float
    #: What the shelf has free for this dispatch: its own reservation counts,
    #: other dispatches' reservations, quarantine and receiving stock do not.
    available: float


class WmsPickUncoveredDocumentOut(BaseModel):
    document_id: UUID
    document_number: str
    lines: list[WmsPickUncoveredLineOut]


class WmsPickCoverageOut(BaseModel):
    """The dispatches of a selection that stock cannot cover; empty when all are."""

    documents: list[WmsPickUncoveredDocumentOut]


class WmsPickLineOut(BaseModel):
    id: UUID
    document_line_id: UUID
    #: The document the line belongs to — a session may pick several.
    document_id: UUID | None = None
    document_number: str | None = None
    #: The group the line plans from (its shelf's anchor) and the batch it
    #: is to take.
    anchor_id: UUID | None = None
    lot_id: UUID | None = None
    #: The shelf the line is planned from; a shelf label is checked against it.
    location_id: UUID | None = None
    #: That shelf as the shared floor card reads it: the label's code large
    #: and the name under it. Empty when the shelf is gone or has none.
    location_code: str | None = None
    location_name: str | None = None
    pick_order: int
    status: str
    picked_quantity: float
    bin_location: str | None = None
    product_name: str | None = None
    lot_name: str | None = None
    #: The date of the stock the row plans to take, next to its batch.
    expiry_date: date | None = None
    expected_quantity: float
    uom_symbol: str | None = None

    model_config = ConfigDict(from_attributes=True)


class WmsPickScanRequest(BaseModel):
    barcode: ScannedCode | None = None
    item_id: UUID | None = None
    #: The batch code read off the label, when the picker read one.
    lot_name: str | None = None
    quantity: Decimal = Field(default=Decimal('1'), gt=0)


class WmsPickScanResponse(BaseModel):
    status: str
    line_id: UUID | None = None
    product_name: str | None = None
    picked_quantity: float = 0
    expected_quantity: float = 0
    uom_symbol: str | None = None
    bin_location: str | None = None
    #: The batch the line now stands for, and -- when the scan named another
    #: one than the row promised -- the one it promised.
    lot_name: str | None = None
    planned_lot_name: str | None = None
    #: The date beside the batch the line now stands for.
    expiry_date: date | None = None
    #: The shelf a shelf answer is about: the one confirmed, or the one the
    #: line waits at.
    shelf: str | None = None
    shelf_id: UUID | None = None
    message: str = ''
    session_complete: bool = False


class WmsShortPickRequest(BaseModel):
    line_id: UUID
    #: The line's final picked total, not the amount this call adds: the
    #: dialog prefills it with the picked quantity already scanned. Zero is
    #: an answer too: the summary records a skipped line as nothing picked,
    #: under the code the person chose for it.
    picked_quantity: Decimal = Field(ge=0)
    discrepancy_code: DocumentDiscrepancyCode | None = None
    discrepancy_reason: str | None = None
    #: True when that total is below the quantity already scanned and is
    #: meant to replace it — a count that supersedes a mistaken scan.
    replace_scans: bool = False


class WmsPickDocumentProgressOut(BaseModel):
    document_id: UUID
    document_number: str
    #: The document's own status (CONFIRMED until it is completed).
    document_status: str
    #: 'picking' while a line is pending, then 'all_picked' or 'short' —
    #: the document is then free to be completed on its own.
    status: str
    total_lines: int = 0
    picked_lines: int = 0
    pending_lines: int = 0


class WmsPickSessionOut(BaseModel):
    id: UUID
    document_id: UUID
    assigned_to: UUID | None = None
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    lines: list[WmsPickLineOut] = []
    total_lines: int = 0
    picked_lines: int = 0
    pending_lines: int = 0
    #: Every document of the session, in the order it was started with.
    documents: list[WmsPickDocumentProgressOut] = []
    #: Whether this session asks for the shelf's label before the product, and
    #: the shelf the last accepted label named.
    shelf_scan_required: bool = False
    confirmed_shelf_id: UUID | None = None
    #: The shelf of a transfer whose label ends the session: set once every
    #: line is answered, until the label is scanned.
    destination_shelf_id: UUID | None = None
    destination_shelf: str | None = None
    #: The destination's label code, for the card's large line.
    destination_shelf_code: str | None = None


class WmsUndoPickResponse(BaseModel):
    line_id: UUID
    product_name: str | None = None
    restored_quantity: float = 0


WmsPickStartResponse.model_rebuild()
