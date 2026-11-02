"""Domain events published by the recipes module.

Canonical home of the ``recipe.*`` events. Cross-module subscribers should use
the plain string values (event names are contracts; importing another module's
code is not allowed).
"""

from enum import StrEnum


class RecipeEvent(StrEnum):
    RECIPE_CREATED = 'recipe.created'
    PICKING_COMPLETED = 'recipe.picking_completed'
    MEAL_PLAN_GENERATED = 'recipe.meal_plan_generated'
