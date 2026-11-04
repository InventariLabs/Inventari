from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.category import Category
from app.schemas.uom import UomInfo
from app.schemas.validators import (
    QUANTITY_MAX,
    decimal_from_int_float,
    quantize_quantity,
)

# === Shopping List Schemas ===


class ShoppingListBase(BaseModel):
    name: str | None = None


class ShoppingListCreate(ShoppingListBase):
    pass


class ShoppingListUpdate(BaseModel):
    name: str | None = None
    # explicit status transitions
    status: str | None = Field(
        default=None,
        pattern='^(active|completed|archived)$',
    )


class ShoppingList(ShoppingListBase):
    id: UUID
    organization_id: UUID
    created_by: UUID
    # state machine + timestamps
    status: str = 'active'
    completed_at: datetime | None = None
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ShoppingListWithItems(ShoppingList):
    items: list['ShoppingListItem'] = []


# === Shopping List Item Schemas ===


class ShoppingListItemBase(BaseModel):
    name: str
    quantity: Decimal = Field(default=Decimal(1), gt=0, le=QUANTITY_MAX)

    @field_validator('quantity', mode='before')
    @classmethod
    def _to_decimal(cls, v: Any) -> Any:
        return decimal_from_int_float(v)

    @field_validator('quantity', mode='after')
    @classmethod
    def _to_store_precision(cls, v: Decimal) -> Decimal:
        # The column holds three places and would round silently, so the
        # number the client sent and the number the store keeps could
        # disagree. Cut it here, where the answer can say so. The column's
        # ceiling rides the field's ``le=`` — a twelve-digit quantity dies
        # as a 422 sentence instead of an asyncpg overflow.
        quantized: Decimal = quantize_quantity(v)
        return quantized

    uom_id: UUID | None = None
    notes: str | None = None
    # Structured note parts for service-composed lines (meal-plan shopping);
    # the interface re-renders them in the reader's language. `notes` is the
    # composed-at-generation fallback.
    note_data: dict[str, Any] | None = None
    estimated_price: Decimal | None = None
    priority: int = Field(default=0, ge=0, le=2)
    source: str = 'manual'


class ShoppingListItemCreate(ShoppingListItemBase):
    item_id: UUID | None = None
    category_id: UUID | None = None
    template_id: UUID | None = None


class ShoppingListItemUpdate(BaseModel):
    name: str | None = None
    quantity: Decimal | None = Field(default=None, gt=0, le=QUANTITY_MAX)

    @field_validator('quantity', mode='before')
    @classmethod
    def _to_decimal(cls, v: Any) -> Any:
        return decimal_from_int_float(v)

    @field_validator('quantity', mode='after')
    @classmethod
    def _to_store_precision(cls, v: Decimal | None) -> Decimal | None:
        quantized: Decimal | None = quantize_quantity(v)
        return quantized

    uom_id: UUID | None = None
    notes: str | None = None
    estimated_price: Decimal | None = None
    priority: int | None = Field(default=None, ge=0, le=2)


class ShoppingListItem(ShoppingListItemBase):
    id: UUID
    shopping_list_id: UUID
    item_id: UUID | None = None
    category_id: UUID | None = None
    template_id: UUID | None = None
    is_purchased: bool
    purchased_at: datetime | None = None
    purchased_by: UUID | None = None
    created_at: datetime
    updated_at: datetime
    category: Category | None = None
    # expose the joined Uom so the FE can render its symbol
    # (e.g. "200 g" instead of falling back to "200 pcs").
    uom: UomInfo | None = None

    model_config = ConfigDict(from_attributes=True)


# === Shopping Suggestion Schemas ===


class ShoppingSuggestionSchema(BaseModel):
    """Schema for a single shopping suggestion."""

    item_id: UUID | None = None
    #: The product template a proposal about a product is about; the low-stock
    #: and consumption sources fill it and leave ``item_id`` null, and a
    #: template's name is not unique — the row's identity, not its label.
    template_id: UUID | None = None
    category_id: UUID | None = None
    name: str
    quantity: Decimal = Decimal(1)
    uom_symbol: str | None = None
    #: The unit the symbol names, so a row added from the proposal keeps it.
    uom_id: UUID | None = None
    source: str
    priority: int = 0
    estimated_price: Decimal | None = None
    notes: str | None = None


class ShoppingSuggestionResponse(BaseModel):
    """Response for suggestions generation."""

    message: str
    added: int
    suggestions: list[ShoppingSuggestionSchema]


class ShoppingSuggestionPreview(BaseModel):
    """What the app would propose buying — and nothing it has done.

    Deliberately not ``ShoppingSuggestionResponse``: that one carries
    ``added``, and a preview adds nothing. Reporting a zero there would be
    the same shape of untruth as the list this preview exists to stop
    creating.
    """

    suggestions: list[ShoppingSuggestionSchema]


class AddFromRecipesRequest(BaseModel):
    recipe_ids: list[UUID] = Field(..., min_length=1)
    servings: int = Field(default=1, ge=1)


class ConvertToPORequest(BaseModel):
    """Request body for shopping list → purchase order conversion."""

    supplier_id: UUID | None = None


class ConvertToPOResponse(BaseModel):
    """Result of shopping list → purchase order conversion."""

    po_id: UUID
    po_number: str
    converted_count: int
    skipped_count: int
    skipped_items: list[str]


# Update forward references
ShoppingListWithItems.model_rebuild()
