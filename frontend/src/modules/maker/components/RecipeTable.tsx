import { useId } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { FlaskConical } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { AvailabilityBadge } from "@/modules/maker/components/AvailabilityBadge";
import { RecipeUnitCost } from "@/modules/maker/components/RecipeUnitCost";
import { resultTerms } from "@/modules/maker/hooks/useResultTerms";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { useCanManage } from "@/hooks/useCanWrite";
import { formatMoney } from "@/utils/formatters";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { formatDate } from "@/utils/helpers";
import type { RecipeCatalogItem } from "@/modules/maker/types/maker";

interface RecipeTableProps {
  recipes: RecipeCatalogItem[];
  /** Ordering the catalog is currently in — reflected as `aria-sort` (§14.1). */
  sort: "newest" | "oldest" | "name";
  onProduce?: (recipe: RecipeCatalogItem) => void;
}

/**
 * The catalog as rows.
 *
 * The cards answer "what is this BOM" one at a time; the table answers "which
 * of them costs the most" by putting the numbers in a column the eye can run
 * down. Same data, same actions — only the arrangement differs, so nothing
 * here may be information the card does not carry.
 */
export function RecipeTable({ recipes, sort, onProduce }: RecipeTableProps) {
  const { t, i18n } = useTranslation("maker");
  const navigate = useNavigate();
  const currency = useOrganizationCurrency();
  // Same split as the card: producing is the page's `onProduce` (absent for
  // an account that may not), adding ingredients is the manager's.
  const canManage = useCanManage("maker");

  // The direction is an organisation-level setting, so the column has one
  // heading for every row; the first row that carries it decides the word.
  const resultTerm = resultTerms(
    t,
    recipes.find((r) => r.reference_direction !== null)?.reference_direction,
  );
  const resultDefinitionId = useId();

  // Headings stay on one line: "Unit cost" broken over two lines made the
  // header band twice as tall as the rows it labels.
  const headerClass =
    "px-3 py-2.5 font-medium text-on-secondary uppercase text-xs tracking-wide whitespace-nowrap";

  return (
    <Card className="overflow-hidden">
      <div className="relative overflow-x-auto">
        <table className="w-full text-sm min-w-[720px]">
          <thead>
            <tr className="border-b border-border text-left">
              <th
                scope="col"
                className={headerClass}
                aria-sort={sort === "name" ? "ascending" : undefined}
              >
                {t("catalog.table.name")}
              </th>
              <th scope="col" className={headerClass}>
                {t("catalog.table.ingredients")}
              </th>
              <th scope="col" className={headerClass}>
                {t("catalog.table.availability")}
              </th>
              <th scope="col" className={`${headerClass} text-right`}>
                {t("catalog.unitCost")}
              </th>
              <th
                scope="col"
                className={`${headerClass} text-right`}
                aria-describedby={resultDefinitionId}
              >
                {resultTerm.label}
              </th>
              <th
                scope="col"
                className={headerClass}
                aria-sort={
                  sort === "newest"
                    ? "descending"
                    : sort === "oldest"
                      ? "ascending"
                      : undefined
                }
              >
                {t("catalog.lastProduced")}
              </th>
              <th scope="col" className="px-3 py-2.5">
                <span className="sr-only">{t("catalog.table.actions")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {recipes.map((recipe) => {
              const result =
                recipe.result !== null && !Number.isNaN(Number(recipe.result))
                  ? Number(recipe.result)
                  : null;
              const hasIngredients = recipe.ingredient_count > 0;
              return (
                <tr
                  key={recipe.id}
                  className="border-b border-border last:border-0 hover:bg-surface-muted"
                >
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-2 min-w-0">
                      {recipe.output_template_image_url ? (
                        <img
                          src={recipe.output_template_image_url}
                          alt=""
                          className="shrink-0 w-8 h-8 rounded object-cover"
                        />
                      ) : (
                        <span className="shrink-0 w-8 h-8 rounded bg-accent/10 flex items-center justify-center">
                          <FlaskConical size={16} className="text-accent" />
                        </span>
                      )}
                      <span className="font-medium text-on truncate max-w-[220px]">
                        {/* The name is the row's one way in — a real link, so
                            Enter, the middle button and "open in a new tab"
                            all reach the recipe. The row-wide click it used
                            to carry ate all three. */}
                        <Link
                          to={`/maker/recipes/${recipe.id}`}
                          className="rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background hover:text-accent"
                        >
                          {recipe.name}
                        </Link>
                      </span>
                      {recipe.is_default && (
                        <span className="shrink-0 text-[10px] font-medium uppercase text-accent bg-accent/10 px-2 py-0.5 rounded-full">
                          {t("catalog.default")}
                        </span>
                      )}
                    </div>
                    {recipe.output_template_name && (
                      <span className="block text-xs text-on-muted truncate max-w-[260px]">
                        {recipe.output_template_name}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-on-secondary whitespace-nowrap">
                    {t("catalog.ingredientCount", {
                      count: recipe.ingredient_count,
                    })}
                  </td>
                  <td className="px-3 py-2.5">
                    {hasIngredients ? (
                      <AvailabilityBadge recipeId={recipe.id} />
                    ) : (
                      <span className="text-on-muted">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-right font-medium text-on whitespace-nowrap">
                    <RecipeUnitCost recipe={recipe} layout="stacked" />
                  </td>
                  <td
                    className={`px-3 py-2.5 text-right font-medium whitespace-nowrap ${
                      result === null
                        ? "text-on-muted"
                        : result >= 0
                          ? "text-accent-700 dark:text-accent-400"
                          : "text-red-600 dark:text-red-400"
                    }`}
                    data-testid="maker-recipe-row-result"
                  >
                    {result === null
                      ? "—"
                      : formatMoney(result, currency, i18n.language)}
                  </td>
                  <td className="px-3 py-2.5 text-on-muted whitespace-nowrap">
                    {recipe.last_produced_at
                      ? formatDate(recipe.last_produced_at)
                      : "—"}
                    {recipe.stock_qty !== null &&
                      Number(recipe.stock_qty) > 0 && (
                        <span className="block text-xs">
                          {t("catalog.stock")}:{" "}
                          {formatQuantityLocalized(t, recipe.stock_qty, null)}
                        </span>
                      )}
                  </td>
                  <td className="px-3 py-2.5 text-right whitespace-nowrap">
                    {/* Same rule as the card: a formula with no ingredients
                        cannot be produced, so the row offers the step that
                        unblocks it instead of an action that can only fail. */}
                    {/* Outline here too. The grid view stopped filling this
                        button; a list of 796 rows with a filled green button
                        on every one of them is the same wall by another
                        layout, and the screen's one primary CTA is in the
                        header (§11.4). */}
                    {hasIngredients && onProduce ? (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => onProduce(recipe)}
                      >
                        {t("catalog.produce")}
                      </Button>
                    ) : !hasIngredients && canManage ? (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => navigate(`/maker/recipes/${recipe.id}`)}
                        data-testid="maker-recipe-row-add-ingredients"
                      >
                        {t("catalog.addIngredients")}
                      </Button>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {/* Said under the table, not in a hover title: a title never reaches
          a keyboard or a finger. */}
      <p
        id={resultDefinitionId}
        className="border-t border-border px-3 py-2 text-xs text-on-muted"
      >
        {resultTerm.label}: {resultTerm.definition}
      </p>
    </Card>
  );
}
