from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# === Availability ===

#: The most one scale factor may multiply a recipe by. A ceiling like the
#: one servings has (``MAX_SERVINGS``): without it ``scale=1e9`` waves
#: through a request that grinds availability across the whole warehouse.
MAX_SCALE = 100


class BestItemSchema(BaseModel):
    item_id: UUID
    available_quantity: float
    uom_symbol: str | None
    expiry_date: str | None
    location: str | None
    fefo_days_left: int | None
    #: Past its date on the organization's day. Such an item is never the
    #: pick while a fresh one is there, and counts towards nothing the
    #: recipe needs; it is shown so the row can say why it is not enough.
    expired: bool = False


class IngredientAvailability(BaseModel):
    ingredient_id: UUID
    name: str
    display_text: str | None = None
    required_quantity: float
    required_uom: str | None
    #: The scaled requirement before the unit's step rounded it up; null when
    #: the step changed nothing. Rounding a requirement up is deliberate —
    #: part of a carton is a carton — and the card needs the number it came
    #: from, or a typed ½ read as "1" looks like a save that failed.
    required_quantity_unrounded: float | None = None
    required_uom_id: UUID | None = None
    original_quantity: float | None = None
    original_unit_text: str | None = None
    # available | available_approx | incomparable | insufficient | missing | unknown
    # available_approx = matched by name (fuzzy), not by an exact template_id
    # incomparable = found on the shelf, but the two measures cannot meet;
    #   counted out of "have" and "missing" alike — neither verdict is knowable
    # insufficient = found on the shelf, less of it than the recipe asks for
    # unknown = the ingredient names nothing lookupable; an empty shelf is 'missing'
    status: str
    match_type: str | None = None  # 'exact' | 'fuzzy' | None
    quantities_comparable: bool = True
    """False exactly when status is 'incomparable' — the goods were found but
    the recipe's measure and the shelf's cannot be put on one scale — 400 g
    asked of stock counted in pieces, with nothing recording what a piece
    weighs. The two readings below let the caller show both numbers instead
    of inventing a verdict."""
    available_quantity: float | None = None
    available_uom: str | None = None
    # Whether the ingredient points at a product template. Not the same as
    # having stock, and not the same as being findable by name: it is the
    # only thing offering to link the ingredient should depend on.
    is_linked: bool = False
    #: The cook marked it as a spice in the import review, whatever the amount
    #: says. The card folds the seasonings section from this and the required
    #: amount together.
    is_spice: bool = False
    #: The organization marked this ingredient "Always at home", by name or
    #: by product. The availability itself still reports the shelf; this is
    #: the half of the buy rule the shopping door needs so it opens exactly
    #: when the list behind it would add a line.
    excluded: bool = False
    best_item: BestItemSchema | None
    alternative_items: list[BestItemSchema]


class RecipeAvailability(BaseModel):
    recipe_id: UUID
    recipe_name: str
    servings_requested: int
    #: The ratio these quantities were multiplied by — the truth behind the
    #: rounded ``servings_requested``, which one int can no longer carry.
    scale: float
    match_percentage: float
    ingredients: list[IngredientAvailability]


# === Picking ===


#: The most servings one run of a recipe may claim. A serving count is a pot
#: on a stove, not a quantity: without a ceiling the number reached the
#: database as an integer overflow.
MAX_SERVINGS = 200


class PickingStartRequest(BaseModel):
    servings: int = 1
    scale: Decimal | None = Field(default=None, gt=0, le=MAX_SCALE)
    """How much of the recipe to cook, stated as a multiplier. Wins over
    ``servings`` when both arrive."""
    meal_plan_entry_id: UUID | None = None
    """The meal-plan card Cook Now was pressed on, when the cook starts from
    one: the cook then completes that card and not a same-day sibling."""

    @field_validator('servings')
    @classmethod
    def servings_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError('servings must be >= 1')
        if v > MAX_SERVINGS:
            raise ValueError(f'servings must be <= {MAX_SERVINGS}')
        return v


