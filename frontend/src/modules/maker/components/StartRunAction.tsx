import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Play } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { DateInput } from "@/components/ui/DateInput";
import { todayIso } from "@/utils/formatters";
import { IngredientBatchPicker } from "@/modules/maker/components/IngredientBatchPicker";
import { useBatchChoice } from "@/modules/maker/hooks/useBatchChoice";
import { useStartProduction } from "@/modules/maker/hooks/useProduction";
import {
  parseEmptyBomError,
  parseShortageError,
} from "@/modules/maker/lib/shortageError";
import type {
  ProductionOrder,
  ShortageEntry,
} from "@/modules/maker/types/maker";

/**
 * "Start run" on a draft: the ingredients leave the records now, on the day
 * named, and the run stays open until it is finished. A refusal arrives as the
 * same shortage list completing a run refuses with.
 */
export function StartRunAction({
  order,
  onShortage,
}: {
  order: ProductionOrder;
  onShortage: (shortages: ShortageEntry[], shortAtCreate: boolean) => void;
}) {
  const { t } = useTranslation("maker");
  const navigate = useNavigate();
  const start = useStartProduction();
  const [asking, setAsking] = useState(false);
  const [day, setDay] = useState(todayIso());
  // The batches the ingredients come from, asked only while the dialog is
  // open: the run takes exactly the ones chosen here.
  const batchQuery = useMemo(
    () =>
      asking
        ? {
            output_template_id: order.output_template_id,
            planned_qty: String(order.planned_qty),
            output_location_id: order.output_location_id,
            recipe_id: order.recipe_id ?? null,
          }
        : null,
    [asking, order],
  );
  const batches = useBatchChoice(batchQuery);

  // Every opening starts from today, not from a refused attempt's day.
  function open() {
    setDay(todayIso());
    setAsking(true);
  }

  // A refusal that is not a list to act on stays inside the dialog, which
  // keeps the day and the batches as chosen.
  async function confirm() {
    try {
      await start.mutateAsync({
        orderId: order.id,
        data: {
          started_on: day || undefined,
          ingredient_lots:
            batches.payload.length > 0 ? batches.payload : undefined,
        },
      });
    } catch (err) {
      const shortage = parseShortageError(err);
      if (shortage?.error === "insufficient_stock") {
        setAsking(false);
        onShortage(shortage.shortages, shortage.shortAtCreate ?? false);
        return;
      }
      const emptyBom = parseEmptyBomError(err);
      if (emptyBom) {
        setAsking(false);
        toast.error(t("detail.emptyBom"), {
          action: emptyBom.recipeId
            ? {
                label: t("detail.emptyBomAction"),
                onClick: () => navigate(`/maker/recipes/${emptyBom.recipeId}`),
              }
            : undefined,
        });
        return;
      }
      throw err;
    }
    setAsking(false);
    toast.success(t("progress.startSuccess"));
  }

  return (
    <>
      <Button
        variant="outline"
        leftIcon={<Play size={16} />}
        disabled={start.isPending}
        onClick={open}
        data-testid="maker-detail-start-button"
      >
        {t("progress.start")}
      </Button>
      <ConfirmDialog
        open={asking}
        title={t("progress.startConfirm.title")}
        message={t("progress.startConfirm.description")}
        confirmLabel={t("progress.start")}
        cancelLabel={t("create.cancel")}
        variant="default"
        confirmDisabled={batches.short.size > 0}
        errorFallback={t("progress.startFailed")}
        onConfirm={confirm}
        onCancel={() => setAsking(false)}
      >
        {/* Title and buttons stay in view; many batched ingredients scroll. */}
        <div className="space-y-4 py-2 max-h-[55vh] overflow-y-auto pr-1">
          <DateInput
            label={t("progress.startDay")}
            value={day}
            max={todayIso()}
            onChange={setDay}
          />
          <IngredientBatchPicker choice={batches} />
        </div>
      </ConfirmDialog>
    </>
  );
}
