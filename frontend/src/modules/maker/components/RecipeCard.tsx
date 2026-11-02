import { useTranslation } from "react-i18next";
import { FlaskConical, Package } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { useCanManage } from "@/hooks/useCanWrite";
import { formatMoney } from "@/utils/formatters";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import type { RecipeCatalogItem } from "@/modules/maker/types/maker";
import { formatDate } from "@/utils/helpers";
import { AvailabilityBadge } from "@/modules/maker/components/AvailabilityBadge";
import { RecipeUnitCost } from "@/modules/maker/components/RecipeUnitCost";
import { resultTerms } from "@/modules/maker/hooks/useResultTerms";

interface RecipeCardProps {
  recipe: RecipeCatalogItem;
  onProduce?: (recipe: RecipeCatalogItem) => void;
}

export function RecipeCard({ recipe, onProduce }: RecipeCardProps) {
  const { t, i18n } = useTranslation("maker");
  const navigate = useNavigate();
  const currency = useOrganizationCurrency();
  // Adding ingredients writes the formula — the manager's side of the split.
  const canManage = useCanManage("maker");

  const hasStock = recipe.stock_qty !== null && Number(recipe.stock_qty) > 0;
  const hasIngredients = recipe.ingredient_count > 0;

  // Financial outcome per unit of output, named the way every production
  // screen names it.
  const result =
    recipe.result !== null && !Number.isNaN(Number(recipe.result))
      ? Number(recipe.result)
      : null;
  const resultTerm = resultTerms(t, recipe.reference_direction);

  return (
    <Card
      className="p-4 flex flex-col gap-3 hover:border-accent transition-colors"
      data-testid="maker-recipe-card"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {/* The product's thumbnail in the place the flask icon held: when
              the product has no picture the icon stands in for it. */}
          {recipe.output_template_image_url ? (
            <img
              src={recipe.output_template_image_url}
              alt=""
              className="flex-shrink-0 w-10 h-10 rounded-lg object-cover"
            />
          ) : (
            <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-accent/10 flex items-center justify-center">
              <FlaskConical size={20} className="text-accent" />
            </div>
          )}
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-on truncate">
              {/* A link, not an onClick heading: the card title was
                  unreachable by keyboard and could not be opened in a tab. */}
              <Link
                to={`/maker/recipes/${recipe.id}`}
                className="hover:text-accent focus-visible:text-accent"
              >
                {recipe.name}
              </Link>
            </h3>
            {recipe.output_template_name && (
              <p className="text-xs text-on-muted truncate">
                {recipe.output_template_name}
              </p>
            )}
          </div>
        </div>
        {recipe.is_default && (
          <span className="text-[10px] font-medium text-accent bg-accent/10 px-2 py-0.5 rounded-full">
            {t("catalog.default")}
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2 text-sm">
        <div className="flex items-center gap-1.5 text-on-muted">
          <Package size={14} />
          <span>
            {t("catalog.ingredientCount", {
              count: recipe.ingredient_count,
              defaultValue: `${recipe.ingredient_count} ingredients`,
            })}
          </span>
        </div>
        <div className="text-right">
          <RecipeUnitCost recipe={recipe} />
        </div>
        {hasStock && (
          <div className="text-on-muted">
            {t("catalog.stock")}:{" "}
            <span className="text-on font-medium tabular-nums">
              {formatQuantityLocalized(t, recipe.stock_qty, null)}
            </span>
          </div>
        )}
        {recipe.last_produced_at && (
          <div className="text-on-muted text-xs">
            {t("catalog.lastProduced")}: {formatDate(recipe.last_produced_at)}
          </div>
        )}
      </div>

      {hasIngredients && <AvailabilityBadge recipeId={recipe.id} />}

      {result !== null && (
        <div
          data-testid="maker-recipe-card-result"
          className={[
            "flex items-center justify-between gap-2 text-sm rounded-lg px-2.5 py-1.5",
            result >= 0
              ? "bg-accent-50 text-accent-700"
              : "bg-red-50 text-red-600",
          ].join(" ")}
        >
          <span className="min-w-0">
            <span className="block font-medium">{resultTerm.label}</span>
            <span className="block text-xs opacity-80">
              {resultTerm.definition}
            </span>
          </span>
          <span className="font-medium tabular-nums shrink-0">
            {formatMoney(result, currency, i18n.language)}
          </span>
        </div>
      )}

      {/* Outline, not filled. §11.4 gives a screen one primary CTA and this
          one already has it in the header ("New formula"). Repeated once per
          card down a grid of hundreds, the filled variant stopped marking the
          important action and became the background the records sit on. */}
      <div className="flex gap-2 mt-auto pt-2">
        {/* Producing from a formula with no ingredients is refused by the
            server (it would create output against zero consumption), so the
            card asks for the one thing that unblocks it instead of offering
            an action that can only fail. The fix is a formula edit, which is
            the manager's — a member gets the details instead of a CTA whose
            every next click is refused. And where the page offers no
            `onProduce` — the account may not create a run — the card offers
            neither. */}
        {hasIngredients && onProduce ? (
          <Button
            size="sm"
            variant="outline"
            className="flex-1"
            onClick={() => onProduce(recipe)}
          >
            {t("catalog.produce")}
          </Button>
        ) : !hasIngredients && canManage ? (
          <Button
            size="sm"
            variant="outline"
            className="flex-1"
            onClick={() => navigate(`/maker/recipes/${recipe.id}`)}
            data-testid="maker-recipe-card-add-ingredients"
          >
            {t("catalog.addIngredients")}
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="ghost"
          onClick={() => navigate(`/maker/recipes/${recipe.id}`)}
        >
          {t("catalog.details")}
        </Button>
      </div>
    </Card>
  );
}
