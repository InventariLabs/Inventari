import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Input } from "@/components/ui/Input";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { QUANTITY_STEP } from "@/module-sdk";
import { BestBeforeField } from "@/modules/maker/components/BestBeforeField";
import { EmptyBomNotice } from "@/modules/maker/components/EmptyBomNotice";
import { IngredientBatchPicker } from "@/modules/maker/components/IngredientBatchPicker";
import type { useCompleteRun } from "@/modules/maker/hooks/useCompleteRun";
import type { ProductionOrder } from "@/modules/maker/types/maker";

interface CompleteRunDialogProps {
  order: ProductionOrder;
  run: ReturnType<typeof useCompleteRun>;
  bomIsEmpty: boolean;
}

/**
 * Closing a draft: how much came out, until when it keeps, and which batch
 * each ingredient is taken from. The best-before opens on the run's day plus
 * the product's shelf life; the batches on the draw the run makes by default.
 */
export function CompleteRunDialog({
  order,
  run,
  bomIsEmpty,
}: CompleteRunDialogProps) {
  const { t } = useTranslation("maker");
  const anyShort = run.batches.short.size > 0;
  return (
    <ConfirmDialog
      open={run.showConfirm}
      title={t("detail.completeConfirm.title", {
        defaultValue: "Complete production run?",
      })}
      message={t("detail.completeConfirm.description", {
        defaultValue:
          "This consumes the listed ingredients and produces the output. This action cannot be undone.",
      })}
      confirmLabel={t("detail.complete", { defaultValue: "Complete run" })}
      cancelLabel={t("create.cancel", { defaultValue: "Cancel" })}
      confirmDisabled={bomIsEmpty || anyShort}
      onConfirm={() => {
        run.setShowConfirm(false);
        run.complete();
      }}
      onCancel={() => {
        run.setShowConfirm(false);
        run.setActualQty("");
      }}
      variant="default"
    >
      {bomIsEmpty && (
        <EmptyBomNotice recipeId={order.recipe_id} className="mt-2" />
      )}
      {/* The dialog keeps its title and its buttons in view; a run with
          many ingredients kept in batches scrolls between them. */}
      <div className="space-y-4 py-2 max-h-[55vh] overflow-y-auto pr-1">
        <div className="space-y-2">
          <Input
            label={t("detail.completeConfirm.actualQtyLabel", {
              defaultValue: "Actual quantity produced (optional)",
            })}
            type="number"
            step={QUANTITY_STEP}
            min="0"
            value={run.actualQty}
            onChange={(e) => run.setActualQty(e.target.value)}
            // A placeholder the reader can type over: formatted like the
            // header says it, not the raw string off the wire ("100.000"
            // with a dot in a comma locale).
            placeholder={formatQuantityLocalized(
              t,
              order.planned_qty,
              order.output_uom_symbol,
            )}
            data-testid="maker-complete-actual-qty-input"
          />
          <p className="text-xs text-on-muted">
            {t("detail.completeConfirm.actualQtyHint", {
              defaultValue:
                "Leave empty to use planned quantity. Enter less for scrap, more for overproduction. Ingredients are consumed as planned regardless of the actual quantity.",
            })}
          </p>
        </div>
        <BestBeforeField
          id="maker-complete-best-before"
          value={run.bestBefore}
          onChange={run.setBestBefore}
          min={order.production_date ?? undefined}
          shelfLifeDays={order.shelf_life_days}
        />
        <IngredientBatchPicker choice={run.batches} />
      </div>
    </ConfirmDialog>
  );
}
