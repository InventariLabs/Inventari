import { useState } from "react";
import { useTranslation } from "react-i18next";
import { CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { DateInput } from "@/components/ui/DateInput";
import { Input } from "@/components/ui/Input";
import { extractApiError } from "@/lib/errors";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { QUANTITY_STEP } from "@/module-sdk";
import { todayIso } from "@/utils/formatters";
import { useFinishProduction } from "@/modules/maker/hooks/useProduction";
import type { ProductionOrder } from "@/modules/maker/types/maker";

/**
 * "Finish run" on a run in progress: the quantity the whole run made — the
 * portions already on the shelf included — and the day it closed. What is
 * still to come out of it is put on the shelf now, and the run takes the cost
 * it ended up with.
 */
export function FinishRunAction({ order }: { order: ProductionOrder }) {
  const { t } = useTranslation("maker");
  const finish = useFinishProduction();
  const [asking, setAsking] = useState(false);
  const [qty, setQty] = useState("");
  const [day, setDay] = useState(todayIso());
  const [lot, setLot] = useState("");

  function confirm() {
    setAsking(false);
    finish.mutate(
      {
        orderId: order.id,
        data: {
          actual_qty: qty.trim() || undefined,
          finished_on: day || undefined,
          output_lot_name: lot.trim() || undefined,
        },
      },
      {
        onSuccess: () => {
          toast.success(t("progress.finishSuccess"));
          setQty("");
          setLot("");
        },
        onError: (err) =>
          toast.error(extractApiError(err, t("progress.finishFailed"))),
      },
    );
  }

  return (
    <>
      <Button
        leftIcon={<CheckCircle2 size={16} />}
        disabled={finish.isPending}
        onClick={() => setAsking(true)}
        data-testid="maker-detail-finish-button"
      >
        {t("progress.finish")}
      </Button>
      <ConfirmDialog
        open={asking}
        title={t("progress.finishConfirm.title")}
        message={t("progress.finishConfirm.description")}
        confirmLabel={t("progress.finish")}
        cancelLabel={t("create.cancel")}
        variant="default"
        onConfirm={confirm}
        onCancel={() => setAsking(false)}
      >
        <div className="space-y-3 py-2">
          <Input
            label={t("progress.finishQty")}
            type="number"
            step={QUANTITY_STEP}
            min="0"
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            placeholder={formatQuantityLocalized(
              t,
              order.planned_qty,
              order.output_uom_symbol,
            )}
            data-testid="maker-finish-actual-qty-input"
          />
          <p className="text-xs text-on-muted">{t("progress.finishQtyHint")}</p>
          <DateInput
            label={t("progress.finishDay")}
            value={day}
            max={todayIso()}
            onChange={setDay}
          />
          <Input
            label={t("progress.portionLot")}
            value={lot}
            maxLength={100}
            onChange={(e) => setLot(e.target.value)}
          />
        </div>
      </ConfirmDialog>
    </>
  );
}
