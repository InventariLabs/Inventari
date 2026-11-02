from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.module_sdk import ScannedCode


class PackageCreate(BaseModel):
    #: Optional; usually known only once the box is full, see ``PackageUpdate``.
    weight_kg: Decimal | None = Field(
        default=None, gt=0, max_digits=10, decimal_places=3
    )


class PackageUpdate(BaseModel):
    #: A named null clears the weight; an absent key leaves it alone.
    weight_kg: Decimal | None = Field(
        default=None, gt=0, max_digits=10, decimal_places=3
    )


class PackageLineSet(BaseModel):
    #: How much of the document line this package holds from now on; zero
    #: takes the line out of the package.
    quantity: Decimal = Field(ge=0, max_digits=12, decimal_places=3)


class PackageScan(BaseModel):
    #: What the scanner read: a product barcode, a SKU or a printed label.
    code: ScannedCode = Field(min_length=1, max_length=128)
    #: How many of the product the scan puts in; one is the hand at the box.
    quantity: Decimal = Field(
        default=Decimal('1'), gt=0, max_digits=12, decimal_places=3
    )


class PackageLabelPrint(BaseModel):
    #: The printer; may be left out while the organization has one.
    agent_id: UUID | None = None
    #: The label's size in mm, as the download takes it; the bounds are the
    #: label export's.
    width_mm: float = Field(50.0, ge=10.0, le=300.0)
    height_mm: float = Field(24.0, ge=5.0, le=300.0)


class PackageLabelQueued(BaseModel):
    #: The print job the label went out as, listed in the print queue.
    job_id: UUID


class PackageLineOut(BaseModel):
    document_line_id: UUID
    line_number: int
    product_name: str | None = None
    uom_symbol: str | None = None
    quantity: Decimal


class PackageOut(BaseModel):
    id: UUID
    number: int
    #: The document number and the package number, as the slip's barcode and
    #: the package label print it.
    code: str
    weight_kg: Decimal | None = None
    created_at: datetime
    lines: list[PackageLineOut] = []


class PackingLineOut(BaseModel):
    """One document line, as far as packing has got with it."""

    document_line_id: UUID
    line_number: int
    product_name: str | None = None
    uom_symbol: str | None = None
    picked_quantity: Decimal
    packed_quantity: Decimal
    #: Picked and not yet in any package.
    remaining_quantity: Decimal


class PackingView(BaseModel):
    packages: list[PackageOut] = []
    lines: list[PackingLineOut] = []
    #: False once the document has left CONFIRMED: a completed dispatch's
    #: packages are a record.
    editable: bool = True
