import { useTranslation } from "react-i18next";
import { extractApiError } from "@/lib/errors";
import { Coins, AlertTriangle } from "lucide-react";
import { Sheet } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useMoney } from "@/hooks/useMoney";
import {
  CostFigure,
  useCostGapSentence,
} from "@/modules/maker/components/CostFigure";
import { BreakdownPieChart } from "@/modules/maker/components/BreakdownPieChart";
import { EmptyBomNotice } from "@/modules/maker/components/EmptyBomNotice";
import { MissingRecipeNotice } from "@/modules/maker/components/MissingRecipeNotice";
import type { ProductOption } from "@/modules/maker/api/products";
import type { CostBreakdownResponse } from "@/modules/maker/types/maker";
import { formatQuantityValue } from "@/utils/formatters";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";

interface ProductionPreviewSheetProps {
  open: boolean;
  onClose: () => void;
  breakdown: CostBreakdownResponse | undefined;
  isLoading: boolean;
  error: Error | null;
  /**
   * The output product the preview is about — when it turns out to have no
   * formula, the notice can open the catalog's create sheet pointed at it.
   */
  outputProduct?: ProductOption | null;
}

/**
 * Read-only cost breakdown sheet for a planned production.
 * Reuses the `/production/orders/preview` endpoint — no state mutation.
 */
export function ProductionPreviewSheet({
  open,
  onClose,
  breakdown,
  isLoading,
  error,
  outputProduct,
}: ProductionPreviewSheetProps) {
  const { t } = useTranslation("maker");
  const money = useMoney();
  const gapSentence = useCostGapSentence();

  // An ingredient with no rate contributes zero, so a formula nobody has
  // priced totals a clean 0.00 — which this sheet announced in its headline
  // tile, directly above its own note that no rates exist.
  const unpriced = breakdown?.missing_cost_lines.length ?? 0;
  const priced = (breakdown?.entries.length ?? 0) - unpriced;

  return (
    <Sheet
      open={open}
      onClose={onClose}
      maxWidth="xl"
      aria-label={t("preview.title")}
    >
      <div className="px-6 pt-6 pb-4 border-b border-border">
        <div className="flex items-center gap-2 text-lg font-semibold text-on">
          <Coins size={20} />
          {t("preview.title")}
        </div>
        <p className="text-sm text-on-muted mt-1">{t("preview.subtitle")}</p>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {isLoading && (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent-600" />
          </div>
        )}

        {error && (
          <Card className="p-4 bg-red-50 border-red-100 text-on-danger text-sm flex items-start gap-3">
            <AlertTriangle size={18} className="mt-0.5 flex-shrink-0" />
            <p>{extractApiError(error, t("preview.loadFailed"))}</p>
          </Card>
        )}

        {/* The preview knew this before the order existed: an empty
            ingredient section, a total of 0.00, and no word about
            the run being refused four screens later. The two zero-entry
            truths say which one they are: no formula at all leads where a
            formula is created, an unfilled one leads to its composition. */}
        {breakdown && !isLoading && breakdown.recipe_state === "no_recipe" && (
          <MissingRecipeNotice product={outputProduct} />
        )}
        {breakdown &&
          !isLoading &&
          breakdown.entries.length === 0 &&
          breakdown.recipe_state !== "no_recipe" && (
            <EmptyBomNotice recipeId={breakdown.recipe_id} />
          )}

        {breakdown && !isLoading && breakdown.entries.length > 0 && (
          <>
            <Card className="p-6 bg-accent-50">
              <div className="text-xs uppercase tracking-widest text-on-muted font-medium">
                {t("preview.totalCost")}
              </div>
              <div className="text-3xl font-semibold text-on mt-1">
                <CostFigure
                  value={breakdown.total_cost}
                  priced={priced}
                  unpriced={unpriced}
                  // The amber card below carries the gap sentence visibly;
                  // announcing it here too reads it twice to a screen reader.
                  // The figure points at that sentence instead, so reader and
                  // explanation stay associated — and when every ingredient
                  // priced, the card (and the id) is not rendered and the
                  // reference names nothing.
                  announce={false}
                  describedBy="production-preview-gap"
                />
              </div>
              <div className="text-xs text-on-muted mt-2">
                {t("preview.unitCostHint")}:{" "}
                {formatQuantityLocalized(
                  t,
                  breakdown.planned_qty,
                  breakdown.planned_uom_symbol,
                )}
              </div>
            </Card>

            {breakdown.missing_cost_lines.length > 0 && (
              <Card className="p-4 bg-amber-50 border-amber-100 text-on-warning text-sm">
                <div className="flex items-start gap-2">
                  <AlertTriangle size={18} className="mt-0.5 flex-shrink-0" />
                  <div>
                    <div className="font-semibold">
                      {t("preview.missingTitle")}
                    </div>
                    <div className="mt-1 text-xs" id="production-preview-gap">
                      {gapSentence({ priced, unpriced })}
                    </div>
                  </div>
                </div>
              </Card>
            )}

            <BreakdownPieChart breakdown={breakdown} />

            <div className="space-y-2">
              <h3 className="text-xs uppercase tracking-widest text-on-muted font-medium px-1">
                {t("preview.ingredients")}
              </h3>
              {breakdown.entries.map((entry) => (
                <Card
                  key={entry.child_template_id}
                  className="p-4 flex items-center justify-between gap-4"
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium truncate">
                      {entry.child_template_name ??
                        `${entry.child_template_id.slice(0, 8)}…`}
                    </div>
                    <div className="text-xs text-on-muted mt-1">
                      {formatQuantityLocalized(
                        t,
                        entry.consumed_qty,
                        entry.unit,
                      )}
                    </div>
                  </div>
                  <div className="text-right flex-shrink-0">
                    <div className="text-sm font-semibold text-on">
                      {entry.cost === null ? "—" : money(entry.cost)}
                    </div>
                    {entry.percentage_of_total && (
                      <div className="text-xs text-on-muted">
                        {formatQuantityValue(entry.percentage_of_total)}%
                      </div>
                    )}
                  </div>
                </Card>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="px-6 py-4 border-t border-border flex items-center justify-end">
        <Button variant="ghost" onClick={onClose}>
          {t("common:actions.close")}
        </Button>
      </div>
    </Sheet>
  );
}
