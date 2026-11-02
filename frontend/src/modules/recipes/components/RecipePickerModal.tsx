import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { ChefHat, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Sheet, SheetHeader } from "@/components/ui/Sheet";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
  TabsPanels,
} from "@/components/ui/Tabs";
import { AvailabilityBadge, SuggestedRecipes } from "./SuggestedRecipes";
import { useMealPlanSuggestions } from "@/modules/recipes/hooks/useMealPlanSuggestions";
import { useRecipes } from "@/modules/recipes/hooks/useRecipes";
import type { RecipeList } from "@/modules/recipes/types/core";
import { QueryFailure } from "@/components/ui/QueryResult";
import type {
  MealSlot,
  SuggestedRecipe,
} from "@/modules/recipes/types/mealplans";

interface RecipePickerModalProps {
  isOpen: boolean;
  date: string;
  slot: MealSlot;
  planId: string;
  onSelect: (recipeId: string, recipeName: string) => void;
  onClose: () => void;
  /** Whether the reader may create a recipe from the empty picker. */
  canWrite?: boolean;
}

export function RecipePickerModal({
  isOpen,
  date,
  slot,
  planId,
  onSelect,
  onClose,
  canWrite = true,
}: RecipePickerModalProps) {
  const { t } = useTranslation("recipes");
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [activeTab, setActiveTab] = useState("suggested");
  const panelsRef = useRef<HTMLDivElement>(null);

  const {
    data: suggestions = [],
    isLoading: loadingSuggestions,
    isError: suggestionsFailed,
  } = useMealPlanSuggestions({
    date,
    slot,
    count: 10,
    plan_id: planId,
  });

  const {
    data,
    isError: recipesFailed,
    error: recipesError,
    refetch: refetchRecipes,
  } = useRecipes({ search: search || undefined });
  const allRecipes = data?.items ?? [];

  // Never land on an empty "Suggested" tab — fall back to all recipes
  useEffect(() => {
    // A failed suggestion read is not "nothing was suggested". Moving the
    // reader to another tab on account of it hides that anything went wrong.
    if (
      activeTab === "suggested" &&
      !loadingSuggestions &&
      !suggestionsFailed &&
      suggestions.length === 0
    ) {
      setActiveTab("all");
    }
  }, [activeTab, loadingSuggestions, suggestionsFailed, suggestions.length]);

  function handleSuggestionSelect(recipe: SuggestedRecipe) {
    onSelect(recipe.recipe_id, recipe.name);
    onClose();
  }

  function handleRecipeSelect(recipe: RecipeList) {
    onSelect(recipe.id, recipe.name);
    onClose();
  }

  if (!isOpen) return null;

  return (
    <Sheet
      open={isOpen}
      onClose={onClose}
      zIndex="confirm"
      maxWidth="lg"
      aria-label={t("meal_planner.pick_recipe")}
    >
      <SheetHeader
        title={t("meal_planner.pick_recipe")}
        onClose={onClose}
        className="p-4"
      />

      <Tabs
        defaultValue="suggested"
        value={activeTab}
        onValueChange={(tab) => {
          setActiveTab(tab);
          // The panels share one scroll area, so the other list would open at
          // wherever this one was scrolled to.
          if (panelsRef.current) panelsRef.current.scrollTop = 0;
        }}
        className="flex-1 flex flex-col overflow-hidden"
      >
        <TabsList className="mx-4 mt-3 shrink-0">
          <TabsTrigger value="suggested">
            {t("meal_planner.tab_suggested")}
          </TabsTrigger>
          <TabsTrigger value="all">{t("meal_planner.tab_all")}</TabsTrigger>
        </TabsList>

        {/* One scroll area for both panels, stacked in one cell: the sheet is
            as tall as the taller list (up to the viewport) on either tab,
            instead of jumping as the tabs swap. */}
        <div ref={panelsRef} className="flex-1 overflow-y-auto">
          <TabsPanels>
            <TabsContent value="suggested" stacked className="mt-0 p-4">
              <SuggestedRecipes
                suggestions={suggestions}
                isLoading={loadingSuggestions}
                onSelect={handleSuggestionSelect}
                t={t}
              />
            </TabsContent>

            <TabsContent value="all" stacked className="mt-0 p-4">
              {/* The column lives in its own box: a stacked panel is `block`
                  while hidden and the panel's own layout would differ between
                  the two states, which is exactly the jump this removes. */}
              <div className="flex min-w-0 flex-col gap-3">
                <Input
                  leftIcon={<Search size={14} />}
                  aria-label={t("meal_planner.search_recipes")}
                  placeholder={t("meal_planner.search_recipes")}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                {recipesFailed ? (
                  <QueryFailure
                    error={recipesError}
                    onRetry={() => refetchRecipes()}
                  />
                ) : allRecipes.length === 0 ? (
                  <EmptyState
                    variant="compact"
                    icon={ChefHat}
                    title={
                      search ? t("empty.no_results") : t("empty.no_recipes")
                    }
                    description={
                      search
                        ? t("empty.no_results_desc")
                        : t("empty.no_recipes_desc")
                    }
                    primaryAction={
                      <div className="flex items-center gap-2">
                        <Button variant="ghost" size="sm" onClick={onClose}>
                          {t("common:actions.cancel")}
                        </Button>
                        {!search && canWrite && (
                          <Button
                            size="sm"
                            onClick={() => {
                              onClose();
                              navigate("/recipes?new=1");
                            }}
                          >
                            {t("actions.new_recipe")}
                          </Button>
                        )}
                      </div>
                    }
                  />
                ) : (
                  <div className="flex flex-col gap-2">
                    {allRecipes.map((recipe) => (
                      <Button
                        key={recipe.id}
                        type="button"
                        variant="outline"
                        size="row"
                        onClick={() => handleRecipeSelect(recipe)}
                        className="hover:border-accent hover:bg-accent/5 transition-colors"
                      >
                        {recipe.image_url ? (
                          <img
                            src={recipe.image_url}
                            alt={recipe.name}
                            loading="lazy"
                            className="w-10 h-10 rounded object-cover flex-shrink-0"
                          />
                        ) : (
                          <div className="w-10 h-10 rounded bg-surface-inset flex-shrink-0" />
                        )}
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium truncate">
                            {recipe.name}
                          </p>
                          {recipe.ingredients_total > 0 && (
                            <div className="mt-0.5">
                              <AvailabilityBadge
                                available={recipe.ingredients_available}
                                total={recipe.ingredients_total}
                              />
                            </div>
                          )}
                        </div>
                      </Button>
                    ))}
                  </div>
                )}
              </div>
            </TabsContent>
          </TabsPanels>
        </div>
      </Tabs>
    </Sheet>
  );
}
