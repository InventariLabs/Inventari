import { useTranslation } from "react-i18next";
import { Coins, Loader2 } from "lucide-react";
import type { ProductTemplate } from "@/lib/api/productTemplates";
import { useMoney } from "@/hooks/useMoney";
import { useShowInventoryValue } from "@/modules/shared/hooks/useShowInventoryValue";
import { unitLabel } from "@/lib/i18nHelpers";

interface ValuationSectionProps {
  template: ProductTemplate | null;
  isLoading: boolean;
  uomSymbol: string | undefined;
  hasTemplate: boolean;
}

/**
 * The average rate of the cost layers still on hand — stock value.
 *
 * A profile that does not show stock value (`show_inventory_value`) keeps
 * no ledger for this rate to be read back from, so the whole section is
 * absent rather than empty (the same decision the add form makes about the
 * purchase-price field).
 */
export function ValuationSection({
  template,
  isLoading,
  uomSymbol,
  hasTemplate,
}: ValuationSectionProps) {
  const { t } = useTranslation("items");
  const money = useMoney();
  const showInventoryValue = useShowInventoryValue();

  if (!hasTemplate || !showInventoryValue) return null;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 border-b pb-2">
        <Coins size={14} className="text-on-muted" />
        <h3 className="text-[10px] font-medium uppercase tracking-wider text-on-secondary">
          {t("valuation.title", { defaultValue: "Valuation" })}
        </h3>
      </div>

      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-on-muted">
          <Loader2 size={14} className="animate-spin" />
          <span>{t("valuation.loading", { defaultValue: "Loading..." })}</span>
        </div>
      ) : template?.current_valuation_rate != null ? (
        <div className="flex items-center justify-between p-3 bg-surface-card border border-border rounded-xl">
          <div>
            <p className="text-xs font-medium text-on-secondary">
              {t("valuation.currentRate", {
                defaultValue: "Average cost of layers on hand",
              })}
            </p>
            <p className="text-[10px] text-on-muted mt-0.5">
              {t("valuation.rateDescription", {
                defaultValue:
                  "Stock value is FIFO; this is the average of the cost layers still on hand.",
              })}
            </p>
          </div>
          <div className="text-right">
            <p className="text-lg font-semibold text-on">
              {money(template.current_valuation_rate)}
            </p>
            <p className="text-xs text-on-muted">{unitLabel(t, uomSymbol)}</p>
          </div>
        </div>
      ) : (
        <p className="text-xs text-on-muted">
          {t("valuation.noRate", {
            defaultValue:
              "No cost layers yet — receive stock with a price to build one.",
          })}
        </p>
      )}
    </div>
  );
}
