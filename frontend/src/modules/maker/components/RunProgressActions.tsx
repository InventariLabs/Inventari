import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, Play } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { DateInput } from "@/components/ui/DateInput";
import { Input } from "@/components/ui/Input";
import { extractApiError } from "@/lib/errors";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { QUANTITY_STEP } from "@/module-sdk";
import { todayIso } from "@/utils/formatters";
import {
  useFinishProduction,
  useStartProduction,
} from "@/modules/maker/hooks/useProduction";
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

  function confirm() {
    setAsking(false);
    start.mutate(
      { orderId: order.id, data: { started_on: day || undefined } },
      {
        onSuccess: () => toast.success(t("progress.startSuccess")),
        onError: (err) => {
          const shortage = parseShortageError(err);
          if (shortage?.error === "insufficient_stock") {
            onShortage(shortage.shortages, shortage.shortAtCreate ?? false);
            return;
          }
          const emptyBom = parseEmptyBomError(err);
          if (emptyBom) {
            toast.error(t("detail.emptyBom"), {
              action: emptyBom.recipeId
                ? {
                    label: t("detail.emptyBomAction"),
                    onClick: () =>
                      navigate(`/maker/recipes/${emptyBom.recipeId}`),
                  }
                : undefined,
            });
            return;
          }
          toast.error(extractApiError(err, t("progress.startFailed")));
        },
      },
    );
  }

  return (
    <>
      <Button
        variant="outline"
        leftIcon={<Play size={16} />}
        disabled={start.isPending}
        onClick={() => setAsking(true)}
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
        onConfirm={confirm}
        onCancel={() => setAsking(false)}
      >
        <div className="py-2">
          <DateInput
            label={t("progress.startDay")}
            value={day}
            max={todayIso()}
            onChange={setDay}
          />
        </div>
      </ConfirmDialog>
    </>
  );
}

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
