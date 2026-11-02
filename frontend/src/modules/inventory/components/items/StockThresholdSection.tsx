import { useTranslation } from "react-i18next";
import { AlertCircle } from "lucide-react";
import { Input } from "@/components/ui/Input";
import type { ItemFormData } from "@/modules/inventory/hooks/useItemForm";
import { RemovalStrategyChoice } from "../RemovalStrategyChoice";

interface StockThresholdSectionProps {
  formData: ItemFormData;
  onInputChange: (name: string, value: unknown) => void;
  /** The product is the shared catalogue's: its issue order is not this
   *  organization's to change, so it is shown, not offered. */
  sharedProduct?: boolean;
}

export function StockThresholdSection({
  formData,
  onInputChange,
  sharedProduct = false,
}: StockThresholdSectionProps) {
  const { t } = useTranslation("items");

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 border-b pb-2">
        <AlertCircle size={14} className="text-on-muted" />
        <h3 className="text-[10px] font-medium uppercase tracking-wider text-on-secondary">
          {t("stockManagement")}
        </h3>
      </div>

      <div className="space-y-1.5">
        <label
          htmlFor="min-stock-level"
          className="block text-xs font-medium text-on-secondary"
        >
          {t("minStockLevel", {})}
        </label>
        <div className="flex items-center gap-2">
          <Input
            id="min-stock-level"
            wrapperClassName="flex-1"
            type="number"
            step="0.01"
            min="0"
            name="min_quantity"
            value={formData.min_quantity || ""}
            onChange={(e) => onInputChange(e.target.name, e.target.value)}
            onWheel={(e) => e.currentTarget.blur()}
            placeholder={t("minQuantityPlaceholder")}
            className="px-4 py-2.5 rounded-lg bg-surface-card border border-amber-200 focus:border-amber-400 focus:ring-2 focus:ring-amber-400/20 outline-none font-medium text-on transition-all placeholder:text-on-muted"
          />
          {formData.uom_id && formData.uom && (
            <span className="text-sm font-medium text-on-secondary px-1">
              {(formData.uom as { symbol: string }).symbol}
            </span>
          )}
        </div>
        <p className="text-[10px] text-on-muted leading-tight">
          {t("minStockHelp")}
        </p>
      </div>

      {sharedProduct ? (
        // Offering the choice here saved nothing: the server keeps a shared
        // product's order for every organization and now refuses a new one.
        <div className="space-y-1">
          <p className="block text-xs font-medium text-on-secondary">
            {t("removalStrategy.label")}
          </p>
          <p className="text-sm font-medium text-on">
            {formData.removal_strategy || "FIFO"}
          </p>
          <p className="text-xs text-on-muted">
            {t("removalStrategy.sharedProduct")}
          </p>
        </div>
      ) : (
        <RemovalStrategyChoice
          label={t("removalStrategy.label")}
          value={formData.removal_strategy}
          onChange={(strategy) => onInputChange("removal_strategy", strategy)}
        />
      )}
    </div>
  );
}
