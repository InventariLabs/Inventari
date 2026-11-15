"""Schemas of a run's batches: the output's, the ingredients', and the record."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ShelfLifeUpdate(BaseModel):
    """Input for PUT /production/shelf-lives/{template_id}; ``None`` clears it."""

    shelf_life_days: int | None = Field(None, ge=1, le=36500)


class ShelfLifeRead(BaseModel):
    """A product's shelf life in days, ``None`` when nobody named one."""

    product_template_id: UUID
    shelf_life_days: int | None


class IngredientLotChoice(BaseModel):
    """One batch an ingredient is taken from, and how much of it.

    The quantity is in the ingredient's stock unit, the unit the batch plan
    answers in. The choices of one ingredient add up to what the run takes
    of it.
    """

    template_id: UUID
    lot_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=16, decimal_places=6)


class OutputBatchHold(BaseModel):
    """Input for POST /production/orders/{id}/hold: why the batch is held."""

    reason: str = Field(min_length=1, max_length=500)

    @field_validator('reason')
    @classmethod
    def _not_only_spaces(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError('reason is empty')
        return stripped


class OutputBatchRead(BaseModel):
    """The run's output batch as it stands after a hold or a release."""

    lot_id: UUID
    lot_name: str
    status: str


class IngredientBatchDraw(BaseModel):
    """A part of an ingredient's need, from one batch (``None``: stock without one)."""

    lot_id: UUID | None = None
    lot_name: str | None = None
    expiry_date: date | None = None
    quantity: Decimal


class IngredientBatchOption(BaseModel):
    """A batch of the ingredient the run may take from, and how much it has free."""

    lot_id: UUID
    lot_name: str
    expiry_date: date | None = None
    production_date: date | None = None
    available: Decimal


class IngredientBatchPlan(BaseModel):
    """Which batches an ingredient of the run will be taken from.

    ``plan`` is the draw the run makes when nobody chooses — the product's
    removal order, earliest best-before first under FEFO — and ``batches``
    every batch the person may choose instead. Held, recalled and expired
    batches are in neither. Quantities are in the ingredient's stock unit.
    """

    template_id: UUID
    template_name: str | None = None
    uom_symbol: str | None = None
    needed: Decimal
    plan: list[IngredientBatchDraw] = Field(default_factory=list)
    batches: list[IngredientBatchOption] = Field(default_factory=list)


class IngredientBatchPlanResponse(BaseModel):
    """Output for POST /production/orders/ingredient-batches."""

    ingredients: list[IngredientBatchPlan] = Field(default_factory=list)


class BatchRecordBatch(BaseModel):
    """What a run took of one ingredient from one batch."""

    lot_id: UUID | None = None
    lot_name: str | None = None
    expiry_date: date | None = None
    quantity: Decimal


class BatchRecordIngredient(BaseModel):
    """One ingredient of the batch record, with the batches it came from."""

    template_id: UUID
    template_name: str | None = None
    unit: str
    consumed_qty: Decimal
    shortfall_qty: Decimal | None = None
    unit_cost: Decimal | None = None
    cost: Decimal | None = None
    batches: list[BatchRecordBatch] = Field(default_factory=list)


class ProductionAttachmentRead(BaseModel):
    """A file filed under a run."""

    id: UUID
    production_order_id: UUID
    original_name: str
    content_type: str
    size_bytes: int
    url: str
    uploaded_by: UUID | None = None
    created_at: datetime


class BatchRecordRead(BaseModel):
    """Everything the printed batch record of a completed run says."""

    order_id: UUID
    number: str | None = None
    status: str
    output_template_name: str | None = None
    recipe_name: str | None = None
    output_uom_symbol: str | None = None
    planned_qty: Decimal
    actual_qty: Decimal | None = None
    scrap_qty: Decimal | None = None
    output_lot_name: str | None = None
    output_lot_status: str | None = None
    production_date: date | None = None
    best_before: date | None = None
    output_location_name: str | None = None
    ingredients: list[BatchRecordIngredient] = Field(default_factory=list)
    material_cost: Decimal | None = None
    total_cost: Decimal | None = None
    estimated_total_cost: Decimal | None = None
    unit_cost: Decimal | None = None
    created_by_name: str | None = None
    created_at: datetime
    completed_by_name: str | None = None
    completed_at: datetime | None = None
    notes: str | None = None
    attachments: list[ProductionAttachmentRead] = Field(default_factory=list)
