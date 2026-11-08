"""Pydantic schemas for Recipe CRUD, catalog and module settings endpoints."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.pagination import PaginatedResponse

from ._schemas_bom import BoMLineRead

ReferenceDirection = Literal['SAVINGS', 'MARGIN']
AvailabilityCheckScope = Literal['GLOBAL', 'PER_LOCATION']
CreateOnShortageStrategy = Literal['ALLOW', 'WARN', 'BLOCK']

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
    process_steps: list[str] | None = None
    reference_price: Decimal | None = Field(None, max_digits=12, decimal_places=2)
    is_default: bool = False
    source_recipe_id: UUID | None = None


class RecipeUpdate(BaseModel):
    """Input for PATCH /recipes/{id} — all fields optional."""

    name: str | None = Field(None, min_length=1, max_length=200)
    batch_yield_qty: Decimal | None = Field(None, gt=0, max_digits=12, decimal_places=4)
    batch_yield_uom_id: UUID | None = None
    process_steps: list[str] | None = None
    reference_price: Decimal | None = Field(None, max_digits=12, decimal_places=2)
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

    kind: str = Field(min_length=1, max_length=16)
    label: str = Field(min_length=1, max_length=120)
    amount: Decimal = Field(max_digits=12, decimal_places=2)
    sort_order: int = 0


class RecipeCostLineUpdate(BaseModel):
    """Input for PATCH /recipes/{id}/cost-lines/{line_id}."""

    kind: str | None = Field(None, min_length=1, max_length=16)
    label: str | None = Field(None, min_length=1, max_length=120)
    amount: Decimal | None = Field(None, max_digits=12, decimal_places=2)
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
    notes: str | None = Field(None, max_length=500)


class BoMLineUpdate(BaseModel):
    """Input for PATCH /recipes/{id}/bom-lines/{line_id} — in-place edit."""

    qty_per_batch: Decimal | None = Field(None, gt=0, max_digits=12, decimal_places=4)
    uom_id: UUID | None = None
    yield_loss_pct: Decimal | None = Field(
        None, ge=0, le=100, max_digits=5, decimal_places=2
    )
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
    process_steps: list[str] | None
    reference_price: Decimal | None
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
    is_default: bool
    ingredient_count: int
    unit_cost: Decimal | None = None  # last_unit_cost from last completed order
    #: How many ingredients of that run had no purchase rate. Completion
    #: prices those at zero so the run can finish, so a total of 0 with a
    #: count above zero means "nobody knows", not "it is free".
    uncosted_ingredients: int = 0
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
    created_at: datetime
    updated_at: datetime


class MakerSettingsUpdate(BaseModel):
    """Input for PATCH /maker/settings."""

    reference_direction: ReferenceDirection | None = None
    allow_overproduction: bool | None = None
    availability_check_scope: AvailabilityCheckScope | None = None
    create_on_shortage_strategy: CreateOnShortageStrategy | None = None
