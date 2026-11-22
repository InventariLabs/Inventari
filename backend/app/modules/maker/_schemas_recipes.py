"""Pydantic schemas for Recipe CRUD, catalog and module settings endpoints."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.pagination import PaginatedResponse

from ._schemas_bom import BoMLineRead

ReferenceDirection = Literal['SAVINGS', 'MARGIN']
AvailabilityCheckScope = Literal['GLOBAL', 'PER_LOCATION']
CreateOnShortageStrategy = Literal['ALLOW', 'WARN', 'BLOCK']
#: The fixed costs of a batch the recipe screen offers, names and badges. The
#: set is closed: a kind the screen cannot name came back to it as a raw code.
CostLineKind = Literal['LABOR', 'PACKAGING', 'OVERHEAD', 'OTHER']


class ProcessStep(BaseModel):
    """One step of a formula's process, and how long it takes.

    A step is a sentence and an optional duration, so a formula that takes two
    hours to make says so, and its labour is costed per step instead of as a lump
    sum typed per batch. The duration is optional: a step nobody timed still
    reads, and costs no labour.
    """

    text: str = Field(min_length=1, max_length=2000)
    minutes: Decimal | None = Field(None, ge=0, max_digits=8, decimal_places=2)

    @field_validator('text', mode='before')
    @classmethod
    def _strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


# ---------------------------------------------------------------------------
# Recipe CRUD
# ---------------------------------------------------------------------------


class RecipeCreate(BaseModel):
    """Input for POST /recipes — create a new recipe."""

    output_template_id: UUID
    name: str = Field(min_length=1, max_length=200)
    batch_yield_qty: Decimal = Field(
        Decimal('1'), gt=0, max_digits=12, decimal_places=4
    )
    batch_yield_uom_id: UUID | None = None
    #: Accepts a bare sentence as well as a step object, so a caller written
    #: before steps carried durations keeps working; the service normalises
    #: both to objects before the row is written.
    process_steps: list[ProcessStep | str] | None = None
    reference_price: Decimal | None = Field(None, ge=0, max_digits=12, decimal_places=2)
    is_default: bool = False
    source_recipe_id: UUID | None = None


class RecipeUpdate(BaseModel):
    """Input for PATCH /recipes/{id} — all fields optional."""

    name: str | None = Field(None, min_length=1, max_length=200)
    batch_yield_qty: Decimal | None = Field(None, gt=0, max_digits=12, decimal_places=4)
    batch_yield_uom_id: UUID | None = None
    #: Accepts a bare sentence as well as a step object, so a caller written
    #: before steps carried durations keeps working; the service normalises
    #: both to objects before the row is written.
    process_steps: list[ProcessStep | str] | None = None
    reference_price: Decimal | None = Field(None, ge=0, max_digits=12, decimal_places=2)
    is_default: bool | None = None


class RecipeFromCulinaryCreate(BaseModel):
    """Input for POST /recipes/from-recipe — maker snapshot of a culinary recipe.

    The culinary recipe (``source_recipe_id``, plain UUID without FK — the
    recipes module may be disabled) is snapshotted into a new maker recipe
    with BOM lines derived from its template-linked ingredients. The maker
    recipe is frozen: later edits of the culinary recipe never propagate
    (one-way snapshot).
    """

    source_recipe_id: UUID
    output_template_id: UUID
    # Optional overrides; both default to the culinary recipe's values
    # (its name and its ``servings`` as the batch yield).
    name: str | None = Field(None, min_length=1, max_length=200)
    batch_yield_qty: Decimal | None = Field(None, gt=0, max_digits=12, decimal_places=4)
    batch_yield_uom_id: UUID | None = None


class RecipeCostLineCreate(BaseModel):
    """Input for POST /recipes/{id}/cost-lines."""

    kind: CostLineKind
    label: str = Field(min_length=1, max_length=120)
    #: Never negative: a fixed cost that subtracts would lower the BOM's unit
    #: cost and the cost of every run after it. Zero is a line costing nothing.
    amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    sort_order: int = 0


class RecipeCostLineUpdate(BaseModel):
    """Input for PATCH /recipes/{id}/cost-lines/{line_id}."""

    kind: CostLineKind | None = None
    label: str | None = Field(None, min_length=1, max_length=120)
    amount: Decimal | None = Field(None, ge=0, max_digits=12, decimal_places=2)
    sort_order: int | None = None


class RecipeCostLineRead(BaseModel):
    """Output schema for a fixed cost line."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    recipe_id: UUID
    kind: str
    label: str
    amount: Decimal
    sort_order: int


