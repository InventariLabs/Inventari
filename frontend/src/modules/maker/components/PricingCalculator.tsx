import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Coins, Save, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Sheet } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Card } from "@/components/ui/Card";
import { CostFigure, CostGapNote } from "@/modules/maker/components/CostFigure";
import { EmptyBomNotice } from "@/modules/maker/components/EmptyBomNotice";
import { MissingRecipeNotice } from "@/modules/maker/components/MissingRecipeNotice";
import type { ProductOption } from "@/modules/maker/api/products";
import { extractApiError } from "@/lib/errors";
import { formatPercentLocale } from "@/utils/formatters";
import {
  useMargin,
  usePricingCompute,
  useSetMargin,
} from "@/modules/maker/hooks/usePricing";

interface PricingCalculatorProps {
  open: boolean;
  onClose: () => void;
  templateId: string | undefined;
  producedQty: string;
  /**
   * The product the price is about — when it turns out to have no formula,
   * the notice can open the catalog's create sheet pointed at it.
   */
  product?: ProductOption | null;
}

function clamp(value: number, min: number, max: number): number {
  if (Number.isNaN(value)) return min;
  return Math.min(Math.max(value, min), max);
}

/**
 * Pricing calculator — live preview of unit cost → sale price given margin.
 * Optionally persists the chosen margin as a per-template default
 * (lives in ``meta_data['maker']['target_margin_pct']``).
 */
