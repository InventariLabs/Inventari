import { extractApiError } from "@/lib/errors";
import { useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, RefreshCw, ShoppingCart, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import {
  useRecipeAvailability,
  useAddToShoppingList,
  useOpenShoppingLists,
} from "../hooks/useRecipes";
import IngredientRow, { statusDot } from "./IngredientRow";
import { Button } from "@/components/ui/Button";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { useCanWrite } from "@/hooks/useCanWrite";
import ServingsSelector from "./ServingsSelector";
import { Card } from "@/components/ui/Card";
import { useModules } from "@/contexts/ModulesContext";
import type { IngredientAvailability } from "@/modules/recipes/types/core";
import { isSpiceQuantity } from "../utils";
import { onOtherListsMessage } from "@/modules/shared/lib/shoppingOverlap";

/**
 * Whether the list behind the button buys this ingredient for this recipe
 * alone: the backend adds a line exactly when the recipe asks for more than
 * the shelf covers, and these are the statuses that say so.
 *
 * The button and the list behind it answer one question, so they read one
 * set of statuses. "Not enough" belongs on this side of the line: a short
 * ingredient still has to be topped up. "Similar" does not — goods found by
 * the ingredient's name cover it as the meal plan counts them, so the
 * button adds what the legend's buy counts say, never "Missing 1" over a
 * click that also lists the similar ones.
 */
function needsBuying(
  status: IngredientAvailability["status"],
  comparable: boolean,
): boolean {
  return (
    !comparable ||
    status === "missing" ||
    status === "insufficient" ||
    status === "incomparable" ||
    status === "unknown"
  );
}

interface RecipeAvailabilityCheckerProps {
  recipeId: string;
  activeServings: number;
  onServingsChange: (n: number) => void;
}

export default function RecipeAvailabilityChecker({
  recipeId,
  activeServings,
  onServingsChange,
}: RecipeAvailabilityCheckerProps) {
  const { t } = useTranslation("recipes");

  const availabilityQuery = useRecipeAvailability(recipeId, activeServings);
  const avail = availabilityQuery.data;

  const addToShoppingListMutation = useAddToShoppingList(recipeId);
  const { data: openLists = [], isError: listsFailed } = useOpenShoppingLists();
  // The newest open list is the default; with several, the reader can name
  // another. A choice that has since left the open lists falls back to it.
  const [pickedListId, setPickedListId] = useState<string | null>(null);
  const targetListId =
    openLists.find((list) => list.id === pickedListId)?.id ?? openLists[0]?.id;
  // writing to a disabled module succeeded silently — the button
  // confirmed data the user could never reach. Gate the action on the
  // target module being enabled (the API write itself stays permissive so
  // existing integrations keep working).
  const { isModuleEnabled } = useModules();
  const shoppingListsEnabled = isModuleEnabled("shopping_lists");
  // Adding to a shopping list writes through `recipes:write`; the button was
  // offered to every reader whose installation has the module.
  const canWrite = useCanWrite("recipes");

  const handleAddToShoppingList = async () => {
    try {
      const result = await addToShoppingListMutation.mutateAsync({
        servings: activeServings,
        // reuse the chosen (by default the newest) open list instead of
        // letting the backend create a new one on every click; when there is
        // no open list the id is omitted and the backend creates the first one.
        ...(targetListId ? { shopping_list_id: targetListId } : {}),
      });
      // Nothing added because it is all on the list already: "Added 0
      // items" read as "nothing was missing" or as a failure.
      // A line topped up counts as written: the list changed by it.
      const written = result.added_count + (result.raised_count ?? 0);
      if (written === 0 && (result.already_listed_count ?? 0) > 0) {
        toast.info(
          t("shopping.already_listed_toast", {
            count: result.already_listed_count,
            list: result.list_name ?? "",
          }),
        );
        return;
      }
      toast.success(
        result.list_name
          ? t("shopping.added_toast", {
              count: written,
              list: result.list_name,
            })
          : t("shopping.added_toast_no_list", {
              count: written,
            }),
      );
      // The same goods may already stand on another open list.
      const overlap = onOtherListsMessage(t, result.on_other_lists);
      if (overlap) toast.warning(overlap);
    } catch (error) {
      toast.error(extractApiError(error, t("errors.shopping_failed")));
    }
  };

  // "Not comparable" is not "nothing missing" — an ingredient whose measure
  // cannot be put on one scale with the shelf's may or may not be covered,
  // and the button must not decide that it is. The same predicate covers
  // "Not enough", so the button is live exactly when the
  // backend would put a line on the list — the "Always at home" flag closes
  // the last gap: the backend skips those lines after the predicate, and
  // with it the door stayed open over a click that added zero lines.
  const hasMissing = avail?.ingredients.some(
    (i) => !i.excluded && needsBuying(i.status, i.quantities_comparable),
  );

  const [spicesExpanded, setSpicesExpanded] = useState(false);

  const { mainIngredients, spiceIngredients } = useMemo(() => {
    if (!avail?.ingredients)
      return { mainIngredients: [], spiceIngredients: [] };
    const main: IngredientAvailability[] = [];
    const spices: IngredientAvailability[] = [];
    for (const ing of avail.ingredients) {
      // The fold is by portion size, not by need: a seasoning that is not on
      // the shelf stays in view, or the footer says "Missing 1" about a name
      // that is only found behind a section labelled for its size.
      const short =
        !ing.excluded &&
        (ing.status === "missing" || ing.status === "insufficient");
      if (
        !short &&
        (ing.is_spice ||
          isSpiceQuantity(ing.required_quantity, ing.required_uom))
      )
        spices.push(ing);
      else main.push(ing);
    }
    return { mainIngredients: main, spiceIngredients: spices };
  }, [avail?.ingredients]);

  return (
    <Card className="p-0 shadow-sm">
      {/* Header: title + serving adjuster */}
      <div className="px-5 py-3 border-b border-border flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-on-secondary">
          {t("recipe.ingredients")}
        </h2>
        <ServingsSelector
          value={activeServings}
          onChange={onServingsChange}
          unit={t("recipe.servings_unit", { count: activeServings })}
          size="lg"
        >
          <Button
            size="icon"
            variant="ghost"
            onClick={() => availabilityQuery.refetch()}
            disabled={availabilityQuery.isFetching}
            className="ml-1"
            aria-label={t("a11y.refresh_availability")}
            title={t("a11y.refresh_availability")}
          >
            <RefreshCw
              size={16}
              className={availabilityQuery.isFetching ? "animate-spin" : ""}
            />
          </Button>
        </ServingsSelector>
      </div>

      {/* Ingredient rows */}
      <div className="px-5 py-1">
        {availabilityQuery.isLoading && (
          <div className="py-4 flex justify-center">
            <Loader2 size={18} className="animate-spin text-on-muted" />
          </div>
        )}
        {avail?.ingredients.length === 0 && (
          <p className="text-sm text-on-muted py-3">
            {t("recipe.no_ingredients")}
          </p>
        )}
        {mainIngredients.map((ing) => (
          <IngredientRow
            key={ing.ingredient_id}
            ingredient={ing}
            recipeId={recipeId}
          />
        ))}

        {/* Spices / seasonings — collapsible section */}
        {spiceIngredients.length > 0 && (
          <div className="mt-1">
            <Button
              size="content"
              variant="ghost"
              onClick={() => setSpicesExpanded((v) => !v)}
              aria-expanded={spicesExpanded}
              className="w-full justify-start px-0 py-2 min-h-11 md:min-h-10 text-xs text-on-muted"
            >
              <ChevronDown
                size={16}
                className={`transition-transform ${spicesExpanded ? "rotate-180" : ""}`}
              />
              {t("recipe.spices_section")} ({spiceIngredients.length})
            </Button>
            {spicesExpanded && (
              <div>
                {spiceIngredients.map((ing) => (
                  <IngredientRow
                    key={ing.ingredient_id}
                    ingredient={ing}
                    recipeId={recipeId}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Legend + shopping list */}
      {avail && avail.ingredients.length > 0 && (
        <div className="px-5 pb-3 pt-1 flex flex-col gap-2">
          {/* Subtle stock legend (only statuses present on the list) + compact CTA */}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-on-muted">
              {(
                [
                  "available",
                  "available_approx",
                  "insufficient",
                  "incomparable",
                  "missing",
                  "unknown",
                ] as const
              )
                .map((status) => ({
                  status,
                  count: avail.ingredients.filter((i) => i.status === status)
                    .length,
                }))
                .filter(({ count }) => count > 0)
                .map(({ status, count }) => (
                  <span
                    key={status}
                    className="flex items-center gap-1"
                    title={
                      status === "unknown"
                        ? t("availability.unknown_tooltip")
                        : status === "incomparable"
                          ? t("availability.incomparable_tooltip")
                          : undefined
                    }
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full inline-block ${
                        statusDot[status] ?? statusDot.unknown
                      }`}
                    ></span>
                    {/* "Unknown 3" alone does not say what it means —
                        unlinked ingredients get a self-explanatory label. */}
                    {status === "unknown"
                      ? t("availability.unknown_inline", { count })
                      : `${t(`availability.${status}`)} ${count}`}
                  </span>
                ))}
            </div>

            {shoppingListsEnabled && canWrite && (
              <div className="flex flex-wrap items-end gap-2">
                {openLists.length > 1 && (
                  <NativeSelect
                    label={t("shopping.target_list_label")}
                    value={targetListId}
                    onChange={(event) => setPickedListId(event.target.value)}
                    wrapperClassName="min-w-0 sm:max-w-56"
                  >
                    {openLists.map((list) => (
                      <option key={list.id} value={list.id}>
                        {list.name}
                      </option>
                    ))}
                  </NativeSelect>
                )}
                {listsFailed && (
                  <p role="alert" className="text-xs text-on-muted">
                    {t("shopping.lists_unavailable")}
                  </p>
                )}
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={handleAddToShoppingList}
                  disabled={!hasMissing || addToShoppingListMutation.isPending}
                  title={
                    !hasMissing
                      ? t("availability.add_missing_disabled_tooltip")
                      : undefined
                  }
                  className="shrink-0"
                >
                  {addToShoppingListMutation.isPending ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <ShoppingCart size={16} />
                  )}
                  {t("shopping.add_missing_button")}
                </Button>
              </div>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}
