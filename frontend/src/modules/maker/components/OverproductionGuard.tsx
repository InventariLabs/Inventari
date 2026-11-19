import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Checkbox } from "@/module-sdk";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { overproductionExtra } from "@/modules/maker/lib/overproduction";
import type { ProductionOrder } from "@/modules/maker/types/maker";

/**
 * The question a closing quantity far above the plan has to answer: it names
 * the extra quantity, says the ingredients stay as planned, and holds the
 * dialog's confirm button until the person ticks the box for that very
 * quantity — typing another number asks again.
 *
 * Shared by the two dialogs that close a run, since the rule behind it is one.
 */
export function useOverproductionGuard(order: ProductionOrder, typed: string) {
  const { t } = useTranslation("maker");
  const [acknowledged, setAcknowledged] = useState("");
  const extra = overproductionExtra(order.planned_qty, typed);
  const value = typed.trim();

  // An emptied field (a dialog opened afresh) forgets the tick.
  useEffect(() => {
    if (value === "") setAcknowledged("");
  }, [value]);

  const notice: ReactNode =
    extra === null ? null : (
      <div
        role="alert"
        className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 space-y-2"
        data-testid="maker-overproduction-notice"
      >
        <p>
          {t("overproduction.warning", {
            extra: formatQuantityLocalized(t, extra, order.output_uom_symbol),
            planned: formatQuantityLocalized(
              t,
              order.planned_qty,
              order.output_uom_symbol,
            ),
          })}
        </p>
        <Checkbox
          label={t("overproduction.confirm")}
          checked={acknowledged === value}
          onChange={(e) => setAcknowledged(e.target.checked ? value : "")}
          data-testid="maker-overproduction-confirm"
        />
      </div>
    );

  return {
    notice,
    /** True while the quantity needs a tick that has not been given. */
    blocked: extra !== null && acknowledged !== value,
  };
}
