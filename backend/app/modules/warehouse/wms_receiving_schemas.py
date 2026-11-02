from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.module_sdk import ScannedCode

from .models import DocumentDiscrepancyCode

#: What a receiving line can be, in the words receiving uses. Stored lines
#: speak the picking vocabulary — same table, same machinery — and the
#: router translates at this boundary. Spelling the set out here is what
#: makes the client's own union checkable against the schema instead of
#: agreeing with it by hand.
ReceiveLineStatus = Literal['pending', 'received', 'short', 'skipped']


class WmsReceiveLineOut(BaseModel):
    id: UUID
    document_line_id: UUID
    pick_order: int
    status: ReceiveLineStatus
    received_quantity: float
    product_name: str | None = None
    lot_name: str | None = None
    expected_quantity: float
    uom_symbol: str | None = None
    #: Of what has been received, how much is held back — damaged or on a
    #: quality hold. The dialog that records a short receive shows it so a
    #: reloaded session answers the same question the same way.
    held_quantity: float | None = None
    #: Why the line differs from what was expected — for a held quantity, the
    #: reason it is held (damage or a quality hold), so the row can name it
    #: beside the figure.
    discrepancy_code: DocumentDiscrepancyCode | None = None
    #: Whether the line receives goods an order asked for. ``expected_quantity``
    #: is then what the order still owes; on a line with no order behind it
    #: it is the count somebody wrote down, and the card must not call it
    #: ordered.
    from_order: bool = False

    #: Where this line's goods are going, and who decided — the same fields a
    #: document line carries, filled by the same planner. The office screen
    #: had them and the floor screen did not, which put the decision out of
    #: reach of the only person standing in front of the shelf.
    #:
    #: Named exactly as on ``DocumentLine`` so one reader serves both screens:
    #: the frontend's ``plannedPutaway`` is structural, and a second set of
    #: names here would have bought a second copy of the sentence.
    planned_location_id: UUID | None = None
    planned_location_name: str | None = None
    #: What a worker scans to name the planned shelf: its own code or the
    #: code of a pool label printed for it, empty for a place with neither.
    #: The session asks for the shelf only where this is set, so the line's
    #: scan hint follows it.
    planned_location_code: str | None = None
    planned_source: str | None = None
    planned_rule_match_key: str | None = None
    planned_rule_match_name: str | None = None
    planned_rule_warning: str | None = None
    planned_over_capacity: bool | None = None
    planned_capacity_used: Decimal | None = None
    planned_capacity_max: Decimal | None = None
    planned_shelf_fill: int | None = None
    #: The shelf somebody named on this line, as opposed to the one the plan
    #: arrived at. The picker needs the difference: empty means "follow the
    #: plan", and inferring that from the plan's own source would make the
    #: control lie the moment a rule happens to agree with the override.
    target_location_id: UUID | None = None
    #: The shelf the phone's card offers when the plan is the document's own
    #: target and that target has shelves below it — a whole warehouse tells
    #: the person holding the box nothing. ``stock``: the product already
    #: lies there; ``zone``: the shelf last received onto below that target.
    #: Empty when the plan names a shelf, or when there is nothing to offer
    #: and the card asks the worker to choose one.
    suggested_location_id: UUID | None = None
    suggested_location_name: str | None = None
    suggested_source: Literal['stock', 'zone'] | None = None

    model_config = ConfigDict(from_attributes=True)


class WmsReceiveScanRequest(BaseModel):
    barcode: ScannedCode | None = None
    quantity: Decimal = Field(default=Decimal('1'), gt=0)
    #: Only say which line the code matches; count nothing. The phone scans
    #: the product to bring its card up and the worker confirms the count on
    #: the card — a scan that counted would receive a one-unit line, close
    #: the session and leave the card with nothing to confirm.
    identify: bool = False
    #: What the first scan of a dated product answers the
    #: ``needs_lot_expiry`` question with; they ride on the same scan, sent
    #: again, and land on the document line the delivery is received from.
    batch_number: str | None = Field(default=None, max_length=100)
    expiry_date: date | None = None


class WmsReceiveScanResponse(BaseModel):
    status: str
    line_id: UUID | None = None
    product_name: str | None = None
    received_quantity: float = 0
    expected_quantity: float = 0
    uom_symbol: str | None = None
    #: The shelf a shelf answer is about: the one confirmed, or the one the
    #: line waits at.
    shelf: str | None = None
    shelf_id: UUID | None = None
    message: str = ''
    session_complete: bool = False


class WmsReceiveShortRequest(BaseModel):
    line_id: UUID
    #: The line's final received total, not the amount this call adds: the
    #: dialog prefills it with the received quantity already scanned. Zero
    #: is a recorded answer — nothing of this line arrived — so the floor
    #: is the sign, not the figure.
    received_quantity: Decimal = Field(ge=0)
    discrepancy_code: DocumentDiscrepancyCode | None = None
    discrepancy_reason: str | None = None
    #: How much of *received_quantity* is received but not usable — damaged
    #: or on a quality hold. Omitted or zero says the whole count is
    #: ordinary stock; the code then only explains the gap, which is what a
    #: delivery refused at the door means.
    held_quantity: Decimal | None = Field(default=None, ge=0)
    #: True when that total is below the quantity already scanned and is
    #: meant to replace it — a count that supersedes a mistaken scan.
    replace_scans: bool = False
    #: What a dated product's ``needs_lot_expiry`` answer is sent again with,
    #: as on the scan: the lot is optional, the expiry lands on the document
    #: line the delivery is received from.
    batch_number: str | None = Field(default=None, max_length=100)
    expiry_date: date | None = None


class WmsReceiveSessionOut(BaseModel):
    id: UUID
    document_id: UUID
    assigned_to: UUID | None = None
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    lines: list[WmsReceiveLineOut] = []
    total_lines: int = 0
    received_lines: int = 0
    pending_lines: int = 0
    #: Whether this session asks for the shelf's label before the product, and
    #: the shelf the last accepted label named.
    shelf_scan_required: bool = False
    confirmed_shelf_id: UUID | None = None


class WmsReceiveUndoResponse(BaseModel):
    line_id: UUID
    product_name: str | None = None
    restored_quantity: float = 0
