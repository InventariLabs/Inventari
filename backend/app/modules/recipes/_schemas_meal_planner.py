from __future__ import annotations

import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.recipes.models import MealSlot

from ._schemas_io import ListedElsewhere

# === MealPlanner ===


class MealPlanCreate(BaseModel):
    name: str | None = None
    start_date: datetime.date
    end_date: datetime.date
    # Same default as the create form (DEFAULT_SLOTS) so the API contract and
    # the UI agree on what "a plan" contains.
    enabled_slots: list[MealSlot] = [
        MealSlot.BREAKFAST,
        MealSlot.LUNCH,
        MealSlot.DINNER,
    ]
    default_servings: int | None = None
    notes: str | None = None


class MealPlanUpdate(BaseModel):
    name: str | None = None
    start_date: datetime.date | None = None
    end_date: datetime.date | None = None
    enabled_slots: list[MealSlot] | None = None
    # when the update disables slots that still hold entries, the API
    # answers 409 with per-slot conflicts; passing this flag asks it to delete
    # those conflicting entries in the same transaction instead.
    remove_conflicting_entries: bool = False
    default_servings: int | None = None
    notes: str | None = None


class MealPlanEntryCreate(BaseModel):
    date: datetime.date
    slot: MealSlot
    recipe_id: UUID
    servings: int | None = None
    notes: str | None = None
    # Omitted means "put it at the end of that meal". It used to default to 0,
    # which is exactly where the dish already in the cell sits, so a second
    # dish collided with the unique constraint and came back as a 500.
    order: int | None = None


class MealPlanEntryUpdate(BaseModel):
    recipe_id: UUID | None = None
    servings: int | None = None
    notes: str | None = None
    order: int | None = None
    # Move support (drag & drop): either field may be omitted to keep the
    # current value; at least one of date/slot must be present to move.
    date: datetime.date | None = None
    slot: MealSlot | None = None


class MealPlanEntrySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    date: datetime.date
    slot: MealSlot
    recipe_id: UUID
    recipe_name: str
    recipe_image_url: str | None = None
    servings: int
    notes: str | None = None
    order: int
    is_completed: bool = False
    picking_session_id: UUID | None = None


class DailyNutritionSummary(BaseModel):
    date: datetime.date
    calories_kcal: float | None = None
    protein_g: float | None = None
    fat_g: float | None = None
    carbs_g: float | None = None
    # Share of the day's non-negligible ingredients that had nutrition values.
    coverage: float = 1.0
    # True when any recipe of the day used generic ingredient values.
    generic_values: bool = False


class MealPlanSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str | None = None
    start_date: datetime.date
    end_date: datetime.date
    enabled_slots: list[MealSlot]
    # None means "no plan-wide default" — each entry then follows the
    # servings its own recipe is written for.
    default_servings: int | None = None
    shopping_list_id: UUID | None = None
    #: The plan holds a meal its shopping list was not made for — planned
    #: after the list, or asking for more servings than it was listed with.
    meals_added_since_list: bool = False
    notes: str | None = None
    entries: list[MealPlanEntrySchema] = []
    daily_nutrition_summary: list[DailyNutritionSummary] = []
    created_by: UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime


class MealPlanListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str | None = None
    start_date: datetime.date
    end_date: datetime.date
    enabled_slots: list[MealSlot]
    # None means "no plan-wide default" — each entry then follows the
    # servings its own recipe is written for.
    default_servings: int | None = None
    shopping_list_id: UUID | None = None
    entry_count: int = 0
    created_at: datetime.datetime
    updated_at: datetime.datetime


class BulkEntriesSave(BaseModel):
    entries: list[MealPlanEntryCreate]


class CopyPlanRequest(BaseModel):
    start_date: datetime.date
    end_date: datetime.date


class CopyPlanResponse(BaseModel):
    plan: MealPlanSchema
    copied: int
    skipped: int


class SuggestedRecipe(BaseModel):
    recipe_id: UUID
    name: str
    image_url: str | None = None
    prep_time_minutes: int | None = None
    availability_pct: float
    ingredients_available: int = 0
    """Required ingredients on the shelf, of ``ingredients_total``.

    The pair the recipe card writes, carried here too: a percentage of five
    ingredients is a rounding of these two numbers, and the reader who wants
    to know what is missing cannot get back to them from 80%.
    """
    ingredients_total: int = 0
    expiry_urgency_score: float
    score: float


class _GeneratedItem(BaseModel):
    key: str
    """What tells this line from the others in the same result: the product
    it was aggregated on and its measure. Names repeat (grams and pieces of
    one product are two lines), so a client keys its rows by this."""
    name: str
    #: Decimal, not int: a recipe line carries the unit's own step ("0.75
    #: kg"), and the generated list must not claim a whole number the
    #: recipe never asked for.
    quantity: Decimal
    uom_id: UUID | None = None
    uom_symbol: str | None = None
    """The unit's symbol as the interface spells it — the summary chips carry
    the number and its measure together ("200 ml"), like the list itself."""
    needed_by: str | None = None
    quantities_comparable: bool = True
    """False when stock exists but its measure and the recipe's cannot be
    put on one scale, so the quantity here is the full requirement rather
    than a deficit — the note says as much."""
    matched_approximately: bool = False
    """True when the line was deducted against a product resolved by name
    rather than by an explicit link."""


class ShoppingListGenerationResult(BaseModel):
    """The result of generating a shopping list from a meal plan.

    The outcome of an action: the list that was written and the counts that
    explain it, with ``items`` the lines it just received. Not a collection
    a client pages — the list itself is read from the shopping-list endpoints.
    """

    shopping_list_id: UUID
    total_ingredients: int
    available_count: int
    to_buy_count: int
    items: list[_GeneratedItem] = []
    #: Lines written to this list that an other open list still asks for too.
    on_other_lists: list[ListedElsewhere] = []


# === Shopping Exclusions ===


class ShoppingExclusionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    template_id: UUID | None = None


class ShoppingExclusionSchema(BaseModel):
    id: UUID
    name: str
    name_normalized: str
    template_id: UUID | None = None
    template_name: str | None = None
    template_barcode: str | None = None
    template_image_url: str | None = None
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)