class IngredientPriceUpdate(BaseModel):
    """Input for PUT /recipes/ingredient-prices/{template_id}.

    The price is per stock unit in the organization's money. ``None`` clears
    it: an estimate that then finds nothing says so again, rather than
    reading a stale number somebody meant to remove.
    """

    unit_price: Decimal | None = Field(None, ge=0, max_digits=12, decimal_places=4)


class IngredientPriceRead(BaseModel):
    """Output for PUT /recipes/ingredient-prices/{template_id}."""

    product_template_id: UUID
    unit_price: Decimal | None


class BoMLineCreateForRecipe(BaseModel):
    """Input for POST /recipes/{id}/bom-lines — add an ingredient.

    The parent comes from the recipe in the path, so this schema carries no
    ``parent_template_id``: a product with several formulas cannot land a
    line in the wrong one. (The removed ``POST /maker/bom`` took the product
    instead and always wrote to its default formula.)
    """

    child_template_id: UUID
    qty_per_batch: Decimal = Field(gt=0, max_digits=12, decimal_places=4)
    unit: str = Field(min_length=1, max_length=8)
    uom_id: UUID | None = None
    yield_loss_pct: Decimal = Field(
        Decimal('0'), ge=0, le=100, max_digits=5, decimal_places=2
    )
    #: An ingredient with a recipe of its own is made fresh on every run and
    #: never taken from its stock. The default takes stock first.
    make_fresh: bool = False
    notes: str | None = Field(None, max_length=500)


class BoMLineUpdate(BaseModel):
    """Input for PATCH /recipes/{id}/bom-lines/{line_id} — in-place edit."""

    qty_per_batch: Decimal | None = Field(None, gt=0, max_digits=12, decimal_places=4)
    uom_id: UUID | None = None
    yield_loss_pct: Decimal | None = Field(
        None, ge=0, le=100, max_digits=5, decimal_places=2
    )
    make_fresh: bool | None = None
    notes: str | None = Field(None, max_length=500)


class RecipeRead(BaseModel):
    """Output for GET /recipes/{id} — full recipe detail."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    output_template_id: UUID
    name: str
    batch_yield_qty: Decimal
    batch_yield_uom_id: UUID | None
    process_steps: list[ProcessStep] | None
    reference_price: Decimal | None

    @field_validator('process_steps', mode='before')
    @classmethod
    def _step_rows_written_before_time(cls, value: object) -> object:
        """Read a row whose steps are still bare sentences.

        ``018`` rewrites those rows, but an older process still writing steps
        during a deploy can store one afterwards, and a formula that no longer
        opens is worse than one whose steps have no duration. The write path
        normalises the same shape; this is the read side of that promise.
        """
        if not isinstance(value, list):
            return value
        steps: list[object] = []
        for step in value:
            if isinstance(step, str):
                text = step.strip()
                if text:
                    steps.append({'text': text, 'minutes': None})
            else:
                steps.append(step)
        return steps

    is_default: bool
    source_recipe_id: UUID | None
    source_snapshot_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Denormalised display name
    output_template_name: str | None = None
    batch_yield_uom_symbol: str | None = None
    """Unit of ``batch_yield_qty`` — the recipe's own, or the output
    product's when the recipe does not override it. Without it the yield is
    a bare number next to ingredients that all carry a measure."""

    cost_lines: list[RecipeCostLineRead] = Field(default_factory=list)
    #: The batch's labour, from the timed steps at the organization's hourly
    #: rate. Computed, never stored on the recipe: changing the rate or a
    #: step's duration changes it, and a stored copy would disagree.
    labour_cost: Decimal | None = None
    # Ingredient lines (BOM) — populated on detail reads.
    lines: list[BoMLineRead] = Field(default_factory=list)
    # AVCO-based cost estimate for one unit of output (None without a BOM).
    estimated_unit_cost: Decimal | None = None


class RecipeBridgeRead(RecipeRead):
    """A snapshot from the culinary bridge, and who made it.

    The bridge is idempotent: asking twice for the same output × source
    pair hands back the first answer. A caller that abandons the second
    half of the bridge needs to tell the two apart before cleaning up,
    or it deletes a record somebody else was using.
    """

    created: bool


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


class RecipeCatalogItem(BaseModel):
    """One card in the /maker/recipes catalog."""

    id: UUID
    output_template_id: UUID
    name: str
    output_template_name: str | None = None
    # The recipe's picture is the output product's picture — one source of
    # truth, the column the product already carries.
    output_template_image_url: str | None = None
    batch_yield_qty: Decimal
    batch_yield_uom_symbol: str | None = None
    #: The culinary recipe this formula is a snapshot of, when it is one.
    source_recipe_id: UUID | None = None
    is_default: bool
    ingredient_count: int
    unit_cost: Decimal | None = None  # last_unit_cost from last completed order
    #: How many ingredients of that run had no purchase rate. Completion
    #: prices those at zero so the run can finish, so a total of 0 with a
    #: count above zero means "nobody knows", not "it is free".
    uncosted_ingredients: int = 0
    #: That run made more than it planned.
    last_run_overproduced: bool = False
    #: Today's estimate from layer rates, computed only when no run has ever
    #: closed — the dash it replaced read as "the system does not know", one
    #: click before the same application showed the number. A recipe with a
    #: run keeps the run's number under its own name instead.
    estimated_unit_cost: Decimal | None = None
    #: Ingredients the estimate found no rate for — same "nobody knows"
    #: caveat as on the run's own count.
    estimated_uncosted_ingredients: int = 0
    reference_price: Decimal | None = None
    # Per-unit financial outcome = reference_price - last_unit_cost
    # (null when either is null). Positive = savings (SAVINGS) or margin
    # (MARGIN) per unit of output — direction only changes the FE label.
    result: Decimal | None = None
    # Org-level setting from maker_module_settings (SAVINGS|MARGIN).
    reference_direction: ReferenceDirection | None = None
    stock_qty: Decimal | None = None
    #: The unit ``stock_qty`` is counted in: the product's own, which a batch
    #: yield written in another unit does not change.
    stock_uom_symbol: str | None = None
    last_produced_at: datetime | None = None


class RecipeCatalogResponse(PaginatedResponse[RecipeCatalogItem]):
    """Paginated catalog response."""


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


class IngredientAvailabilityItem(BaseModel):
    """Per-ingredient availability in an availability check."""

    child_template_id: UUID
    child_template_name: str | None = None
    needed: Decimal
    available: Decimal
    shortage: Decimal | None = None
    """None when the recipe's measure and the stock's cannot be compared —
    no bridge, no verdict. Not the same as "nothing is missing"."""

    uom_symbol: str | None = None
    convertible: bool = True
    available_uom_symbol: str | None = None
    """Set only when ``convertible`` is false: the unit ``available`` is
    actually counted in, so 100 litres never renders as 100 kilograms."""

    to_buy: Decimal | None = None
    """What buying the shortage puts on a shopping list: the shortfall
    rounded up to the ingredient's own stock unit's step, stated in that
    unit. None when nothing is short, or when no quantity can be stated."""

    to_buy_uom_symbol: str | None = None
    """The unit ``to_buy`` is counted in — the ingredient's stock unit."""


