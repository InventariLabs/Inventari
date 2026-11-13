from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ._schemas_picking import MAX_SCALE, MAX_SERVINGS

# === Nutrition ===


class NutritionSummary(BaseModel):
    calories_kcal: float | None = None
    protein_g: float | None = None
    fat_g: float | None = None
    carbs_g: float | None = None
    fiber_g: float | None = None
    sugar_g: float | None = None
    salt_g: float | None = None


class IngredientNutrition(BaseModel):
    ingredient_name: str
    quantity: float
    uom: str | None
    has_data: bool
    nutrition: NutritionSummary | None


class RecipeNutrition(BaseModel):
    recipe_id: UUID
    servings: int
    #: The ratio these figures were multiplied by — the truth behind the
    #: rounded ``servings``, which one int can no longer carry.
    scale: float
    per_serving: NutritionSummary
    total: NutritionSummary
    ingredients: list[IngredientNutrition]
    coverage: float
    missing_nutrition: list[str]
    warnings: list[str] = []
    #: True when some counted ingredient got its figures from the generic
    #: ingredient dictionary rather than from a product's own values.
    generic_values: bool = False


# === Shopping List Integration ===


class AddToShoppingListRequest(BaseModel):
    shopping_list_id: UUID | None = None
    servings: int = Field(default=1, ge=1)
    scale: Decimal | None = Field(default=None, gt=0, le=MAX_SCALE)
    """How much of the recipe to buy for, stated as a multiplier. Wins over
    ``servings`` when both arrive."""


class LinkIngredientTemplateRequest(BaseModel):
    template_id: UUID


class AddFromRecipesRequest(BaseModel):
    """Several recipes onto one list — the shopping list's own entry point."""

    recipe_ids: list[UUID] = Field(min_length=1)
    shopping_list_id: UUID | None = None
    servings: int | None = Field(default=None, ge=1)
    """Servings to scale every selected recipe to; each recipe's own when null."""
    scale: Decimal | None = Field(default=None, gt=0, le=MAX_SCALE)
    """How much of every selected recipe to buy for, stated as a multiplier.
    Wins over ``servings`` when both arrive."""


class ListedElsewhere(BaseModel):
    """A line just written that another open shopping list already carries."""

    name: str
    list_id: UUID
    list_name: str


class AddToShoppingListResponse(BaseModel):
    shopping_list_id: UUID
    added_count: int
    #: Lines already on the list that the recipes needed more of, topped up
    #: in place (``added_count`` counts only the lines written new).
    raised_count: int = 0
    # Additive field: name of the list items were added to (for toasts).
    # Optional for backward compatibility with older frontends.
    list_name: str | None = None
    #: Missing goods left off because the list already carries them — so a
    #: second press can say "already on the list" instead of "added 0".
    already_listed_count: int = 0
    #: Lines written to this list that an other open list still asks for too,
    #: so the reader can see the overlap instead of shopping the goods twice.
    on_other_lists: list[ListedElsewhere] = []


# === Cooking History ===


class CookingHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: UUID
    cooked_at: datetime | None
    servings: int
    duration_minutes: int | None
    notes: str | None
    rating: int | None
    items_picked: int
    items_skipped: int
    items_total: int


class PatchCookingHistoryRequest(BaseModel):
    notes: str | None = None
    rating: int | None = None


class RecordCookingRequest(BaseModel):
    """A step-by-step cook opens no picking session — nothing came off the
    shelf. Recording it is what gives the cook its own entry (its own date
    and servings) instead of lending the rating to whatever closed last.

    ``session_id`` is how a cook says it is not a new one: the step-by-step
    screen opened after a picking run for the same dinner continues that
    session instead of writing a second entry for one meal.
    """

    servings: int | None = Field(default=None, ge=1, le=MAX_SERVINGS)
    """Bounded like the picking start it stands beside: a serving count is a
    pot on a stove, and an unbounded one reached the database as an overflow
    (3000000000 answered 500, 100000 answered 201)."""

    session_id: UUID | None = None


# === Image Upload ===


class RecipeImageResponse(BaseModel):
    image_url: str


# === Cost — kept here for import convenience ===


class IngredientCost(BaseModel):
    ingredient_name: str
    quantity: float
    uom: str | None
    estimated_cost: float | None
    currency: str | None
    has_price_data: bool
    price_source: str | None = None


class RecipeCost(BaseModel):
    recipe_id: UUID
    # False when the organization switched cost calculation off: the figures
    # below are then empty by design, not because nothing could be priced, and
    # a screen leaves the cost out instead of offering to fill in prices.
    enabled: bool = True
    servings: int
    estimated_cost: float | None
    currency: str | None
    cost_coverage: float
    mixed_currencies: bool
    missing_cost_ingredients: list[str]
    ingredients: list[IngredientCost]


# === Import / Export ===


class RecipeExportIngredient(BaseModel):
    name: str
    quantity: float
    uom: str | None
    is_optional: bool
    sort_order: int


class RecipeImportIngredient(BaseModel):
    name: str
    quantity: float = 1.0
    uom: str | None = None
    is_optional: bool = False
    sort_order: int = 0


class RecipeImportRequest(BaseModel):
    """Request body for POST /recipes/import."""

    format: str  # 'json' | 'url'
    data: dict[str, Any] | None = None  # for format='json'
    url: str | None = None  # for format='url'


class PreviewIngredient(BaseModel):
    """Parsed ingredient returned inside a recipe import preview."""

    name: str
    quantity: float
    uom_symbol: str | None = None
    uom_id: str | None = None
    original_text: str | None = None
    group_name: str | None = None
    template_id: str | None = None
    template_name: str | None = None
    is_optional: bool = False
    is_spice: bool = False
    allergens: list[str] = Field(default_factory=list)
    original_quantity: float | None = None
    original_unit_text: str | None = None
    unit_display: str | None = None


class RecipePreview(BaseModel):
    """Parsed recipe returned by POST /recipes/import/preview."""

    name: str
    description: str | None = None
    instructions: str | None = None
    servings: int
    prep_time_minutes: int | None = None
    #: Where the source page keeps its picture. Nothing is downloaded for a
    #: preview — the address travels back out with the reviewed recipe and
    #: the server fetches it when the recipe is saved.
    image_source_url: str | None = None
    source_url: str | None = None
    tags: list[str] = []
    ingredients: list[PreviewIngredient] = []
    # 'llm_fallback' when the LLM parse failed and the basic regex parser
    # was used instead — the UI warns that names/units are not translated.
    parse_warning: str | None = None
