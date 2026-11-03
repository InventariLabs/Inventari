"""Import preview, product search, and quick-create Pydantic schemas.

Extracted from ``schemas.py`` — these are leaf schemas for file-import
endpoints and product-search helpers.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    field_validator,
)

ImportPreviewValue = str | int | float | None


class ImportPreviewRow(RootModel[dict[str, ImportPreviewValue]]):
    """A single row from the import preview.

    Columns are dynamic (driven by the source file's headers), so the row is
    represented as a flat dict mapping column name → primitive value. The model
    serialises back to the underlying dict, preserving the wire format the
    frontend already expects.
    """

    root: dict[str, ImportPreviewValue]


class ProductSearchResult(BaseModel):
    """Result from product search endpoint.

    Two searches share this shape. Without ``location_id`` the endpoint ranks
    product templates, and ``item_id`` is absent. With one it ranks the stock
    standing in that location, and every result names the item a dispatch line
    has to reference — ``product_template_id`` is then whatever the item is
    catalogued as, which may be nothing at all.
    """

    product_template_id: str | None = None
    item_id: str | None = None
    available_quantity: Decimal | None = None
    #: What makes two rows of one product on one shelf two rows: the records
    #: differ by their best-before or their serial, and the reader sees it.
    expiry_date: date | None = None
    serial_number: str | None = None
    #: When this record landed, per-record rows only — a merged row is a
    #: shelf total and names no single date.
    created_at: datetime | None = None
    #: The shelf a hit stands on. The search walks a location's subtree and a
    #: scrap searches the whole org, so the shelf is often the only thing
    #: telling same-named rows apart.
    location_name: str | None = None
    name: str
    sku: str | None = None
    barcode: str | None = None
    brand: str | None = None
    uom_id: str | None = None
    uom_symbol: str | None = None
    #: Catalogue search only: what the product last cost, from its newest
    #: stock record that carries a price. A purchase line starts from it.
    purchase_price: Decimal | None = None
    image_url: str | None = None
    is_stub: bool = False

    model_config = ConfigDict(from_attributes=True)


class DocumentImportAnalyzeResponse(BaseModel):
    headers: list[str]
    preview_rows: list[ImportPreviewRow]
    total_rows: int

    @field_validator('preview_rows', mode='before')
    @classmethod
    def _coerce_preview_rows(cls, value: Any) -> Any:
        """Accept the raw ``list[dict]`` shape from
        :func:`app.core.file_import.analyze_import_file` and wrap each row
        in :class:`ImportPreviewRow` for typing without changing the JSON
        payload (the ``RootModel`` round-trips back to a plain dict).
        """
        if value and isinstance(value, list) and isinstance(value[0], dict):
            return [ImportPreviewRow.model_validate(row) for row in value]
        return value


class DocumentImportLineResponse(BaseModel):
    id: str
    name: str | None = None
    brand: str | None = None
    barcode: str | None = None
    quantity: str
    product_template_id: str | None = None
    item_id: str | None = None
    uom_id: str | None = None
    unit_price: str | None = None
    tax_rate: str | None = None
    batch_number: str | None = None
    expiry_date: date | None = None


class DocumentImportNoStockRow(BaseModel):
    """A row whose line takes goods off a shelf that has none of it free."""

    row: int
    name: str | None = None


class DocumentImportErrorResponse(BaseModel):
    row: int
    error: str


class DocumentImportLinesResponse(BaseModel):
    imported: int
    matched: int
    unmatched: int
    stubs_created: int = 0
    # The server's count of refused rows; ``errors`` lists only the first few.
    failed: int = 0
    errors: list[DocumentImportErrorResponse]
    # Rows whose line found no stock record to take from; only a type that
    # takes goods off a shelf asks.
    no_stock: list[DocumentImportNoStockRow] = []
    lines: list[DocumentImportLineResponse]


class OpeningStockImportResponse(BaseModel):
    """What an opening-stock sheet became: one draft receipt, or nothing.

    ``document_id`` is None when no row could be read — no draft is left
    behind for the reader to find empty. The counts and the refused rows
    take the shape every spreadsheet import reports.
    """

    document_id: str | None
    number: str | None
    total: int
    imported: int
    failed: int
    errors: list[DocumentImportErrorResponse]
    matched: int
    unmatched: int
    stubs_created: int


@dataclass
class PartnerContext:
    """Lightweight partner context for document rendering."""

    name: str | None = None
    code: str | None = None
    tax_id: str | None = None
    address: str | None = None


class QuickCreateStub(BaseModel):
    """Request body for POST /product-search/quick-create."""

    name: str = Field(min_length=1, max_length=255)
    barcode: str | None = Field(default=None, max_length=50)
