import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Checkbox } from "@/module-sdk";
import { DateInput } from "@/components/ui/DateInput";
import { extractApiError } from "@/lib/errors";
import { todayIso } from "@/utils/formatters";
import { useTickStep } from "@/modules/maker/hooks/useProduction";
import type { ProductionOrder } from "@/modules/maker/types/maker";

/**
 * The formula's process steps on a run that takes days: each is ticked with
 * the day it was done (racked on this day, filtered on that), and the day can
 * be corrected after.
 */
export function RunSteps({
  order,
  canWrite,
}: {
  order: ProductionOrder;
  canWrite: boolean;
}) {
  const { t } = useTranslation("maker");
  const tick = useTickStep();
  const steps = order.steps ?? [];
  if (steps.length === 0) return null;

  function setDay(index: number, doneOn: string | null) {
    tick.mutate(
      { orderId: order.id, index, doneOn },
      {
        onError: (err) =>
          toast.error(extractApiError(err, t("progress.stepFailed"))),
      },
    );
  }

  return (
    <section className="space-y-3" aria-labelledby="run-steps-title">
      <h2 id="run-steps-title" className="text-base font-medium text-on">
        {t("progress.steps")}
      </h2>
      <ul className="divide-y divide-border rounded-xl border border-border bg-surface-card">
        {steps.map((step, index) => (
          <li
            key={`${index}-${step.text}`}
            className="flex flex-wrap items-center justify-between gap-3 px-4 py-2"
          >
            <Checkbox
              touchTarget
              label={step.text}
              checked={Boolean(step.done_on)}
              disabled={!canWrite || tick.isPending}
              onChange={(e) =>
                setDay(index, e.target.checked ? todayIso() : null)
              }
              data-testid={`maker-step-${index}-checkbox`}
            />
            {step.done_on && (
              <DateInput
                aria-label={t("progress.stepDay", { step: step.text })}
                value={step.done_on}
                max={todayIso()}
                disabled={!canWrite}
                onChange={(day) => day && setDay(index, day)}
                wrapperClassName="w-44"
              />
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