class PickingItemSchema(BaseModel):
    ingredient_id: UUID
    name: str
    quantity_to_pick: float
    uom_symbol: str | None
    recommended_item_id: UUID | None
    location: str | None
    fefo_days_left: int | None
    fefo_expiry_date: str | None = None
    status: str  # pending | picked | skipped | missing | unknown
    is_linked: bool
    """Whether the ingredient points at a product template.

    Distinct from ``recommended_item_id``, which reports the best item found
    in stock — by link or by name. A linked ingredient that has run out has
    ``is_linked=True`` and no recommendation; an unlinked one matched by name
    has ``is_linked=False`` and a recommendation. Only the first of those is
    a broken link, and only it warrants asking the user to fix one."""


class PickingStartResponse(BaseModel):
    picking_session_id: UUID
    recipe_name: str
    servings: int
    # The multiplier the session cooks at, when it was started from one;
    # None is a portioned session, whose multiplier is derived from
    # ``servings``. Stated so the reader can tell the two apart and the
    # restart can re-derive the same sheet.
    scale: Decimal | None = None
    items_to_pick: list[PickingItemSchema]
    # True when this is a session that was already open, handed back instead of
    # thrown away. Starting used to cancel an unfinished session on sight,
    # which put the ingredients of a meal that had been cooked back on the
    # shelf — silently, on the next tap of "Get ingredients".
    resumed: bool = False


class PickingScanRequest(BaseModel):
    barcode: str | None = None
    item_id: UUID | None = None  # direct pick (override FEFO / disambiguation)
    #: ``item_id`` is the record the checklist recommends, not one the cook chose:
    #: an open pack beside a sealed one with an earlier date is still the
    #: cook's call.
    from_checklist: bool = False


class OpenedSuggestion(BaseModel):
    opened_item_id: UUID
    opened_quantity: float
    opened_uom: str | None
    opened_location: str | None
    opened_expiry: str | None


class DisambiguationCandidate(BaseModel):
    item_id: UUID
    quantity: float
    #: The unit the quantity is in (a record is kept in its card's unit).
    uom_id: UUID | None = None
    uom_symbol: str | None = None
    #: What one piece of the product weighs or holds, when its card records it:
    #: a quantity of 0.75 pcs on a 2 kg card is 1.5 kg left, and the screen
    #: says so instead of showing a fraction of a piece.
    piece_measure_value: float | None = None
    piece_measure_symbol: str | None = None
    expiry_date: str | None
    location: str | None
    recommended: bool = False
    #: The record is an opened package; ``opened_at`` is when it was opened.
    #: Beside a sealed pack with an earlier date it is the cook's choice.
    opened: bool = False
    opened_at: str | None = None


class UnitMismatch(BaseModel):
    """Both readings, when the recipe's measure and the shelf's cannot meet.

    Handed over instead of a consumed quantity: with nothing recording how
    the two units relate, any number picking took would be invented."""

    required_quantity: float
    required_uom: str | None
    available_quantity: float
    available_uom: str | None


class PickingScanResponse(BaseModel):
    # picked | disambiguation_required | not_in_recipe | already_picked
    # | fefo_mismatch | unit_mismatch
    status: str
    ingredient_id: UUID | None = None
    ingredient_name: str | None = None
    quantity_consumed: float | None = None
    uom_symbol: str | None = None
    item_remaining_quantity: float | None = None
    # How much more of this ingredient is still needed (partial picks); null when fully satisfied.
    ingredient_remaining_quantity: float | None = None
    message: str | None = None
    session_complete: bool = False
    opened_suggestion: OpenedSuggestion | None = None
    candidates: list[DisambiguationCandidate] | None = None
    # FEFO mismatch — user scanned a non-optimal item
    fefo_mismatch_days_left: int | None = None
    fefo_recommended_item_id: UUID | None = None
    fefo_recommended_expiry_date: str | None = None
    fefo_scanned_item_id: UUID | None = None
    # Unit mismatch — set only with status 'unit_mismatch'
    unit_mismatch: UnitMismatch | None = None


class UndoPickRequest(BaseModel):
    ingredient_id: UUID


class UndoPickResponse(BaseModel):
    ingredient_id: UUID
    ingredient_name: str
    restored_quantity: float
    uom_symbol: str | None = None
