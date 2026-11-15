"""Pydantic schemas for Production Order endpoints."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.pagination import PaginatedResponse

from ._schemas_batches import IngredientLotChoice
from ._schemas_breakdown import CostBreakdownResponse
from ._schemas_recipes import IngredientAvailabilityItem


class ProductionOrderCreate(BaseModel):
    """Input for POST /production/orders — DRAFT order to fulfil later.

    Note: there is no ``input_storage_location_id`` — ingredients can be
    drawn from multiple locations. Resolution happens at completion time
    via ``stock_consumption.consume_across_locations``.
    """

    output_template_id: UUID
    recipe_id: UUID | None = None
    planned_qty: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    output_location_id: UUID
    production_date: date | None = None
    notes: str | None = Field(None, max_length=500)
    #: The batch the output goes into; empty puts it on the shelf unbatched.
    output_lot_name: str | None = Field(None, max_length=100)
    # when create_on_shortage_strategy=WARN, the FE re-POSTs
    # with this flag set to confirm despite the shortage list.
    confirm_shortage: bool = False

    @field_validator('output_lot_name')
    @classmethod
    def _blank_is_no_batch(cls, value: str | None) -> str | None:
        """A batch name of spaces names no batch."""
        if value is None:
            return None
        return value.strip() or None


class ProductionMadeCreate(ProductionOrderCreate):
    """Input for POST /production/orders/made — a run that already happened.

    Besides the run, what closing it decides: the output batch's
    best-before (the run's day plus the product's shelf life when left
    out) and, per ingredient, the batches it was taken from (the removal
    order when left out).
    """

    best_before: date | None = None
    ingredient_lots: list[IngredientLotChoice] = Field(
        default_factory=list, max_length=500
    )


class ProductionOrderLineRead(BaseModel):
    """Snapshot of one consumed ingredient at completion time."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    production_order_id: UUID
    child_template_id: UUID
    consumed_qty: Decimal
    unit: str
    source_location_id: UUID | None
    unit_cost_snapshot: Decimal | None
    cost_source: str | None
    #: What the formula predicted for this ingredient when the run closed:
    #: its standard quantity for the output that came out, at the estimated
    #: rate. ``None`` on runs that closed before the estimate was kept.
    estimated_qty: Decimal | None = None
    estimated_unit_cost_snapshot: Decimal | None = None
    # What the records lacked of ``consumed_qty`` on a run recorded after the
    # fact (None when the run drew it all) — the ingredient is due a count.
    shortfall_qty: Decimal | None = None
    # Denormalised display names (None when the row they name was deleted).
    child_template_name: str | None = None
    source_location_name: str | None = None


class ProductionStepRead(BaseModel):
    """One process step of a run in progress: its text, time and the day it was done."""

    text: str | None = None
    minutes: int | None = None
    done_on: date | None = None


