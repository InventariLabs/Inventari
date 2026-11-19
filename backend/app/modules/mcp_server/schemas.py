"""The JSON shapes the MCP tools and resources answer with.

The SDK derives each tool's output schema from these models, so the fields and
their descriptions are part of the agent-facing contract. Quantities are
decimal strings in JSON (Pydantic's decimal encoding) — exact, unlike a float.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.contracts import ItemDTO, StockLotDetailDTO, StorageDTO


class ItemView(BaseModel):
    """One stock record as an agent reads it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description='The record id; pass it to get_item.')
    name: str
    brand: str | None = None
    barcode: str | None = None
    serial_number: str | None = None
    quantity: Decimal | None = Field(
        None, description='Quantity on this record, in the unit of uom_symbol.'
    )
    uom_symbol: str | None = None
    shelf_id: UUID = Field(description='The location the record stands on.')
    shelf_name: str | None = None
    shelf_location: str | None = Field(
        None, description='The shelf path, when the Core resolves one.'
    )
    template_id: UUID | None = Field(
        None, description='The product template this record belongs to.'
    )
    template_name: str | None = None
    category_id: UUID | None = None
    lot_id: UUID | None = Field(None, description='The batch this stock is in.')
    expiry_date: date | None = None
    meta_data: dict[str, object] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_dto(cls, item: ItemDTO) -> ItemView:
        return cls(
            id=item.id,
            name=item.name,
            brand=item.brand,
            barcode=item.barcode or item.template_barcode,
            serial_number=item.serial_number,
            quantity=item.quantity,
            uom_symbol=item.uom_symbol,
            shelf_id=item.location_id,
            shelf_name=item.location_name,
            shelf_location=item.shelf_location,
            template_id=item.template_id,
            template_name=item.template_name,
            category_id=item.category_id,
            lot_id=item.lot_id,
            expiry_date=item.expiry_date,
            meta_data=item.meta_data,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )


class StockRow(ItemView):
    """A row of stock; interchangeable records are one row with a total."""

    offered_quantity: Decimal = Field(
        description='What this row can offer: the record quantity, or the group total.'
    )
    merged: bool = Field(
        description='True when several interchangeable records were summed into this row.'
    )


class SearchItemsResult(BaseModel):
    query: str = Field(description='The search text as received.')
    stock: list[StockRow] = Field(
        default_factory=list,
        description='Stock on hand that matches, newest first.',
    )
    records: list[ItemView] = Field(
        default_factory=list,
        description=(
            'Catalogue records when no stock row matched — a product with no '
            'stock, or a barcode looked up directly.'
        ),
    )


class ItemDetail(BaseModel):
    item: ItemView
    lot: LotView | None = Field(
        None, description='The batch, when the record names one.'
    )


class CorrectStockResult(BaseModel):
    """What one correction did: the record, and what it was posted as."""

    item: ItemView
    previous_quantity: Decimal | None = Field(
        None, description='The quantity the record held before the correction.'
    )
    quantity: Decimal = Field(description='The quantity the record holds now.')
    reference: UUID = Field(
        description=(
            'The correction id; the movement and the register document carry '
            'it as their reference.'
        ),
    )
    register_document_id: UUID | None = Field(
        None,
        description=(
            'The adjustment document the register kept, when the Warehouse '
            'module is on and the quantity changed; None otherwise.'
        ),
    )
    register_document_number: str | None = Field(
        None, description='The adjustment document number, when one was written.'
    )


class LocationNode(BaseModel):
    """One location, with its children when a tree was asked for."""

    id: UUID
    name: str
    parent_id: UUID | None = Field(
        None, description='The parent location; None for a top-level location.'
    )
    usage: str = Field(description='e.g. internal, customer, production')
    short_code: str | None = None
    behavior_mode: str | None = Field(
        None, description='Tracking mode: STOCK, EXPIRY or FREEZING.'
    )
    context_tag: str | None = None
    description: str | None = None
    children: list[LocationNode] = Field(default_factory=list)

    @classmethod
    def from_dto(cls, location: StorageDTO) -> LocationNode:
        return cls(
            id=location.id,
            name=location.name,
            parent_id=location.parent_id,
            usage=location.usage,
            short_code=location.short_code,
            behavior_mode=location.behavior_mode,
            context_tag=location.context_tag,
            description=location.description,
        )


class LocationsResult(BaseModel):
    locations: list[LocationNode] = Field(
        default_factory=list, description='The locations, flat, in name order.'
    )
    has_more: bool = Field(
        False, description='True when the page hit the requested limit.'
    )


class LocationTreeResult(BaseModel):
    roots: list[LocationNode] = Field(
        default_factory=list, description='Top-level locations with their subtrees.'
    )
    ancestors: list[LocationNode] = Field(
        default_factory=list,
        description='When a subtree was asked for: its ancestors, nearest first.',
    )


