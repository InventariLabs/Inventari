"""Recipes module Pydantic schemas.

Re-exports all public schema classes so existing
``from app.modules.recipes.schemas import X`` keeps working.

Sub-modules:
- _schemas_recipe.py: RecipeIngredient, Recipe
- _schemas_picking.py: Availability, Picking
- _schemas_io.py: Nutrition, Shopping, Cooking, Image, Cost, Import/Export
- _schemas_admin.py: Tags, IngredientDefault, UnitConversion
- _schemas_meal_planner.py: MealPlanner, ShoppingExclusions
"""

from ._schemas_admin import (  # noqa: F401
    ImportDefaultsResult,
    IngredientDefaultBase,
    IngredientDefaultCreate,
    IngredientDefaultLookupResponse,
    IngredientDefaultSchema,
    RecipeTagItem,
    TagColorRequest,
    TagColorResponse,
    TagDeleteResponse,
    TagMergeRequest,
    TagMergeResponse,
    UnitConversionBase,
    UnitConversionCreate,
    UnitConversionSchema,
    UnitConversionUpdate,
)
from ._schemas_io import (  # noqa: F401
    AddFromRecipesRequest,
    AddToShoppingListRequest,
    AddToShoppingListResponse,
    CookingHistoryItem,
    IngredientCost,
    IngredientNutrition,
    LinkIngredientTemplateRequest,
    ListedElsewhere,
    NutritionSummary,
    PatchCookingHistoryRequest,
    PreviewIngredient,
    RecipeCost,
    RecipeExportIngredient,
    RecipeImageResponse,
    RecipeImportIngredient,
    RecipeImportRequest,
    RecipeNutrition,
    RecipePreview,
    RecordCookingRequest,
)
from ._schemas_meal_planner import (  # noqa: F401
    BulkEntriesSave,
    CopyPlanRequest,
    CopyPlanResponse,
    DailyNutritionSummary,
    MealPlanCreate,
    MealPlanEntryCreate,
    MealPlanEntrySchema,
    MealPlanEntryUpdate,
    MealPlanListItem,
    MealPlanSchema,
    MealPlanUpdate,
    ShoppingExclusionCreate,
    ShoppingExclusionSchema,
    ShoppingListGenerationResult,
    SuggestedRecipe,
    _GeneratedItem,
)
from ._schemas_picking import (  # noqa: F401
    BestItemSchema,
    DisambiguationCandidate,
    IngredientAvailability,
    OpenedSuggestion,
    PickingItemSchema,
    PickingScanRequest,
    PickingScanResponse,
    PickingStartRequest,
    PickingStartResponse,
    RecipeAvailability,
    UndoPickRequest,
    UndoPickResponse,
    UnitMismatch,
)
from ._schemas_recipe import (  # noqa: F401
    Recipe,
    RecipeBase,
    RecipeBulkDeleteRequest,
    RecipeBulkDeleteResponse,
    RecipeBulkTagRequest,
    RecipeBulkTagResponse,
    RecipeCollectionCreate,
    RecipeCollectionMemberRequest,
    RecipeCollectionMemberResponse,
    RecipeCollectionSchema,
    RecipeCollectionUpdate,
    RecipeCreate,
    RecipeIngredient,
    RecipeIngredientBase,
    RecipeIngredientCreate,
    RecipeList,
    RecipeUpdate,
)
