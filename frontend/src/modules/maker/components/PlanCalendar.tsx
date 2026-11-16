import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { CalendarClock } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { DateInput } from "@/components/ui/DateInput";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
  SheetHeader,
} from "@/components/ui/Sheet";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { formatDate } from "@/utils/formatters";
import { ProductionCoverageBadge } from "@/modules/maker/components/ProductionCoverageBadge";
import { useUpdateProductionOrder } from "@/modules/maker/hooks/useProduction";
import type { PlanPeriod } from "@/modules/maker/lib/planPeriod";
import type { ProductionOrder } from "@/modules/maker/types/maker";

interface PlanCalendarProps {
  period: PlanPeriod;
  orders: ProductionOrder[];
  canWrite: boolean;
}

/**
 * The planned runs of a week or a month, by day.
 *
 * A grid of days from `md` up; on a phone it is a list by day, the days with
 * nothing planned left out — a month of empty rows says nothing. A run is
 * moved to another day from here, which also moves it in the queue the plan
 * counts the shelf in.
 */
export function PlanCalendar({ period, orders, canWrite }: PlanCalendarProps) {
  const { t } = useTranslation("maker");
  const [moving, setMoving] = useState<ProductionOrder | null>(null);
  const byDay = new Map<string, ProductionOrder[]>();
  for (const order of orders) {
    if (!order.production_date) continue;
    byDay.set(order.production_date, [
      ...(byDay.get(order.production_date) ?? []),
      order,
    ]);
  }

  return (
    <>
      <ol
        className="grid grid-cols-1 md:grid-cols-7 gap-2"
        data-testid="maker-plan-calendar"
      >
        {Array.from({ length: period.leading }, (_, i) => (
          <li key={`blank-${i}`} aria-hidden className="hidden md:block" />
        ))}
        {period.days.map((day) => {
          const runs = byDay.get(day) ?? [];
          return (
            <li
              key={day}
              className={`rounded-lg border border-border bg-surface p-2 min-h-16 ${
                runs.length === 0 ? "hidden md:block" : ""
              }`}
              data-testid={`maker-plan-day-${day}`}
            >
              <div className="text-xs font-medium text-on-secondary mb-1">
                {formatDate(day)}
              </div>
              <ul className="space-y-2">
                {runs.map((order) => (
                  <li key={order.id} className="text-sm">
                    <Link
                      to={`/maker/production/${order.id}`}
                      className="font-medium text-on hover:text-accent"
                    >
                      {order.output_template_name ?? order.number}
                    </Link>
                    <div className="text-xs text-on-secondary">
                      {formatQuantityLocalized(
                        t,
                        order.planned_qty,
                        order.output_uom_symbol,
                      )}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-1">
                      <ProductionCoverageBadge coverage={order.coverage} />
                      {canWrite && (
                        <Button
                          size="sm"
                          variant="ghost"
                          leftIcon={<CalendarClock size={14} />}
                          onClick={() => setMoving(order)}
                          aria-label={t("planning.move.aria", {
                            name: order.output_template_name ?? order.number,
                          })}
                        >
                          {t("planning.move.button")}
                        </Button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </li>
          );
        })}
      </ol>
      <MoveRunSheet order={moving} onClose={() => setMoving(null)} />
    </>
  );
}

function MoveRunSheet({
  order,
  onClose,
}: {
  order: ProductionOrder | null;
  onClose: () => void;
}) {
  const { t } = useTranslation("maker");
  const update = useUpdateProductionOrder(t("planning.move.failed"));
  const [day, setDay] = useState("");
  const [seen, setSeen] = useState<string | null>(null);
  // Start from the run's own day each time the sheet opens on another run.
  if (order && seen !== order.id) {
    setSeen(order.id);
    setDay(order.production_date ?? "");
  }
  const changed = !!order && day !== "" && day !== order.production_date;
  return (
    <Sheet
      open={order !== null}
      onClose={onClose}
      maxWidth="sm"
      aria-label={t("planning.move.title", {
        name: order?.output_template_name ?? order?.number ?? "",
      })}
    >
      <SheetHeader
        title={t("planning.move.title", {
          name: order?.output_template_name ?? order?.number ?? "",
        })}
        onClose={onClose}
      />
      <SheetBody className="p-5">
        <DateInput
          label={t("planning.move.day")}
          value={day}
          onChange={setDay}
        />
        {order?.production_date && (
          <p className="mt-2 text-xs text-on-secondary">
            {t("planning.move.now", {
              date: formatDate(order.production_date),
            })}
          </p>
        )}
      </SheetBody>
      <SheetFooter>
        <SheetActions>
          <Button variant="ghost" onClick={onClose}>
            {t("planning.move.cancel")}
          </Button>
          <Button
            disabled={!changed}
            isLoading={update.isPending}
            onClick={() =>
              order &&
              update.mutate(
                { orderId: order.id, data: { production_date: day } },
                { onSuccess: onClose },
              )
            }
          >
            {t("planning.move.save")}
          </Button>
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}