class ProductionPortionRead(BaseModel):
    """One portion of a run's output, put on the shelf on its own day."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    qty: Decimal
    made_on: date
    lot_name: str | None = None
    item_id: UUID | None = None
    unit_cost: Decimal | None = None
    created_at: datetime


class ShortageItemRead(BaseModel):
    """One blocked ingredient — the refusal's own row.

    Mirrors ``availability_service.ShortageItem`` so the order page can
    read the exact list completion refuses with, instead of recomputing a
    forecast that could disagree with it. ``shortage`` is null when the
    line's measure and the stock's have no bridge: the ingredient still
    blocks the run, but as "nobody can tell", not as a quantity.
    """

    model_config = ConfigDict(from_attributes=True)

    child_template_id: UUID
    child_template_name: str | None
    needed: Decimal
    available: Decimal
    shortage: Decimal | None
    uom_symbol: str | None
    convertible: bool = True
    available_uom_symbol: str | None = None


class ProductionOrderRead(BaseModel):
    """Output for GET/POST /production/orders/{id}."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    output_template_id: UUID
    recipe_id: UUID | None = None
    # Human-facing run number ("PR/2026/0001"); NULL for legacy orders —
    # the interface falls back to the short-UUID display for them.
    number: str | None = None
    planned_qty: Decimal
    actual_qty: Decimal | None = None
    overproduced: bool = False
    scrap_qty: Decimal | None = None
    output_location_id: UUID
    status: str
    total_cost: Decimal | None
    #: The cost the formula predicted when the run closed, beside the cost
    #: it actually carried — the two figures the page puts side by side.
    estimated_total_cost: Decimal | None = None
    production_date: date | None
    notes: str | None
    output_lot_name: str | None = None
    #: The batch the output went into (completed runs), its state — ``held``
    #: or ``quarantined`` while on hold — and its best-before.
    output_lot_id: UUID | None = None
    output_lot_status: str | None = None
    best_before: date | None = None
    #: The output product's shelf life in days: what a best-before is
    #: counted from when the run closes. On the single-order read only.
    shelf_life_days: int | None = None
    created_by: UUID | None
    completed_by: UUID | None
    created_at: datetime
    completed_at: datetime | None
    # Denormalised join field (from output_template relationship) so the
    # frontend can show/filter by product name instead of a raw UUID.
    output_template_name: str | None = None
    output_uom_symbol: str | None = None
    """Unit of ``planned_qty`` / ``actual_qty`` — the output product's."""

    cancel_reason: str | None = None
    produced_item_id: UUID | None = None
    # Name of the item this run produced — the detail page linked to a bare
    # identifier before, which told the operator nothing.
    produced_item_name: str | None = None
    # Derived: total_cost / actual_qty (same expression as the receipt).
    unit_cost: Decimal | None = None
    # Drafts only: how many ingredients the planned consumption cannot cover,
    # counted the way completion counts them when it refuses a run — at the
    # order's own output location, unmeasurable ingredients included. None
    # for orders past the draft: their consumption already happened — and
    # for drafts without a recipe: there is nothing to forecast from.
    shortage_count: int | None = None
    # The rows behind the count, on the detail read: the same list the 422
    # refusal carries, so the page that names the blocker can name every
    # ingredient it comes from.
    shortage_items: list[ShortageItemRead] | None = None
    # financial result snapshot at completion (null for legacy
    # orders without a recipe, or when the recipe had no reference price).
    unit_cost_snapshot: Decimal | None = None
    reference_price_snapshot: Decimal | None = None
    result_per_unit: Decimal | None = None
    result_per_batch: Decimal | None = None
    lines: list[ProductionOrderLineRead] = Field(default_factory=list)
    #: The day a run that is finished later was started, and what its
    #: ingredients cost — its work in progress until it closes. Null on a run
    #: completed in one step.
    started_on: date | None = None
    material_cost: Decimal | None = None
    #: What of the run's cost could not go on the shelf because its output left
    #: it before the run closed. Null unless the run was filled in portions.
    unshelved_cost: Decimal | None = None
    #: The process steps of a run that was started, with the day each was done.
    steps: list[ProductionStepRead] = Field(default_factory=list)
    #: The output put on the shelf so far, portion by portion.
    portions: list[ProductionPortionRead] = Field(default_factory=list)


class ProductionStockMoveRead(BaseModel):
    """One stock move of a production run, named for display.

    A module-local view over ``StockMoveDTO``: the core contract carries
    identifiers, and resolving them to names is presentation, which belongs
    to the module that presents them.
    """

    id: UUID
    product_template_id: UUID
    product_template_name: str | None = None
    # A quantity means nothing without its measure: the same screen two
    # paragraphs above writes "200 ml" and "4 kg", this table wrote "200"
    # and "4".
    uom_symbol: str | None = None
    from_location_id: UUID | None = None
    to_location_id: UUID | None = None
    # The shelves the move names, resolved for the reader: which shelf the
    # goods left and which they landed on is the question the trace exists
    # to answer, and an identifier answers it for nobody. None when the
    # location row is gone (or the side never had one — consumption goes
    # from a shelf into the run, receipt arrives out of it).
    from_location_name: str | None = None
    to_location_name: str | None = None
    quantity: Decimal
    lot_id: UUID | None = None
    lot_code: str | None = None
    created_at: datetime | None = None


class ProductionOrderCancel(BaseModel):
    """Optional request body for POST /orders/{id}/cancel.

    ``reason`` is stored on the order row and mirrored to the audit log.
    """

    reason: str | None = Field(None, max_length=500)