class StockLevelRow(BaseModel):
    """One quant: a product in a batch, on a shelf, for one owner."""

    product_template_id: UUID
    location_id: UUID
    lot_id: UUID | None = None
    owner_id: UUID | None = None
    quantity: Decimal
    reserved_quantity: Decimal
    available_quantity: Decimal


class ShelfTotal(BaseModel):
    location_id: UUID
    product_template_id: UUID
    quantity: Decimal = Field(description='Every batch and owner on the shelf, summed.')


class StockLevelsResult(BaseModel):
    rows: list[StockLevelRow] = Field(
        default_factory=list,
        description='Quant rows when the call was narrowed by product or shelf.',
    )
    shelf_totals: list[ShelfTotal] = Field(
        default_factory=list,
        description=(
            'Per-product totals for one whole shelf, when the call named a '
            'shelf and no product.'
        ),
    )
    total: int = Field(
        0,
        description=(
            'How many rows match the filters, before limit cut the answer. '
            'Equal to rows when nothing was cut.'
        ),
    )
    has_more: bool = Field(
        False,
        description='True when limit cut the answer; ask again with a larger limit.',
    )


class LotLocationView(BaseModel):
    location_id: UUID
    location_name: str | None = None
    quantity: Decimal
    reserved_quantity: Decimal


class LotStatusEventView(BaseModel):
    status: str
    reason: str | None = None
    at: datetime | None = None
    by_name: str | None = None


class LotView(BaseModel):
    """A batch with its dates, state and what stands where."""

    id: UUID
    product_template_id: UUID
    product_name: str | None = None
    name: str
    status: str = Field(description='active, quarantined, held, expired or recalled')
    status_reason: str | None = None
    expiry_date: date | None = None
    production_date: date | None = None
    use_by_date: date | None = Field(
        None, description='Best-before; FEFO reads use_by_date before expiry_date.'
    )
    on_hand: Decimal = Field(
        Decimal('0'), description='Total pieces of this batch still on shelves.'
    )
    uom_symbol: str | None = None
    locations: list[LotLocationView] = Field(default_factory=list)
    status_history: list[LotStatusEventView] = Field(default_factory=list)
    meta_data: dict[str, object] | None = None

    @classmethod
    def from_dto(cls, lot: StockLotDetailDTO) -> LotView:
        return cls(
            id=lot.id,
            product_template_id=lot.product_template_id,
            product_name=lot.product_name,
            name=lot.name,
            status=lot.status,
            status_reason=lot.status_reason,
            expiry_date=lot.expiry_date,
            production_date=lot.production_date,
            use_by_date=lot.use_by_date,
            on_hand=lot.on_hand,
            uom_symbol=lot.uom_symbol,
            locations=[
                LotLocationView(
                    location_id=location.location_id,
                    location_name=location.location_name,
                    quantity=location.quantity,
                    reserved_quantity=location.reserved_quantity,
                )
                for location in lot.locations
            ],
            status_history=[
                LotStatusEventView(
                    status=event.status,
                    reason=event.reason,
                    at=event.at,
                    by_name=event.by_name,
                )
                for event in lot.status_history
            ],
            meta_data=lot.meta_data,
        )


class LotsResult(BaseModel):
    detail: LotView | None = Field(None, description='The batch when lot_id was given.')
    items: list[LotView] = Field(
        default_factory=list,
        description='The page of batches when no lot_id was given.',
    )
    total: int = Field(0, description='How many batches match the filters.')


class ExpiringItem(BaseModel):
    item_id: UUID
    name: str
    quantity: Decimal | None = None
    uom_symbol: str | None = None
    shelf_id: UUID | None = None
    shelf_name: str | None = None
    expiry_date: date | None = Field(
        None,
        description=(
            'The date the record is judged by: the batch expiry, or the '
            "opened package's use-by when that is earlier."
        ),
    )
    days_left: int | None = Field(
        None,
        description=(
            'Calendar days from today to expiry_date; 0 is today, negative is overdue.'
        ),
    )
    lot_id: UUID | None = None


class ExpiryBucketView(BaseModel):
    period: str = Field(description='e.g. Today, This week, This month')
    count: int


class ExpiringSoonResult(BaseModel):
    days: int
    today: date
    items: list[ExpiringItem] = Field(default_factory=list)
    forecast: list[ExpiryBucketView] = Field(
        default_factory=list,
        description='The organization-wide six-bucket expiry forecast.',
    )
    shelf_id: UUID | None = None
    shelf_count: int | None = Field(
        None,
        description='How many items expire in the window on the named shelf.',
    )


ItemDetail.model_rebuild()
LocationNode.model_rebuild()
