import { useState } from "react";
import { Bell, BellOff, X, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Item } from "@/types";
import { toAmount } from "@/utils/formatters";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import { useUpdateItem } from "@/modules/inventory/hooks/useItemMutations";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Sheet, SheetActions } from "@/components/ui/Sheet";
import { formatQuantityLocalized, unitLabel } from "@/lib/i18nHelpers";
import { useProductTemplateStock } from "@/modules/inventory/hooks/useProductTemplateStock";

interface Props {
  item: Item;
  onClose: () => void;
}

export default function ThresholdQuickSetSheet({ item, onClose }: Props) {
  const { t } = useTranslation(["items", "common"]);
  const updateItemMutation = useUpdateItem();
  // An empty field for an item that has no threshold yet. Pre-filling it with
  // the quantity on the shelf proposed the one number that makes the alert
  // fire immediately, and it looked like a saved setting rather than a guess —
  // "Set to current quantity" below is the same shortcut, said out loud.
  const [value, setValue] = useState<string>(
    item.min_quantity != null ? String(item.min_quantity) : "",
  );

  const saveMutation = {
    mutate: (min_quantity: number | null) =>
      updateItemMutation.mutate(
        { id: item.id, data: { min_quantity } },
        {
          onSuccess: () => {
            toast.success(
              t("messages.updateSuccess", { defaultValue: "Saved" }),
            );
            onClose();
          },
          // "Something went wrong" over a refusal sends the reader looking for
          // an outage instead of an administrator. The server says which it is.
          onError: (error: unknown) =>
            toast.error(
              extractApiError(
                error,
                t("common:errors.generic", { defaultValue: "Failed to save" }),
              ),
            ),
        },
      ),
    isPending: updateItemMutation.isPending,
  };

  const handleSave = () => {
    const num = parseFloat(value);
    if (isNaN(num) || num < 0) return;
    saveMutation.mutate(num);
  };

  const canSave = value.trim() !== "" && !isNaN(parseFloat(value));

  const handleRemove = () => {
    saveMutation.mutate(null);
  };

  // The threshold governs the product, not this record — it is stored on
  // the template and read as a sum (`app.services.items.low_stock`). So the
  // quantity this sheet shows, compares and offers to copy is the product's
  // total, not the row the reader opened: on a product kept in six places,
  // "set the alert to what is here now" used to set it to a sixth of what
  // was there, and the alert then never fired.
  const { data: productStock } = useProductTemplateStock(item.template_id);
  const coversWholeProduct = !!item.template_id;
  // Both quantities cross the wire as Decimal strings; the comparison runs
  // on the numbers they denote (TECHNICAL_DECISIONS §18).
  const measuredQuantity = productStock
    ? Number(productStock.total_quantity)
    : (toAmount(item.quantity) ?? 0);

  const hasThreshold = item.min_quantity != null;
  const isAtOrBelow =
    hasThreshold && measuredQuantity <= (item.min_quantity ?? 0);

  return (
    <Sheet
      open
      onClose={onClose}
      zIndex="modal-nested"
      backdropOpacity={60}
      aria-label={t("threshold.title")}
    >
      {/* Drag handle */}
      <div className="w-10 h-1 bg-surface-inset rounded-full mx-auto mt-3 sm:hidden" />

      <div className="p-6 space-y-5 flex-1 overflow-y-auto">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-amber-50 flex items-center justify-center">
              <Bell size={18} className="text-amber-500" />
            </div>
            <div>
              <h3 className="font-semibold text-on text-sm leading-tight">
                {t("threshold.title")}
              </h3>
              <p className="text-xs text-on-muted mt-0.5 font-medium truncate max-w-[180px]">
                {item.name}
              </p>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            aria-label={t("common:actions.close")}
          >
            <X size={18} />
          </Button>
        </div>

        {/* Current quantity info */}
        <div
          className={`px-3 py-2 rounded-xl text-xs font-medium flex items-center gap-2 ${isAtOrBelow ? "bg-amber-50 text-amber-700" : "bg-surface text-on-secondary"}`}
        >
          <span>
            {coversWholeProduct
              ? t("threshold.currentAcrossLocations")
              : t("threshold.current")}{" "}
            {formatQuantityLocalized(
              t,
              measuredQuantity,
              item.uom?.symbol,
              item.uom?.rounding,
            )}
          </span>
          {isAtOrBelow && (
            <span className="ml-auto">⚠ {t("threshold.runningLow")}</span>
          )}
        </div>

        {/* Input */}
        <div className="space-y-1.5">
          <label
            htmlFor="threshold-quick-set"
            className="block text-xs font-medium text-on-secondary"
          >
            {t("threshold.fieldLabel")}
          </label>
          <div className="flex items-center gap-2">
            <Input
              id="threshold-quick-set"
              type="number"
              step="any"
              min="0"
              data-testid="threshold-input"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSave()}
              onWheel={(e) => e.currentTarget.blur()}
              className="text-center text-lg"
              autoFocus
            />
            <span className="text-sm font-semibold text-on-muted shrink-0">
              {unitLabel(t, item.uom?.symbol)}
            </span>
          </div>
        </div>

        {/* Quick set to what is actually measured */}
        {String(measuredQuantity) !== value && (
          <Button
            size="content"
            variant="link"
            onClick={() => setValue(String(measuredQuantity))}
            className="w-full text-xs text-amber-600 font-medium p-0"
          >
            ← {t("threshold.setToCurrent")} (
            {formatQuantityLocalized(
              t,
              measuredQuantity,
              item.uom?.symbol,
              item.uom?.rounding,
            )}
            )
          </Button>
        )}

        {coversWholeProduct && (
          <p className="text-[10px] text-on-muted leading-snug">
            {t("threshold.scopeNote")}
          </p>
        )}

        {/* Actions */}
        <SheetActions className="pt-1">
          {/* ui-pattern: destructive-as-neutral — this switches an alert off
              rather than destroying anything, and the same sheet sets it
              again in one step */}
          {hasThreshold && (
            <Button
              variant="outline"
              onClick={handleRemove}
              disabled={saveMutation.isPending}
            >
              <BellOff size={14} />
              <span>{t("common:actions.remove")}</span>
            </Button>
          )}
          <Button
            onClick={handleSave}
            disabled={saveMutation.isPending || !canSave}
            className="bg-amber-500 hover:bg-amber-600"
          >
            {saveMutation.isPending ? (
              <Loader2 size={15} className="animate-spin" />
            ) : (
              <Bell size={15} />
            )}
            {t("threshold.save")}
          </Button>
        </SheetActions>
      </div>
    </Sheet>
  );
}
