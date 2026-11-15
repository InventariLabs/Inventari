import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Play } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { DateInput } from "@/components/ui/DateInput";
import { extractApiError } from "@/lib/errors";
import { todayIso } from "@/utils/formatters";
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