class ProductionOrderComplete(BaseModel):
    """Optional request body for POST /orders/{id}/complete.

    ``actual_qty`` is the real output quantity. When omitted, defaults to
    ``planned_qty`` (backward compatible). Must be > 0. When
    ``actual_qty > planned_qty``, the org's ``allow_overproduction`` setting
    gates acceptance.
    """

    actual_qty: Decimal | None = Field(None, ge=0, max_digits=12, decimal_places=3)
    #: The output batch's best-before; left out, the run's day plus the
    #: product's shelf life.
    best_before: date | None = None
    #: The batches the person chose for ingredients; an ingredient left out
    #: is taken in the product's removal order.
    ingredient_lots: list[IngredientLotChoice] = Field(
        default_factory=list, max_length=500
    )


class ProductionOrderStart(BaseModel):
    """Optional request body for POST /orders/{id}/start.

    ``started_on`` is the day the ingredients were taken; the organization's
    today when omitted.
    """

    started_on: date | None = None


class ProductionOrderFinish(BaseModel):
    """Optional request body for POST /orders/{id}/finish.

    ``actual_qty`` is what the whole run made, portions already put on the
    shelf included; the rest of it is put on the shelf now. ``finished_on``
    is the day it closed and ``output_lot_name`` the batch of that closing
    quantity.
    """

    actual_qty: Decimal | None = Field(None, ge=0, max_digits=12, decimal_places=3)
    finished_on: date | None = None
    output_lot_name: str | None = Field(None, max_length=100)

    @field_validator('output_lot_name')
    @classmethod
    def _blank_is_no_batch(cls, value: str | None) -> str | None:
        """A batch name of spaces names no batch."""
        if value is None:
            return None
        return value.strip() or None


class ProductionPortionCreate(BaseModel):
    """Request body for POST /orders/{id}/portions — output before the run closes."""

    qty: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    made_on: date | None = None
    output_lot_name: str | None = Field(None, max_length=100)

    @field_validator('output_lot_name')
    @classmethod
    def _blank_is_no_batch(cls, value: str | None) -> str | None:
        """A batch name of spaces names no batch."""
        if value is None:
            return None
        return value.strip() or None


class ProductionStepTick(BaseModel):
    """Request body for PUT /orders/{id}/steps/{index} — a step done on a day.

    ``done_on`` null clears the tick.
    """

    done_on: date | None = None


class ProductionOrderUpdate(BaseModel):
    """Request body for PATCH /orders/{id} — all fields optional.

    Only DRAFT orders can be updated; ``status``, ``output_template_id``
    and ``output_storage_location_id`` are immutable after creation.
    """

    planned_qty: Decimal | None = Field(None, gt=0, max_digits=12, decimal_places=3)
    production_date: date | None = None
    notes: str | None = Field(None, max_length=500)


class ProductionOrderListResponse(PaginatedResponse[ProductionOrderRead]):
    """Paginated envelope for GET /production/orders."""


class MonthlyResultItem(BaseModel):
    """One month of the aggregated financial result (dashboard widget)."""

    month: str
    result: Decimal
    orders: int


class ProductionPreviewResponse(CostBreakdownResponse):
    """Output for POST /production/orders/preview — what a run would take and cost.

    The breakdown, plus what the person deciding needs before saving: each
    ingredient's need against what the records hold where the run would draw
    (``ingredients``, judged like completion judges), the recipe's batch size,
    and the cost per unit with the recipe's fixed costs and the result against
    its reference price.
    """

    ingredients: list[IngredientAvailabilityItem] = Field(default_factory=list)
    has_shortage: bool = False
    batch_yield_qty: Decimal | None = None
    fixed_cost: Decimal = Decimal('0')
    #: The batch's labour, from the timed steps at the organization's rate.
    labour_cost: Decimal = Decimal('0')
    unit_cost: Decimal | None = None
    reference_price: Decimal | None = None
    result_per_unit: Decimal | None = None
    #: The output product's shelf life in days, for the best-before the
    #: form proposes.
    shelf_life_days: int | None = None


class ShortageShoppingListResponse(BaseModel):
    """Output for POST /production/orders/shortages/shopping-list.

    The result of an action, not a collection: it names the list that was
    touched and counts the lines added and raised, and carries no rows to page.
    """

    shopping_list_id: UUID | None = None
    """None when nothing was short — no list is touched then."""

    list_name: str | None = None
    added_count: int = 0
    """Lines written new."""

    raised_count: int = 0
    """Lines already on the list that the run needs more of, topped up."""
