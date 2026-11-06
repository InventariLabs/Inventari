"""RecipeService — CRUD + availability checking with fuzzy ingredient matching.

Ingredient matching logic:
  1. The ingredient's own template, when it has stock  -> status 'available'
  2. Best catalogue name matching the ingredient       -> status 'available_approx'
  3. Less of it on the shelf than asked for            -> status 'insufficient'
  4. Nothing on the shelf at all                       -> status 'missing'
  5. An ingredient whose name identifies nothing       -> status 'unknown'

This module is a thin facade. Implementation lives in:
  - ._crud         — create/get/list/update/delete
  - ._availability  — get_recipe_availability, _find_available_items,
                      _check_ingredient_availability, get_available_recipes,
                      build_stock_context
  - ._helpers       — FEFO/sort/serialization (private)
  - ._ingredient_matching — the lookup key and the catalogue matcher
  - ._uom_helpers  — UOM conversion (private; tests import _convert_qty_to_uom)
"""

from __future__ import annotations

from ._availability import (
    _check_ingredient_availability,
    _find_available_items,
    annotate_recipes_with_availability,
    build_stock_context,
    get_available_recipes,
    get_recipe_availability,
)
from ._crud import (
    bulk_delete_recipes,
    bulk_tag_recipes,
    create_recipe,
    delete_recipe,
    duplicate_recipe,
    get_recipe,
    list_recipes,
    update_recipe,
)
from ._helpers import set_recipe_image_url
from ._uom_helpers import _convert_qty_to_uom  # re-exported for tests

__all__ = [
    'create_recipe',
    'get_recipe',
    'list_recipes',
    'update_recipe',
    'delete_recipe',
    'duplicate_recipe',
    'bulk_delete_recipes',
    'bulk_tag_recipes',
    'get_recipe_availability',
    'build_stock_context',
    '_find_available_items',
    '_check_ingredient_availability',
    'get_available_recipes',
    'annotate_recipes_with_availability',
    'set_recipe_image_url',
    '_convert_qty_to_uom',
]
