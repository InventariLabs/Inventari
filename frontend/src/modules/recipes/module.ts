import { lazy } from "react";
import { ChefHat, Calendar, Database, Link2Off, Settings } from "lucide-react";
import { moduleRegistry } from "@/lib/moduleRegistry";
import type { SearchResult } from "@/lib/moduleRegistry";
import { recipesApi } from "./api/recipes";
import type { RecipeList } from "./types/core";

const RecipesPage = lazy(() => import("./pages/RecipesPage"));
const RecipeDetailPage = lazy(() => import("./pages/RecipeDetailPage"));
const RecipeSettingsPage = lazy(() => import("./pages/RecipeSettingsPage"));
const RecipesModuleSettingsPage = lazy(
  () => import("./pages/RecipesModuleSettingsPage"),
);
const MealPlannerPage = lazy(() => import("./pages/MealPlannerPage"));
const MealPlanDetailPage = lazy(() => import("./pages/MealPlanDetailPage"));
const UnlinkedIngredientsPage = lazy(
  () => import("./pages/UnlinkedIngredientsPage"),
);

function recipeToResult(recipe: RecipeList): SearchResult {
  return {
    id: `recipe-${recipe.id}`,
    title: recipe.name,
    path: `/recipes/${recipe.id}`,
    module: "recipes",
  };
}

moduleRegistry.register({
  name: "recipes",
  launcher: {
    displayName: "recipes:launcher.title",
    description: "recipes:launcher.description",
    icon: ChefHat,
    color: "bg-orange-500",
    category: "business",
    order: 30,
  },
  moduleNav: {
    basePath: "/recipes",
    items: [
      {
        path: "/recipes",
        icon: ChefHat,
        labelKey: "recipes:navigation.recipes",
        titleKey: "recipes:page.title",
        subtitleKey: "recipes:page.subtitle",
        order: 10,
      },
      {
        path: "/recipes/unlinked-ingredients",
        icon: Link2Off,
        labelKey: "recipes:navigation.unlinkedIngredients",
        titleKey: "recipes:linking.title",
        order: 20,
      },
      {
        path: "/recipes/ingredient-data",
        icon: Database,
        labelKey: "recipes:navigation.ingredientData",
        titleKey: "recipes:settings.page_title",
        order: 40,
      },
      {
        path: "/recipes/settings",
        icon: Settings,
        labelKey: "recipes:navigation.settings",
        titleKey: "recipes:settings.module_title",
        // Module settings are read and written by an admin-only endpoint.
        roles: ["admin"],
        // Settings sit last in the module bar, always (UI_GUIDELINES §2.14).
        order: 90,
      },
      {
        path: "/recipes/meal-planner",
        icon: Calendar,
        labelKey: "recipes:meal_planner.page_title",
        titleKey: "recipes:meal_planner.page_title",
        order: 30,
      },
    ],
  },
  routes: [
    { path: "/recipes", component: RecipesPage },
    { path: "/recipes/settings", component: RecipesModuleSettingsPage },
    { path: "/recipes/ingredient-data", component: RecipeSettingsPage },
    {
      path: "/recipes/unlinked-ingredients",
      component: UnlinkedIngredientsPage,
    },
    { path: "/recipes/:id", component: RecipeDetailPage },
    { path: "/recipes/meal-planner", component: MealPlannerPage },
    { path: "/recipes/meal-planner/:id", component: MealPlanDetailPage },
  ],
  standalone: {
    coreSections: {
      labels: "renounce",
      scan: "renounce",
      stats: "renounce",
      stock_takes: "renounce",
      archive: "renounce",
    },
    backgroundFeatures: [
      {
        provider: "inventory",
        feature: "stock",
        labelKey: "recipes:background.pantry",
      },
      {
        provider: "shopping_lists",
        feature: "active_list",
        labelKey: "recipes:background.shopping",
      },
    ],
  },
  // No `settings_ai_module_config` slot: the AI screen already lists every
  // purpose in its bindings grid, so a module-branded section rendered the
  // same select twice on one screen. The module-local editor lives on
  // /recipes/settings (RecipesAiSettings).
  searchProvider: async (query: string): Promise<SearchResult[]> => {
    const { items } = await recipesApi.list({ search: query, limit: 5 });
    return items.slice(0, 5).map(recipeToResult);
  },
});