export function PricingCalculator({
  open,
  onClose,
  templateId,
  producedQty,
  product,
}: PricingCalculatorProps) {
  const { t } = useTranslation("maker");

  const { data: storedMargin, isLoading: marginLoading } = useMargin(
    open ? templateId : undefined,
  );
  const computeMutation = usePricingCompute();
  const setMarginMutation = useSetMargin(templateId ?? "");

  const [marginInput, setMarginInput] = useState<string>("30");
  const [qtyInput, setQtyInput] = useState<string>(producedQty);

  useEffect(() => {
    if (open) {
      setQtyInput(producedQty);
    }
  }, [open, producedQty]);

  // A result belongs to the product it was computed for: another product, or
  // the sheet opened again, starts from "nothing computed yet".
  const { reset: resetCompute } = computeMutation;
  useEffect(() => {
    resetCompute();
  }, [templateId, open, resetCompute]);

  useEffect(() => {
    if (storedMargin && !marginLoading && marginInput === "30") {
      setMarginInput(storedMargin.target_margin_pct);
    }
  }, [storedMargin, marginLoading, marginInput]);

  const margin = clamp(Number(marginInput), 0, 95);
  const qty = clamp(Number(qtyInput), 0, 9999);

  function handlePreview() {
    if (!templateId) return;
    if (qty <= 0) {
      toast.error(t("pricing.errors.qty"));
      return;
    }
    computeMutation.mutate({
      template_id: templateId,
      produced_qty: String(qty),
      target_margin_pct: String(margin),
    });
  }

  function handleSaveDefault() {
    if (!templateId) return;
    setMarginMutation.mutate(String(margin), {
      onSuccess: () => {
        toast.success(t("pricing.saved"));
      },
      onError: (err) => {
        toast.error(extractApiError(err, t("pricing.saveFailed")));
      },
    });
  }

  const result = computeMutation.data;

  // An ingredient with no rate is priced at zero so the sum can finish, and
  // all three figures came out 0.00 — including a suggested sale price, at
  // whatever margin. A price derived from no cost is not a suggestion.
  const unpriced = result?.unrated_ingredient_count ?? 0;
  const priced = (result?.ingredient_count ?? 0) - unpriced;

  return (
    <Sheet
      open={open}
      onClose={onClose}
      maxWidth="md"
      aria-label={t("pricing.title")}
    >
      <div className="px-6 pt-6 pb-4 border-b border-border">
        <div className="flex items-center gap-2 text-lg font-semibold text-on">
          <Sparkles size={20} />
          {t("pricing.title")}
        </div>
        <p className="text-sm text-on-muted mt-1">{t("pricing.subtitle")}</p>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-5">
        {storedMargin && !marginLoading && (
          <div className="text-xs text-on-muted">
            {t("pricing.currentDefault")}{" "}
            <span className="font-medium text-on">
              {formatPercentLocale(storedMargin.target_margin_pct, 1)}
            </span>
            {storedMargin.is_default && (
              <span className="ml-2 text-on-muted italic">
                {t("pricing.isDefault")}
              </span>
            )}
          </div>
        )}

        <Input
          type="number"
          step="any"
          min="0"
          label={t("pricing.qtyLabel")}
          value={qtyInput}
          onChange={(e) => setQtyInput(e.target.value)}
        />

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label
              id="maker-pricing-margin-label"
              htmlFor="maker-pricing-margin-slider"
              className="block text-xs font-medium uppercase text-on-secondary tracking-wide"
            >
              {t("pricing.marginLabel")}
            </label>
            <span className="text-sm font-medium text-on tabular-nums">
              {formatPercentLocale(margin, 1)}
            </span>
          </div>
          <input
            id="maker-pricing-margin-slider"
            type="range"
            min={0}
            max={95}
            step={0.5}
            value={Number(marginInput)}
            onChange={(e) => setMarginInput(e.target.value)}
            className="w-full accent-accent-600"
            data-testid="maker-pricing-slider"
          />
          {/* The slider and the field edit one value, so both carry the same
              name: the label points at the slider, the field names itself
              from it. */}
          <Input
            type="number"
            step="any"
            min="0"
            max="95"
            aria-labelledby="maker-pricing-margin-label"
            value={marginInput}
            onChange={(e) => setMarginInput(e.target.value)}
            className="text-right tabular-nums"
          />
        </div>

        <Button
          variant="outline"
          onClick={handlePreview}
          disabled={qty <= 0 || computeMutation.isPending}
          className="w-full"
          data-testid="maker-pricing-preview-button"
        >
          {computeMutation.isPending
            ? t("pricing.calculating")
            : t("pricing.preview")}
        </Button>

        {/* A 30% margin on nothing is 0.00, and a price of zero
            reads as an answer. Say there was nothing to price — and which
            nothing it is: no formula leads where one is created, an
            unfilled one leads to its composition. */}
        {result && result.recipe_state === "no_recipe" && (
          <MissingRecipeNotice product={product} />
        )}
        {result &&
          result.ingredient_count === 0 &&
          result.recipe_state !== "no_recipe" && (
            <EmptyBomNotice recipeId={result.recipe_id} />
          )}

        {result && result.ingredient_count > 0 && (
          <Card className="p-4 bg-accent-50 space-y-2">
            {/* Three figures, one gap sentence: the CostGapNote at the bottom
                of the card prints it visibly, so the figures above stay quiet
                instead of reading it to a screen reader three times. Each
                figure points at that note (describedBy), which is how the
                reader still gets figure and explanation as one announcement
                without the sentence being said twice. */}
            <div className="flex items-baseline justify-between">
              <span className="text-xs uppercase tracking-widest text-on-muted font-medium">
                {t("pricing.totalCost")}
              </span>
              <span className="font-mono text-sm text-on-secondary">
                <CostFigure
                  value={result.total_cost}
                  priced={priced}
                  unpriced={unpriced}
                  announce={false}
                  describedBy="pricing-gap-note"
                />
              </span>
            </div>
            <div className="flex items-baseline justify-between">
              <span className="text-xs uppercase tracking-widest text-on-muted font-medium">
                {/* Today's rates, not a measurement: the card above the tab
                    says "estimated" and this figure is the same number. */}
                {t("pricing.unitCostEstimated")}
              </span>
              <span className="font-mono text-sm text-on-secondary">
                <CostFigure
                  value={result.unit_cost}
                  priced={priced}
                  unpriced={unpriced}
                  announce={false}
                  describedBy="pricing-gap-note"
                />
              </span>
            </div>
            <div className="border-t border-accent-200/50 my-1" />
            <div className="flex items-baseline justify-between">
              <span className="text-xs uppercase tracking-widest text-on-muted font-medium flex items-center gap-1">
                <Coins size={12} />
                {t("pricing.suggestedPrice")}
              </span>
              <span className="text-2xl font-semibold text-accent-700 tabular-nums">
                <CostFigure
                  value={result.unit_sale_price}
                  priced={priced}
                  unpriced={unpriced}
                  announce={false}
                  describedBy="pricing-gap-note"
                />
              </span>
            </div>
            <CostGapNote
              priced={priced}
              unpriced={unpriced}
              id="pricing-gap-note"
            />
          </Card>
        )}

        {computeMutation.error && (
          <Card className="p-3 bg-red-50 border-red-100 text-red-700 text-xs">
            {extractApiError(
              computeMutation.error,
              t("pricing.errors.compute"),
            )}
          </Card>
        )}
      </div>

      <div className="px-6 py-4 border-t border-border flex items-center justify-between gap-3">
        <Button variant="ghost" onClick={onClose}>
          {t("pricing.close")}
        </Button>
        <Button
          onClick={handleSaveDefault}
          leftIcon={<Save size={16} />}
          disabled={!templateId || setMarginMutation.isPending}
          data-testid="maker-pricing-save-default"
        >
          {setMarginMutation.isPending
            ? t("pricing.saving")
            : t("pricing.saveDefault")}
        </Button>
      </div>
    </Sheet>
  );
}
