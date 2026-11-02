from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# === Tag Management ===


class RecipeTagItem(BaseModel):
    """A single tag with usage count and optional color."""

    name: str
    count: int
    color: str | None = None


class TagColorRequest(BaseModel):
    """A tag's colour, or ``null`` for no colour at all.

    ``null`` is a value here, not a missing field: the tag manager has offered
    a "clear colour" button since it was written, and with ``color: str`` the
    only reply that button could ever get was a 422. The column has always
    been nullable — it was the API that refused.
    """

    color: str | None = None

    @field_validator('color')
    @classmethod
    def validate_hex_color(cls, v: str | None) -> str | None:
        import re

        if v is None:
            return None
        if not re.match(r'^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$', v):
            raise ValueError(f'Invalid hex color {v!r}. Use #RGB or #RRGGBB format.')
        return v


class TagColorResponse(BaseModel):
    name: str
    color: str | None


class TagMergeRequest(BaseModel):
    old_tag: str
    new_tag: str


class TagMergeResponse(BaseModel):
    old_tag: str
    new_tag: str
    updated_recipes: int


class TagDeleteResponse(BaseModel):
    name: str
    updated_recipes: int


# === Ingredient Nutrition Defaults ===


class IngredientDefaultBase(BaseModel):
    name: str
    lang: str = 'en'
    calories_kcal: Decimal
    protein_g: Decimal | None = None
    fat_g: Decimal | None = None
    carbs_g: Decimal | None = None
    fiber_g: Decimal | None = None
    sugar_g: Decimal | None = None
    salt_g: Decimal | None = None


class IngredientDefaultCreate(IngredientDefaultBase):
    pass


class IngredientDefaultSchema(IngredientDefaultBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID | None
    name_normalized: str
    source: str
    is_system: bool
    created_at: datetime
    updated_at: datetime


class IngredientDefaultLookupResponse(BaseModel):
    found: bool
    name: str
    lang: str
    calories_kcal: Decimal | None = None
    protein_g: Decimal | None = None
    fat_g: Decimal | None = None
    carbs_g: Decimal | None = None
    fiber_g: Decimal | None = None
    sugar_g: Decimal | None = None
    salt_g: Decimal | None = None
    source: str | None = None
    # Inferred EU 1169/2011 allergens for the ingredient name
    allergens: list[str] = []


class ImportDefaultsResult(BaseModel):
    """What an import did, row by row: a new ingredient, an override founded
    over a system row, an existing override changed, or nothing."""

    created: int
    overridden: int
    updated: int
    unchanged: int
    errors: int


# === Unit Conversions ===


class UnitConversionBase(BaseModel):
    ingredient_key: str = Field(min_length=1)
    ingredient_name: str = Field(min_length=1)
    source_unit: str = Field(min_length=1)
    metric_quantity: Decimal = Field(gt=0)
    metric_unit: str = Field(min_length=1)
    category: str = 'other'
    lang: str = 'en'


class UnitConversionCreate(UnitConversionBase):
    pass


class UnitConversionUpdate(BaseModel):
    ingredient_key: str | None = None
    ingredient_name: str | None = None
    source_unit: str | None = None
    metric_quantity: Decimal | None = None
    metric_unit: str | None = None
    category: str | None = None


class UnitConversionSchema(UnitConversionBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID | None = None
    is_system: bool
