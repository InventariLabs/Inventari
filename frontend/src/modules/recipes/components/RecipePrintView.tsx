import { useTranslation } from "react-i18next";
import { useAuthStore } from "@/store/authStore";
import { InstructionsView } from "./InstructionsView";
import { NUTRITION_COMPLETE_COVERAGE } from "./NutritionCard";
import {
  formatMoney,
  formatNumberLocale,
  formatQuantityLocale,
} from "@/utils/formatters";
import type { Recipe, RecipeIngredient } from "@/modules/recipes/types/core";
import type {
  RecipeCost,
  RecipeNutrition,
} from "@/modules/recipes/types/nutrition";
import { unitLabel } from "@/lib/i18nHelpers";
import { toAmount } from "@/utils/formatters";

interface RecipePrintViewProps {
  recipe: Recipe;
  servings: number;
  nutrition?: RecipeNutrition;
  cost?: RecipeCost;
  /** Fallback when the cost payload names no currency (the org's own). */
  currency?: string;
}

function formatQty(value: number | string): string {
  // The printout is read like any other screen: the shared formatter
  // decides the places and the decimal mark, and takes the wire's Decimal
  // string as-is.
  return formatQuantityLocale(value, 3);
}

function scaledIngredients(
  recipe: Recipe,
  servings: number,
): RecipeIngredient[] {
  const ratio = servings / Math.max(1, recipe.servings);
  return recipe.ingredients
    .filter((ing) => ing.name.trim())
    .map((ing) => ({
      ...ing,
      // The line's quantity crosses the wire as a Decimal string; the
      // scaled printout keeps that shape (the formatter reads both).
      quantity: String((toAmount(ing.quantity) ?? 0) * ratio),
    }));
}

/**
 * Allergens on paper — the sheet leaves the app, so the caveat travels with it,
 * and an empty list says so instead of reading as "contains none".
 */
function PrintAllergens({ allergens }: { allergens: string[] }) {
  const { t } = useTranslation("recipes");
  const marked = allergens.length > 0;
  return (
    <section className="mt-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide border-b border-border pb-1">
        {t("recipes:allergens.title")}
      </h2>
      {marked && (
        <p className="text-sm mt-1">
          {allergens.map((key) => t(`recipes:allergens.${key}`)).join(", ")}
        </p>
      )}
      <p className="text-xs mt-1 italic" data-testid="print-allergen-note">
        {marked
          ? t("recipes:allergens.note")
          : t("recipes:allergens.none_marked")}
      </p>
    </section>
  );
}

/**
 * Unknown calories are said in words: a zero here is a figure nobody measured,
 * on a sheet with no screen around it to contradict it. A measured 0 stays a 0.
 */
function PrintCalories({ value }: { value?: number | string | null }) {
  const { t } = useTranslation("recipes");
  const calories = toAmount(value);
  return (
    <span>
      {calories == null
        ? t("recipes:print.calories_unknown")
        : `${Math.round(calories)} kcal`}
    </span>
  );
}

/** A nutrient nobody measured prints a dash, as the screen does, not "—g". */
function printGrams(value?: number | null): string {
  return value != null ? `${formatNumberLocale(value, 1)}g` : "–";
}

/** The estimate caveat under the nutrition line; it names generic values when used. */
function PrintNutritionEstimate({ generic }: { generic?: boolean }) {
  const { t } = useTranslation("recipes");
  return (
    <p className="text-xs mt-1 italic" data-testid="print-nutrition-estimate">
      {t(
        generic
          ? "recipes:nutrition.estimate_generic_note"
          : "recipes:nutrition.estimate_note",
      )}
    </p>
  );
}

