"""Pydantic schemas for pricing endpoints."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ._schemas_breakdown import RecipeState


class PricingRequest(BaseModel):
    """Compute sale price from cost + target margin for one template."""

    template_id: UUID
    produced_qty: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    target_margin_pct: Decimal = Field(ge=0, lt=100)


class PricingResponse(BaseModel):
    """Output — total cost, unit cost and suggested sale price."""

    model_config = ConfigDict(from_attributes=True)

    template_id: UUID
    produced_qty: Decimal
    total_cost: Decimal
    unit_cost: Decimal
    target_margin_pct: Decimal
    unit_sale_price: Decimal
    ingredient_count: int
    """Ingredients the price was computed from; 0 means an empty formula."""

    unrated_ingredient_count: int
    """How many of those have no valuation rate and contributed zero."""

    recipe_state: RecipeState
    """Which of the two zero-ingredient truths this price is about."""
    recipe_id: UUID | None = None
    """The default formula the price was computed on, when one exists."""


class MarginResponse(BaseModel):
    """Read default margin for a template.

    ``is_default`` is ``True`` when the value comes from the system default,
    not from a user-set ``meta_data['maker']['target_margin_pct']``.
    """

    model_config = ConfigDict(from_attributes=True)

    template_id: UUID
    target_margin_pct: Decimal
    is_default: bool


class MarginUpdate(BaseModel):
    """Persist user's preferred target margin for a template."""

    target_margin_pct: Decimal = Field(ge=0, lt=100)
