/**
 * A delivery cost that reached no product — recorded, listed, never valued.
 *
 * A freight bill that arrives after the receipt is posted cannot be spread
 * over the goods: some of them may be gone. The amount is kept here with its
 * reason and the day it belongs to, and the section says in so many words
 * that the stock value does not move.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { DateInput } from "@/components/ui/DateInput";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { useCanManage } from "@/hooks/useCanWrite";
import { useMoney } from "@/hooks/useMoney";
import { extractApiError } from "@/lib/errors";
import { formatDate, todayIso } from "@/utils/formatters";
import {
  useAddCostVariance,
  useExtraCosts,
  useRemoveCostVariance,
} from "@/modules/warehouse/hooks/useExtraCosts";
import type { ExtraCostKind } from "@/modules/warehouse/api/extraCosts";

const KINDS: ExtraCostKind[] = ["freight", "duty", "insurance", "other"];

export function DocumentCostVariancesSection({
  documentId,
}: {
  documentId: string;
}) {
  const { t } = useTranslation(["warehouse", "common"]);
  const money = useMoney();
  const canManage = useCanManage("warehouse");
  const { data } = useExtraCosts(documentId);
  const add = useAddCostVariance(documentId);
  const remove = useRemoveCostVariance(documentId);

  const [kind, setKind] = useState<ExtraCostKind>("freight");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  // The day the cost belongs to — a bill entered a week after the goods came
  // is dated by the delivery, not by the day it was typed.
  const [day, setDay] = useState(todayIso);

  if (!data) return null;
  // While the receipt is open a cost goes into the value of the goods — that
  // is the section above. The variance is for what comes after.
  const canRecord = canManage && !data.editable;
  if (!canRecord && data.variances.length === 0) return null;

  const submit = () => {
    if (!amount.trim() || !reason.trim() || !day) return;
    add.mutate(
      {
        kind,
        amount: amount.trim(),
        reason: reason.trim(),
        occurred_on: day,
      },
      {
        onSuccess: () => {
          setAmount("");
          setReason("");
          setDay(todayIso());
        },
        onError: (error) =>
          toast.error(
            extractApiError(error, t("warehouse:costVariances.addFailed")),
          ),
      },
    );
  };

  return (
    <Card className="p-4 sm:p-5 space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-on">
          {t("warehouse:costVariances.sectionTitle")}
        </h2>
        <p className="text-sm text-on-secondary mt-1">
          {t("warehouse:costVariances.sectionSubtitle")}
        </p>
      </div>

      {data.variances.length > 0 && (
        <>
          <ul className="divide-y divide-border border border-border rounded-xl overflow-hidden">
            {data.variances.map((variance) => (
              <li
                key={variance.id}
                className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm"
              >
                <span className="min-w-0 text-on">
                  {t(`warehouse:extraCosts.kind.${variance.kind}`, {
                    defaultValue: variance.kind,
                  })}
                  <span className="text-on-muted">
                    {" · "}
                    {formatDate(variance.occurred_on)}
                    {" · "}
                    {variance.reason}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-3">
                  <span className="tabular-nums text-on">
                    {money(Number(variance.amount), variance.currency)}
                  </span>
                  {canManage && (
                    <Button
                      variant="ghostDanger"
                      size="icon"
                      aria-label={t("warehouse:costVariances.removeLabel")}
                      onClick={() => remove.mutate(variance.id)}
                    >
                      <Trash2 size={16} />
                    </Button>
                  )}
                </span>
              </li>
            ))}
          </ul>
          <p className="text-sm font-medium text-on">
            {t("warehouse:costVariances.total")}:{" "}
            <span className="tabular-nums">
              {money(Number(data.variance_total), data.currency)}
            </span>
          </p>
        </>
      )}

      {canRecord && (
        <div className="flex flex-wrap items-end gap-3">
          <NativeSelect
            label={t("warehouse:extraCosts.kindLabel")}
            wrapperClassName="w-full sm:w-40"
            value={kind}
            onChange={(event) => setKind(event.target.value as ExtraCostKind)}
          >
            {KINDS.map((value) => (
              <option key={value} value={value}>
                {t(`warehouse:extraCosts.kind.${value}`)}
              </option>
            ))}
          </NativeSelect>
          <Input
            label={t("warehouse:extraCosts.amountLabel")}
            wrapperClassName="w-full sm:w-32"
            inputMode="decimal"
            aria-required
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
          />
          <Input
            label={t("warehouse:costVariances.reasonLabel")}
            wrapperClassName="w-full sm:flex-1 sm:min-w-56"
            maxLength={255}
            aria-required
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
          <DateInput
            label={t("warehouse:costVariances.dayLabel")}
            wrapperClassName="w-full sm:w-56"
            value={day}
            onChange={setDay}
            // A cost that has not happened yet is not a variance to record.
            max={todayIso()}
            required
          />
          <Button
            leftIcon={<Plus size={16} />}
            onClick={submit}
            isLoading={add.isPending}
            disabled={!amount.trim() || !reason.trim() || !day}
          >
            {t("warehouse:costVariances.record")}
          </Button>
        </div>
      )}
    </Card>
  );
}
