from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ._allergens import ALLERGEN_KEYS, ALLERGEN_SET

# === RecipeIngredient ===


class RecipeIngredientBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    template_id: UUID | None = None
    ingredient_group_name: str | None = None
    quantity: Decimal = Field(ge=0)
    uom_id: UUID | None = None
    is_optional: bool = False
    is_spice: bool = False
    """The cook's own mark from the import review: the amount alone may say
    "not a spice" and the mark overrules it. The card reads it beside the
    amount when it folds the seasonings section."""
    picking_skip: bool | None = None
    """The cook's explicit override of the picking auto-skip: ``True`` always
    skips, ``False`` never does, and ``None`` leaves it to the heuristic
    (optional or small spice amounts) — and it is the default, so an
    ingredient saved without an answer keeps the heuristic. The column is
    nullable and the demo rows carry that null — a named null is a real
    answer, not a validation
    error, so the form's round-trip of a seeded ingredient saves."""
    sort_order: int = 0
    calories_kcal_per_100g: Decimal | None = None
    display_text: str | None = None
    original_quantity: Decimal | None = None
    original_unit_text: str | None = None
    price: Decimal | None = None
    price_uom_id: UUID | None = None
    price_currency: str | None = None
    # EU 1169/2011 allergen keys
    allergens: list[str] = Field(default_factory=list)

    @field_validator('allergens')
    @classmethod
    def validate_allergens(cls, v: list[str]) -> list[str]:
        unknown = [a for a in v if a not in ALLERGEN_SET]
        if unknown:
            raise ValueError(f'Unknown allergen keys: {", ".join(sorted(unknown))}')
        return [key for key in ALLERGEN_KEYS if key in v]


class RecipeIngredientCreate(RecipeIngredientBase):
    id: UUID | None = None
    """Identity of an existing row when the client edits a recipe.

    An update carrying ids updates those rows in place instead of replacing
    the whole ingredient list — which is what keeps picking sessions attached
    to what they actually consumed. Omit it and the ingredient is created."""


class RecipeIngredient(RecipeIngredientBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    recipe_id: UUID

    # Enriched at read time
    uom_symbol: str | None = None


# === Recipe ===


class RecipeBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    instructions: str | None = None
    servings: int = Field(default=1, ge=1)
    prep_time_minutes: int | None = Field(default=None, ge=0)
    image_url: str | None = None
    source_url: str | None = None
    tags: list[str] | None = None
    is_favorite: bool = False

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        if '\x00' in v:
            raise ValueError('name must not contain null bytes')
        return v

    @field_validator('image_url')
    @classmethod
    def validate_image_url(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith(('http://', 'https://', '/')):
            raise ValueError('image_url must be a valid URL or relative path')
        return v


class RecipeCreate(RecipeBase):
    ingredients: list[RecipeIngredientCreate] = Field(
        default_factory=list, max_length=100
    )
    #: Where a picture for this recipe can be fetched from — an address on
    #: somebody else's server, supplied by an import. The server downloads it
    #: and sets ``image_url`` to its own copy; the address itself is never
    #: what the app shows, so that what a reader sees does not depend on what
    #: that server serves today, and opening a recipe does not announce the
    #: reader to a host they never chose.
    image_source_url: str | None = None

    @field_validator('image_source_url')
    @classmethod
    def validate_image_source_url(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith(('http://', 'https://')):
            raise ValueError('image_source_url must be an http(s) URL')
        return v

    @field_validator('source_url')
    @classmethod
    def validate_source_url(cls, v: str | None) -> str | None:
        """Only real web links — the frontend renders this straight into href.

        Validated on the way in rather than on ``RecipeBase``: rows written
        before this check must keep loading on read.
        """
        if v is not None and not v.startswith(('http://', 'https://')):
            raise ValueError('source_url must be an http(s) URL')
        return v


class RecipeBulkDeleteRequest(BaseModel):
    recipe_ids: list[UUID] = Field(min_length=1, max_length=200)


class RecipeBulkDeleteResponse(BaseModel):
    deleted: int


class RecipeBulkTagRequest(BaseModel):
    recipe_ids: list[UUID] = Field(min_length=1, max_length=200)
    tags: list[str] = Field(min_length=1, max_length=20)


class RecipeBulkTagResponse(BaseModel):
    updated: int


# === Recipe collections ===


class RecipeCollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    icon: str | None = Field(default=None, max_length=64)
    parent_id: UUID | None = None


class RecipeCollectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    icon: str | None = None
    parent_id: UUID | None = None


class RecipeCollectionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    icon: str | None = None
    parent_id: UUID | None = None
    recipe_count: int = 0
    children: list['RecipeCollectionSchema'] = []


class RecipeCollectionMemberRequest(BaseModel):
    recipe_id: UUID


class RecipeCollectionMemberResponse(BaseModel):
    collection_id: UUID
    recipe_id: UUID


class RecipeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    instructions: str | None = None
    servings: int | None = Field(default=None, ge=1)
    prep_time_minutes: int | None = Field(default=None, ge=0)
    image_url: str | None = None
    tags: list[str] | None = None
    is_favorite: bool | None = None
    ingredients: list[RecipeIngredientCreate] | None = None

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is not None and '\x00' in v:
            raise ValueError('name must not contain null bytes')
        return v


class Recipe(RecipeBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    source_url: str | None = None
    ingredients: list[RecipeIngredient] = []
    # Computed at read time as the union of ingredient allergens
    allergens: list[str] = []


class RecipeList(BaseModel):
    """Recipe in list view — lightweight, with availability badge."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None = None
    servings: int
    prep_time_minutes: int | None = None
    image_url: str | None = None
    tags: list[str] | None = None
    is_favorite: bool
    created_at: datetime
    source_url: str | None = None

    # Availability summary (filled by availability service)
    ingredients_total: int = 0
    ingredients_linked: int = 0
    ingredients_available: int = 0
    # Required lines whose measure could not be compared with the shelf's —
    # counted out of both "have" and "missing", so the card can name them
    # instead of letting "0 of 1" read as an empty shelf.
    ingredients_incomparable: int = 0
    missing_names: list[str] = []
    match_percentage: float | None = None
