"""Schemas of a product's label: its facts, and what its recipe makes of them."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .labelling import ALLERGEN_KEYS


def _known(keys: list[str]) -> list[str]:
    unknown = sorted(set(keys) - set(ALLERGEN_KEYS))
    if unknown:
        raise ValueError(f'Unknown allergen keys: {", ".join(unknown)}')
    return keys


class LabelFactsUpdate(BaseModel):
    """Input for PUT /labelling/products/{template_id}.

    ``allergens`` set to ``null`` says nobody has checked them; an empty list
    says the product contains none. Leaving everything empty clears the card.
    """

    label_name: str | None = Field(None, max_length=255)
    allergens: list[str] | None = Field(None, max_length=14)
    may_contain: list[str] = Field(default_factory=list, max_length=14)

    @field_validator('allergens')
    @classmethod
    def _allergens_known(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _known(value)

    @field_validator('may_contain')
    @classmethod
    def _may_contain_known(cls, value: list[str]) -> list[str]:
        return _known(value)


class LabelIngredientRef(BaseModel):
    """An ingredient named beside an allergen, a missing figure or a doubt."""

    template_id: UUID
    name: str


class LabelAllergen(BaseModel):
    """One allergen of a made product: the ingredients that bring it, and
    whether the product's own card declares it."""

    allergen: str
    sources: list[LabelIngredientRef]
    declared_on_product: bool


class LabelFactsRead(BaseModel):
    """What a product's card says for its label, and what its recipe adds.

    ``suggested_allergens`` is what the product's name suggests, for a person
    to confirm. ``derived_*`` come from the product's default recipe when it
    is made (``recipe_id``), each with the ingredients that bring it.
    """

    product_template_id: UUID
    label_name: str | None
    allergens: list[str] | None
    may_contain: list[str]
    suggested_allergens: list[str]
    recipe_id: UUID | None = None
    derived_allergens: list[LabelAllergen] = Field(default_factory=list)
    derived_may_contain: list[LabelAllergen] = Field(default_factory=list)


class LabelIngredient(BaseModel):
    """One entry of an ingredient list, heaviest first.

    ``weight_g`` is what the parent's batch uses, its loss included; null when
    nothing says what the ingredient weighs. ``emphasised``: its card names an
    allergen. ``children``: a made ingredient's own list, in brackets.
    """

    template_id: UUID
    name: str
    weight_g: Decimal | None
    emphasised: bool
    children: list[LabelIngredient] = Field(default_factory=list)


class LabelUnchecked(BaseModel):
    """An ingredient nobody has checked for allergens, and what its name suggests."""

    template_id: UUID
    name: str
    suggested_allergens: list[str]


class LabelNutrientGap(BaseModel):
    """An ingredient without some of the figures the declaration needs."""

    template_id: UUID
    name: str
    nutrients: list[str]


class LabelNutrition(BaseModel):
    """The nutrition declaration per 100 g of the made product.

    A figure is null when an ingredient lacks it (named in ``missing``), when
    an ingredient cannot be weighed, or when the batch's weight is not known.
    """

    energy_kj: Decimal | None
    energy_kcal: Decimal | None
    fat: Decimal | None
    saturates: Decimal | None
    carbohydrate: Decimal | None
    sugars: Decimal | None
    protein: Decimal | None
    salt: Decimal | None
    missing: list[LabelNutrientGap]


class RecipeLabelRead(BaseModel):
    """A made product's label, computed from one recipe.

    ``text`` is the list and the allergens as a label prints them (allergens
    in capitals). ``yield_weight_g`` is what the batch weighs when it comes
    out; null when neither the recipe's yield nor the product's card says.
    ``nutrition`` is null when no ingredient carries a figure.
    """

    recipe_id: UUID
    output_template_id: UUID
    ingredients: list[LabelIngredient]
    text: str | None
    allergens: list[LabelAllergen]
    may_contain: list[LabelAllergen]
    unchecked: list[LabelUnchecked]
    unweighed: list[LabelIngredientRef]
    yield_weight_g: Decimal | None
    nutrition: LabelNutrition | None
