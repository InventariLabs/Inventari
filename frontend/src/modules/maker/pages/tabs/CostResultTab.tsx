import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Pencil, TrendingDown, TrendingUp, X } from "lucide-react";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { QueryError } from "@/components/ui/QueryResult";
import { Input } from "@/components/ui/Input";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { formatMoney } from "@/utils/formatters";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { useBomCostEstimate } from "@/modules/maker/hooks/useBom";
import { useUpdateMakerRecipe } from "@/modules/maker/hooks/useRecipes";
import { useResultTerms } from "@/modules/maker/hooks/useResultTerms";
import { useCanWrite } from "@/hooks/useCanWrite";
import { BreakdownPieChart } from "@/modules/maker/components/BreakdownPieChart";
import { CostLinesEditor } from "@/modules/maker/components/CostLinesEditor";
import { CostFigure, CostGapNote } from "@/modules/maker/components/CostFigure";
import type { MakerRecipe } from "@/modules/maker/types/maker";

interface CostResultTabProps {
  recipe: MakerRecipe;
}

export function CostResultTab({ recipe }: CostResultTabProps) {
  // The reference price is a field on the recipe, so saving it is
  // `maker:write` — not the `maker:manage` the page above asks about, which
  // guards the formula itself. Two rights, two questions, and the page's
  // answer was never passed down here.
  const canWrite = useCanWrite("maker");
  const currency = useOrganizationCurrency();
  const { t, i18n } = useTranslation("maker");
  // The estimate is asked for THIS formula at a full batch, so the tab
  // divides by the yield exactly once. It used to fetch one unit of the
  // product's default formula and divide that by the yield again — a
  // variant priced someone else's ingredients, and a yield of 2 halved a
  // number that was already per unit.
  const {
    data: breakdown,
    isLoading,
    isError,
    refetch,
  } = useBomCostEstimate(recipe.output_template_id, {
    recipeId: recipe.id,
    qty: recipe.batch_yield_qty,
  });
  const resultTerm = useResultTerms();
  const updateRecipe = useUpdateMakerRecipe();

  const [refPriceDraft, setRefPriceDraft] = useState<string | null>(null);

  // An ingredient with no rate contributes zero, so a formula nobody has
  // priced sums to a clean 0.00 — and this tab printed that as the cost
  // while the row it came from said "—". The counts say which zero it is.
  const unpriced = breakdown?.missing_cost_lines.length ?? 0;
  const priced = (breakdown?.entries.length ?? 0) - unpriced;
  // breakdown is a full batch of this formula: one division, batch → unit.
  const unitCost =
    breakdown && priced > 0
      ? Number(breakdown.total_cost) / Number(recipe.batch_yield_qty)
      : null;
  const referencePrice = recipe.reference_price
    ? Number(recipe.reference_price)
    : null;

  const result =
    unitCost !== null && referencePrice !== null
      ? referencePrice - unitCost
      : null;

  async function saveRefPrice() {
    if (refPriceDraft === null) return;
    const value = refPriceDraft.trim();
    if (value === "" || Number.isNaN(Number(value))) {
      setRefPriceDraft(null);
      return;
    }
    try {
      await updateRecipe.mutateAsync({
        recipeId: recipe.id,
        data: { reference_price: value },
      });
      setRefPriceDraft(null);
      toast.success(t("detail.cost.referencePriceSaved"));
    } catch (err) {
      toast.error(
        extractApiError(
          err,
          t("detail.cost.referencePriceSaveFailed", {
            defaultValue: "Failed to save reference price",
          }),
        ),
      );
    }
  }

  return (
    <div className="space-y-4">
      {/* Summary cards. The fixed-costs total is not one of them: it moved
          into the fixed-cost lines section below, whose heading it used to
          duplicate — the figure belongs with the lines it sums. */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Card className="p-4">
          <p className="text-xs text-on-muted uppercase tracking-widest font-medium">
            {/* Layer rates today, not a measurement of a run — the card
                above this tab names the same figure "estimated". */}
            {t("catalog.unitCostEstimated")}
          </p>
          <p className="text-xl font-semibold text-on mt-1">
            {/* The CostGapNote below prints the gap sentence visibly, so the
                figure does not repeat it to a screen reader — and the
                figure points at that note, so reader and figure stay
                associated without anything being said twice. */}
            <CostFigure
              value={unitCost}
              priced={priced}
              unpriced={unpriced}
              announce={false}
              describedBy="maker-cost-gap-note"
            />
          </p>
          {/* The figure above is total ÷ batch yield, so it is per
              unit — the caption used to read "per batch" and passed
              a {{qty}} none of the five translations used. */}
          <p className="text-xs text-on-muted mt-0.5">
            {t("detail.cost.perYieldUnit", {
              qty: formatQuantityLocalized(
                t,
                recipe.batch_yield_qty,
                recipe.batch_yield_uom_symbol,
              ),
            })}
          </p>
          <CostGapNote
            priced={priced}
            unpriced={unpriced}
            id="maker-cost-gap-note"
          />
        </Card>

        <Card className="p-4">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-on-muted uppercase tracking-widest font-medium">
              {t("detail.cost.referencePrice")}
            </p>
            {refPriceDraft === null ? (
              canWrite && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setRefPriceDraft(recipe.reference_price ?? "")}
                  aria-label={t("detail.cost.editReferencePrice")}
                  data-testid="maker-ref-price-edit"
                >
                  <Pencil size={14} />
                </Button>
              )
            ) : (
              <div className="flex items-center gap-1">
                <Input
                  wrapperClassName="w-24"
                  type="number"
                  step="0.01"
                  min="0"
                  value={refPriceDraft}
                  onChange={(e) => setRefPriceDraft(e.target.value)}
                  className="h-8 text-sm"
                  aria-label={t("detail.cost.referencePrice")}
                  data-testid="maker-ref-price-input"
                />
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={saveRefPrice}
                  disabled={updateRecipe.isPending}
                  aria-label={t("common:actions.save")}
                >
                  <Check size={16} className="text-accent-600" />
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setRefPriceDraft(null)}
                  aria-label={t("common:actions.cancel")}
                >
                  <X size={16} />
                </Button>
              </div>
            )}
          </div>
          <p className="text-xl font-semibold text-on mt-1">
            {refPriceDraft === null
              ? formatMoney(recipe.reference_price, currency, i18n.language)
              : "—"}
          </p>
          {result !== null && (
            <p
              className={`text-xs font-medium mt-0.5 flex items-center gap-1 ${
                result >= 0 ? "text-accent-600" : "text-red-500"
              }`}
            >
              {result >= 0 ? (
                <TrendingUp size={12} />
              ) : (
                <TrendingDown size={12} />
              )}
              {resultTerm.label}: {formatMoney(result, currency, i18n.language)}
            </p>
          )}
          {result !== null && (
            <p className="text-xs text-on-muted mt-0.5">
              {resultTerm.definition}
            </p>
          )}
        </Card>
      </div>

      {/* Fixed cost lines editor */}
      <CostLinesEditor recipeId={recipe.id} lines={recipe.cost_lines ?? []} />

      {/* Ingredient cost breakdown */}
      {isLoading ? (
        <div className="text-center py-8 text-on-muted text-sm">
          {t("detail.loading")}
        </div>
      ) : isError ? (
        <Card className="p-4">
          <QueryError onRetry={() => void refetch()} />
        </Card>
      ) : breakdown ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <BreakdownPieChart breakdown={breakdown} />
          <Card className="p-4 space-y-2">
            <h3 className="text-xs uppercase tracking-widest text-on-muted font-medium px-1">
              {t("detail.cost.ingredients")}
            </h3>
            {breakdown.entries.length === 0 ? (
              // Not the order's message: this screen has no Cancel
              // button and cannot have one.
              <p className="text-sm text-on-muted px-1">
                {t("detail.cost.emptyLines")}
              </p>
            ) : (
              breakdown.entries.map((entry) => (
                <div
                  key={entry.child_template_id}
                  className="flex items-center justify-between gap-2 text-sm px-1 py-1"
                >
                  <span className="truncate text-on">
                    {entry.child_template_name ??
                      entry.child_template_id.slice(0, 8)}
                  </span>
                  <span className="text-on-muted shrink-0">
                    {formatQuantityLocalized(t, entry.consumed_qty, entry.unit)}
                  </span>
                  <span className="font-medium text-on shrink-0">
                    {formatMoney(entry.cost, currency, i18n.language)}
                  </span>
                </div>
              ))
            )}
            <div className="border-t border-border pt-2 flex items-center justify-between text-sm px-1">
              <span className="font-semibold text-on">
                {t("detail.cost.total")}
              </span>
              <span className="font-semibold text-on">
                {/* Same visible CostGapNote up in the summary card — the
                    sentence is announced there once, not once per figure.
                    Both figures point at the same note. */}
                <CostFigure
                  value={breakdown.total_cost}
                  priced={priced}
                  unpriced={unpriced}
                  announce={false}
                  describedBy="maker-cost-gap-note"
                />
              </span>
            </div>
          </Card>
        </div>
      ) : null}
    </div>
  );
}
