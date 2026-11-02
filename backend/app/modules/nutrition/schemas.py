"""Pydantic shapes owned by the nutrition module.

``NutritionFacts`` used to live in ``vision/schemas.py``, in the same model as
``expiry_date`` and ``brand``, with the rule "for non-food items leave all
nutritional values as null" written into vision's prompt. That made the
generic label reader carry a food vertical's vocabulary, and every equipment
nameplate came back with six empty grams-per-100g.

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
