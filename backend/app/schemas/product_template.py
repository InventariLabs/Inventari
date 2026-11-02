from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.validators import RemovalStrategy, normalize_barcode, normalize_sku


class ProductTemplateLookupResult(BaseModel):
    product_template_id: UUID | None = None
    name: str
    brand: str | None
    barcode: str | None
    sku: str | None = None
    uom_id: UUID | None
    uom_symbol: str | None
    #: The unit's own name (`kilogram`), so a form can show which unit the
    #: record will land with without resolving a second catalogue itself.
    uom_name: str | None = None
    image_url: str | None
    description: str | None
    weight_value: float | None
    source: Literal['local', 'off'] = 'local'


class ProductTemplateStockResponse(BaseModel):
    """How much of one product the organization has on its shelves.

    The number a threshold is measured against, so the screen that sets
    one can name it. That screen used to show the quantity of the single
    record the reader had opened, and offered to copy it into a field
    governing the product as a whole.
    """

    product_template_id: UUID
    #: Summed over internal locations only — stock in a customer or
    #: production location has left the shelf, which is the same rule the
    #: dashboard tile and the purchasing engine read.
    total_quantity: Decimal
    uom_symbol: str | None = None


class ProductTemplateCountResponse(BaseModel):
    """Answer to "is the product catalog empty"."""

    count: int


class GeneratedProductCode(BaseModel):
    """An internal EAN-13 for a product without a manufacturer's code."""

    barcode: str


class ProductTemplateBase(BaseModel):
    #: Every string bound here mirrors the column it lands in — the model's
    #: ``String(n)``. Without one, a longer value sailed past validation and
    #: the driver refused it at insert with a truncation error the caller
    #: read as a 500; a bound turns the same request into a translated 422.
    name: str = Field(max_length=255)
    brand: str | None = Field(None, max_length=255)
    barcode: str | None = Field(None, max_length=50)
    #: Already bounded: the validator below caps a SKU at 50 characters,
    #: the length of its column.
    sku: str | None = None

    @field_validator('barcode', mode='before')
    @classmethod
    def normalize_barcode_field(cls, v):
        return normalize_barcode(v)

    @field_validator('sku', mode='before')
    @classmethod
    def validate_sku(cls, v):
        return normalize_sku(v)

    uom_id: UUID | None = None

    # Logistics 2.0 conversion fields
    weight_value: float | None = None
    weight_uom_id: UUID | None = None
    volume_value: float | None = None
    volume_uom_id: UUID | None = None

    image_url: str | None = Field(None, max_length=500)
    description: str | None = Field(None, max_length=500)
    min_quantity: float | None = None


class ProductTemplateCreate(ProductTemplateBase):
    """Request body for POST /items/product-templates.

    Extends ProductTemplateBase (which carries name/brand/barcode/sku and
    the descriptive fields) with the metadata payload the underlying model
    supports. Kept on the schema (not just the service signature) so the
    OpenAPI surface advertises it to the E2E seeding client.
    """

    meta_data: dict | None = None


class ProductTemplateNutritionUpdate(BaseModel):
    """Lightweight schema for updating only nutrition_info on a template."""

    nutrition_info: dict | None = None


class ProductTemplateClone(BaseModel):
    """Schema for cloning a product template."""

    name: str = Field(max_length=255)
    barcode: str | None = Field(None, max_length=50)


class ProductTemplate(ProductTemplateBase):
    id: UUID
    organization_id: UUID | None = None
    # Module-owned enrichment data (namespaced per module, e.g. meta_data['nutrition']).
    meta_data: dict | None = None
    # This organization's AVCO rate. Not a column: it is filled per request
    # from the caller's own valuation layers. It used to be cached on the
    # template row, which a global template shares with every organization, so
    # the figure served here belonged to whoever wrote it last.
    current_valuation_rate: float | None = None
    #: The order this product's stock leaves in; None reads as FIFO. Written
    #: through the item payload, like the threshold (ADR-015).
    removal_strategy: RemovalStrategy | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SkuSchemaConfig(BaseModel):
    prefix: str = ''
    separator: str = '-'
    next_number: int = 1
    pad_length: int = 5
    enabled: bool = False
