"""Pydantic schemas for cost breakdown endpoints."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

#: What the answer knows about the formula it costed. A product with no
#: formula and a formula with no lines are two different truths — the reader
#: is sent to create the first and to fill the second, so the answer has to
#: say which one it is and name the formula it is about.
RecipeState = Literal['no_recipe', 'empty', 'has_lines']


class CostBreakdownPlannedDraw(BaseModel):
    """One shelf a planned draw would take from, and how much of it.

    The same plan completion draws by, read before anything leaves stock —
    so the reader learns which shelf the run will empty while closing it
    is still reversible (it stops being so the moment it happens).
    """

    location_id: UUID
    # None when the location row was deleted after stock landed on it.
    location_name: str | None = None
    quantity: Decimal


class CostBreakdownEntry(BaseModel):
    """Per-ingredient cost contribution to a production run."""

    model_config = ConfigDict(from_attributes=True)

    child_template_id: UUID
    consumed_qty: Decimal
    unit: str
    # The layer-average rate per unit and the line's share of it. Both travel
    # so the draft's table can carry the same two named columns as the closed
    # run's — a draft used to show the line amount under a header that the
    # closed run filled with the rate. (Stock value is FIFO; the rate is the
    # average of the layers still on hand — 'avco' is the historical label.)
    unit_cost: Decimal | None = None
    cost: Decimal | None
    percentage_of_total: Decimal | None
    cost_source: str  # 'avco' | 'supplier' (estimates) | 'fifo' (actual) | 'none'
    # Denormalised display name (None when the template was deleted).
    child_template_name: str | None = None
    # Where the ingredient would come from, shelf by shelf, in the order the
    # run would draw it. Empty when no shelf holds any. A shelf short of the
    # whole need still names what it would give — the shortage columns say
    # the rest.
    planned_draws: list[CostBreakdownPlannedDraw] = Field(default_factory=list)


class CostBreakdownResponse(BaseModel):
    """Output for GET /breakdown and POST /production/orders/preview."""

    model_config = ConfigDict(from_attributes=True)

    output_template_id: UUID
    planned_qty: Decimal
    planned_uom_symbol: str | None = None
    """Unit ``planned_qty`` is counted in (the output product's)."""

    total_cost: Decimal
    entries: list[CostBreakdownEntry]
    missing_cost_lines: list[str]  # template IDs with no layer rate or usable offer
    recipe_state: RecipeState
    """Which of the two zero-entry truths this answer is about."""
    recipe_id: UUID | None = None
    """The formula the answer costed — the door each sentence leads through."""
