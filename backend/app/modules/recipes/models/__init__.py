"""Recipes models package — re-exports all model classes.

Import as: ``from app.modules.recipes.models import Recipe, RecipeIngredient, ...``
"""

from .collections import RecipeCollection, RecipeCollectionMember
from .extras import (
    IngredientNutritionDefault,
    RecipeTagConfig,
    UnitConversion,
)
from .meal_plan import (
    MealPlan,
    MealPlanEntry,
    ShoppingExclusion,
)
from .picking import (
    PickingSession,
    PickingSessionItem,
)
from .recipe import (
    MealSlot,
    Recipe,
    RecipeIngredient,
)

__all__ = [
    'IngredientNutritionDefault',
    'MealPlan',
    'MealPlanEntry',
    'MealSlot',
    'PickingSession',
    'PickingSessionItem',
    'Recipe',
    'RecipeCollection',
    'RecipeCollectionMember',
    'RecipeIngredient',
    'RecipeTagConfig',
    'ShoppingExclusion',
    'UnitConversion',
]
