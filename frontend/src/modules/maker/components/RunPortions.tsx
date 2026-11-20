import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { useCanWrite } from "@/hooks/useCanWrite";
import { DateInput } from "@/components/ui/DateInput";
import { Input } from "@/components/ui/Input";
import { extractApiError } from "@/lib/errors";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { QUANTITY_STEP } from "@/module-sdk";
import { formatDate } from "@/utils/helpers";
import { todayIso } from "@/utils/formatters";
import { BestBeforeField } from "@/modules/maker/components/BestBeforeField";
import { useProposedBestBefore } from "@/modules/maker/hooks/useProposedBestBefore";
import { useAddPortion } from "@/modules/maker/hooks/useProduction";
import type { ProductionOrder } from "@/modules/maker/types/maker";

/**
 * The output a run has put on the shelf so far, and the form for the next
 * portion: bottling part of a vat is output from that day, with its own batch,
 * while the run stays open.
 */
export function RunPortions({
  order,
  canWrite,
}: {
  order: ProductionOrder;
  canWrite: boolean;
}) {
  const { t } = useTranslation("maker");
  // A portion lands on the shelf as stock: the endpoint asks for items:write.
  const canMoveStock = useCanWrite("items");
  const addPortion = useAddPortion();
  const [qty, setQty] = useState("");
  const [day, setDay] = useState(todayIso());
  const [lot, setLot] = useState("");
  const bestBefore = useProposedBestBefore(day, order.shelf_life_days);

  function add() {
    addPortion.mutate(
      {
        orderId: order.id,
        data: {
          qty: qty.trim(),
          made_on: day || undefined,
          output_lot_name: lot.trim() || undefined,
          best_before: bestBefore.value || undefined,
        },
      },
      {
        onSuccess: () => {
          toast.success(t("progress.portionAdded"));
          setQty("");
          setLot("");
          bestBefore.reset();
        },
        onError: (err) =>
          toast.error(extractApiError(err, t("progress.portionFailed"))),
      },
    );
  }

  const portions = order.portions ?? [];
  return (
    <section className="space-y-3" aria-labelledby="run-portions-title">
      <h2 id="run-portions-title" className="text-base font-medium text-on">
        {t("progress.portions")}
      </h2>
      {portions.length === 0 ? (
        <p className="text-sm text-on-muted">{t("progress.noPortions")}</p>
      ) : (
        <ul className="divide-y divide-border rounded-xl border border-border bg-surface-card">
          {portions.map((portion) => (
            <li
              key={portion.id}
              className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-2 text-sm"
            >
              <span className="font-medium text-on">
                {formatQuantityLocalized(
                  t,
                  portion.qty,
                  order.output_uom_symbol,
                )}
              </span>
              <span className="text-on-muted">
                {formatDate(portion.made_on)}
                {portion.lot_name ? ` · ${portion.lot_name}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
      {canWrite && canMoveStock && (
        <div className="space-y-3">
          <div className="grid grid-cols-1 items-end gap-3 sm:grid-cols-3">
            <Input
              label={t("progress.portionQty")}
              type="number"
              step={QUANTITY_STEP}
              min="0"
              value={qty}
              onChange={(e) => setQty(e.target.value)}
              data-testid="maker-portion-qty-input"
            />
            <DateInput
              label={t("progress.portionDay")}
              value={day}
              max={todayIso()}
              onChange={setDay}
            />
            <Input
              label={t("progress.portionLot")}
              value={lot}
              maxLength={100}
              onChange={(e) => setLot(e.target.value)}
              data-testid="maker-portion-lot-input"
            />
          </div>
          <div className="sm:max-w-xs">
            <BestBeforeField
              id="maker-portion-best-before"
              value={bestBefore.value}
              onChange={bestBefore.set}
              min={day || undefined}
              shelfLifeDays={order.shelf_life_days}
            />
          </div>
          <Button
            variant="outline"
            leftIcon={<Plus size={16} />}
            disabled={!(Number(qty) > 0) || addPortion.isPending}
            onClick={add}
            data-testid="maker-portion-add-button"
          >
            {t("progress.addPortion")}
          </Button>
        </div>
      )}
    </section>
  );
}