/** Print-only recipe card — hidden on screen, full A4 card in print. */
export function RecipePrintView({
  recipe,
  servings,
  nutrition,
  cost,
  currency,
}: RecipePrintViewProps) {
  const { t, i18n } = useTranslation(["recipes", "common"]);
  const lang = i18n.language?.substring(0, 2) ?? "en";
  const orgName = useAuthStore((s) => s.user?.organization_name);

  const ingredients = scaledIngredients(recipe, servings);
  const printedOn = new Date().toLocaleDateString(i18n.language ?? "en", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  const nutritionSummary =
    nutrition && nutrition.coverage > 0 ? nutrition.per_serving : null;
  // The screen's card says so when some ingredients have no nutrition data;
  // paper is read without the card beside it, so the printout says it too.
  const nutritionIsPartial =
    nutritionSummary != null &&
    nutrition != null &&
    nutrition.coverage < NUTRITION_COMPLETE_COVERAGE;
  const costPerServing =
    cost?.estimated_cost != null
      ? cost.estimated_cost / Math.max(1, servings)
      : null;

  return (
    <div className="hidden print:block">
      <div className="p-8 font-sans text-black">
        {/* Header */}
        <div className="flex items-start justify-between border-b-2 border-black pb-3">
          <div>
            <h1 className="text-xl font-semibold">{recipe.name}</h1>
            <p className="text-xs mt-1">
              {t("recipes:recipe.servings", {
                count: servings,
              })}{" "}
              ·{" "}
              {recipe.prep_time_minutes != null &&
                t("recipes:recipe.prep_time", {
                  minutes: recipe.prep_time_minutes,
                })}
            </p>
          </div>
          <div className="text-right text-xs">
            {orgName && <p className="font-medium">{orgName}</p>}
            <p className="text-gray-600">
              {t("recipes:print.printed_on", { date: printedOn })}
            </p>
          </div>
        </div>

        {/* Ingredients */}
        <section className="mt-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide border-b border-border pb-1">
            {t("recipes:recipe.ingredients")}
          </h2>
          <table className="w-full text-sm mt-2">
            <tbody>
              {ingredients.map((ing) => (
                <tr key={ing.id ?? ing.name} className="border-b border-border">
                  <td className="py-1 pr-2 font-medium">{ing.name}</td>
                  <td className="py-1 text-right whitespace-nowrap">
                    {formatQty(ing.quantity)} {unitLabel(t, ing.uom_symbol)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <PrintAllergens allergens={recipe.allergens ?? []} />

        {/* Nutrition + cost per serving */}
        {(nutritionSummary || costPerServing != null) && (
          <section className="mt-3">
            <h2 className="text-sm font-semibold uppercase tracking-wide border-b border-border pb-1">
              {t("recipes:print.per_serving")}
            </h2>
            <div className="text-sm mt-1 flex flex-wrap gap-x-4 gap-y-0.5">
              {nutritionSummary && (
                <>
                  <PrintCalories value={nutritionSummary.calories_kcal} />
                  {/* The macros are written exactly as the screen writes them
                      (one decimal, the reader's mark) — paper is read like a
                      screen, and `Math.round` gave the same number a second
                      shape on the same path. */}
                  <span>
                    {t("recipes:nutrition.protein")}:{" "}
                    {printGrams(nutritionSummary.protein_g)}
                  </span>
                  <span>
                    {t("recipes:nutrition.carbs")}:{" "}
                    {printGrams(nutritionSummary.carbs_g)}
                  </span>
                  <span>
                    {t("recipes:nutrition.fat")}:{" "}
                    {printGrams(nutritionSummary.fat_g)}
                  </span>
                  <span>
                    {t("recipes:nutrition.fiber")}:{" "}
                    {printGrams(nutritionSummary.fiber_g)}
                  </span>
                  <span>
                    {t("recipes:nutrition.sugar")}:{" "}
                    {printGrams(nutritionSummary.sugar_g)}
                  </span>
                  <span>
                    {t("recipes:nutrition.salt")}:{" "}
                    {printGrams(nutritionSummary.salt_g)}
                  </span>
                </>
              )}
              {costPerServing != null && (
                <span>
                  {t("recipes:cost.title")}:{" "}
                  {/* The printout carried a hardcoded "PLN" — the same bug
                      as on the hero card, on paper. */}
                  {formatMoney(
                    costPerServing,
                    cost?.currency ?? currency,
                    lang,
                  )}
                </span>
              )}
            </div>
            {nutritionSummary && (
              <PrintNutritionEstimate generic={nutrition?.generic_values} />
            )}
            {nutritionIsPartial && nutrition && (
              <p
                className="text-xs mt-1 italic"
                data-testid="print-nutrition-partial"
              >
                {t("recipes:nutrition.incomplete_warning", {
                  pct: Math.round(nutrition.coverage * 100),
                })}
              </p>
            )}
          </section>
        )}

        {/* Instructions */}
        {recipe.instructions && (
          <section className="mt-3">
            <h2 className="text-sm font-semibold uppercase tracking-wide border-b border-border pb-1">
              {t("recipes:recipe.instructions")}
            </h2>
            <div className="text-sm mt-2 [&_p]:mb-1.5 [&_li]:mb-0.5">
              <InstructionsView text={recipe.instructions} />
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
