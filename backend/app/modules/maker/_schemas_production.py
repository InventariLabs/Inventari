"""Pydantic schemas for Production Order endpoints."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.pagination import PaginatedResponse

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
    # when create_on_shortage_strategy=WARN, the FE re-POSTs
    # with this flag set to confirm despite the shortage list.
    confirm_shortage: bool = False


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
    # What the records lacked of ``consumed_qty`` on a run recorded after the
    # fact (None when the run drew it all) — the ingredient is due a count.
    shortfall_qty: Decimal | None = None
    # Denormalised display names (None when the row they name was deleted).
    child_template_name: str | None = None
    source_location_name: str | None = None


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
    production_date: date | None
    notes: str | None
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
    unit_cost: Decimal | None = None
    reference_price: Decimal | None = None
    result_per_unit: Decimal | None = None


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
