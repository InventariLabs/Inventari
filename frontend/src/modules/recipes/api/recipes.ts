import { recipesCoreApi } from "./recipes_core";
import { recipesCollectionsApi } from "./recipes_collections";
import { recipesIngredientsApi } from "./recipes_ingredients";
import { recipesLinkingApi } from "./recipes_linking";
import { recipesMealPlansApi } from "./recipes_mealplans";

export const recipesApi = {
  ...recipesCoreApi,
  ...recipesCollectionsApi,
  ...recipesIngredientsApi,
  ...recipesLinkingApi,
  ...recipesMealPlansApi,
};
