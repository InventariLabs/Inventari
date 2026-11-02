import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/Card";
import type { TranslateFn } from "@/types/i18n";
import type { WorkItemMeasures } from "@/modules/warehouse/types";
import { splitDuration } from "./boardColumns";

function durationText(t: TranslateFn, seconds: number): string {
  const { hours, minutes } = splitDuration(seconds);
  return hours > 0
    ? t("warehouse:board.measures.hoursMinutes", { hours, minutes })
    : t("warehouse:board.measures.minutes", { minutes });
}

function Measure({
  label,
  children,
  tone,
}: {
  label: string;
  children: React.ReactNode;
  tone?: "warning";
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-on-secondary">{label}</span>
      <span
        className={`text-sm font-medium tabular-nums ${
          tone === "warning" ? "text-on-warning" : "text-on"
        }`}
      >
        {children}
      </span>
    </div>
  );
}

/**
 * The strip above the board: how long goods stood on the dock this week, how
 * many orders left on the day they were raised, and how many cards are late.
 * Every number is counted from the records, never typed in.
 */
export function BoardMeasures({
  measures,
  failed,
  overdue,
  overdueFailed = false,
}: {
  measures: WorkItemMeasures | undefined;
  failed: boolean;
  /** The late-card count could not be read. */
  overdueFailed?: boolean;
  /** `null` while the count is not known (loading, or it failed). */
  overdue: number | null;
}) {
  const { t } = useTranslation("warehouse");
  return (
    <Card className="flex flex-wrap items-center gap-x-8 gap-y-3 p-4">
      <Measure label={t("board.measures.dockToStock")}>
        {failed || !measures
          ? "—"
          : measures.dock_to_stock_seconds == null
            ? t("board.measures.dockNone")
            : t("board.measures.average", {
                duration: durationText(t, measures.dock_to_stock_seconds),
              })}
      </Measure>
      <Measure label={t("board.measures.sameDay")}>
        {failed || !measures
          ? "—"
          : measures.shipped_total === 0
            ? t("board.measures.sameDayNone")
            : t("board.measures.sameDayValue", {
                shipped: measures.shipped_same_day,
                total: measures.shipped_total,
              })}
      </Measure>
      <Measure
        label={t("board.measures.overdue")}
        tone={overdue ? "warning" : undefined}
      >
        {overdue === null
          ? "—"
          : overdue === 0
            ? t("board.measures.overdueNone")
            : t("board.measures.overdueValue", { count: overdue })}
      </Measure>
      {(failed || overdueFailed) && (
        <span role="alert" className="text-xs text-on-warning">
          {t("board.measures.failed")}
        </span>
      )}
    </Card>
  );
}