class ShortagePurchaseOrderResponse(BaseModel):
    """Output for POST /recipes/{id}/shortages/purchase-order.

    None when the batch is covered, or when an open order already expects
    what is short: nothing is ordered then, and no empty or duplicate
    document is left behind for somebody to cancel.
    """

    purchase_order_id: UUID | None = None
    number: str | None = None
    added_count: int = 0
    #: Short ingredients an open order already expects. Nothing new is
    #: ordered for them, so the notice can say so instead of raising a
    #: second identical draft.
    already_ordered_count: int = 0


class AvailabilityResponse(BaseModel):
    """Response for GET /maker/recipes/{id}/availability."""

    max_batches: Decimal | None = None
    """Whole batches only — a batch is made or it is not. None when at least
    one ingredient cannot be compared: an unmeasurable bottleneck yields no
    batch count."""

    has_shortage: bool
    has_unknown: bool = False
    ingredients: list[IngredientAvailabilityItem]


# ---------------------------------------------------------------------------
# Module settings
# ---------------------------------------------------------------------------


class MakerSettingsRead(BaseModel):
    """Output for GET /maker/settings."""

    model_config = ConfigDict(from_attributes=True)

    organization_id: UUID
    reference_direction: ReferenceDirection
    allow_overproduction: bool = True
    availability_check_scope: AvailabilityCheckScope = 'GLOBAL'
    create_on_shortage_strategy: CreateOnShortageStrategy = 'WARN'
    #: What an hour of the organization's own work costs. A formula's labour
    #: is its steps' minutes at this rate; zero means nobody named one.
    labor_hourly_rate: Decimal = Decimal('0')
    created_at: datetime
    updated_at: datetime


class MakerSettingsUpdate(BaseModel):
    """Input for PATCH /maker/settings."""

    reference_direction: ReferenceDirection | None = None
    allow_overproduction: bool | None = None
    availability_check_scope: AvailabilityCheckScope | None = None
    create_on_shortage_strategy: CreateOnShortageStrategy | None = None
    labor_hourly_rate: Decimal | None = Field(
        None, ge=0, max_digits=12, decimal_places=2
    )
