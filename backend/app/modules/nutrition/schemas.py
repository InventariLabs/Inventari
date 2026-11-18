"""Pydantic shapes owned by the nutrition module.

``NutritionFacts`` lives here, apart from the generic label reader's model in
``vision/schemas.py``, so the reader carries no food vertical's vocabulary: an
equipment nameplate does not come back with six empty grams-per-100g.

The field descriptions are the prompt: Core renders them into the request
(:func:`app.core.llm.structured_extraction.build_shape_prompt`), so the
vocabulary lives beside the field it fills and cannot drift away from it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ['NutritionFacts']


class NutritionFacts(BaseModel):
    """A nutrition table as printed, normalised to 100 g / 100 ml."""

    energy_kcal: float | None = Field(None, description='kcal per 100g or 100ml')
    proteins: float | None = Field(None, description='protein, grams per 100g/100ml')
    fat: float | None = Field(None, description='fat, grams per 100g/100ml')
    saturated_fat: float | None = Field(
        None, description='saturated fat, grams per 100g/100ml'
    )
    carbohydrates: float | None = Field(
        None, description='carbohydrate, grams per 100g/100ml'
    )
    sugars: float | None = Field(None, description='sugars, grams per 100g/100ml')
    fiber: float | None = Field(None, description='fibre, grams per 100g/100ml')
    salt: float | None = Field(None, description='salt, grams per 100g/100ml')
    nova_group: int | None = Field(
        None, description='NOVA processing group, 1 to 4, only if determinable'
    )
    ingredients: str | None = Field(
        None, description='the ingredients list, verbatim as printed'
    )
