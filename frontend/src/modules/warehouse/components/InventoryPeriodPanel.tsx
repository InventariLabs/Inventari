import { useState } from "react";
import type { TFunction } from "i18next";
import { useCanManage } from "@/hooks/useCanWrite";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Lock, Unlock } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Select } from "@/components/ui/Select";
import { formatDate, formatMonthName } from "@/utils/formatters";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryFailure } from "@/components/ui/QueryResult";
import {
  useInventoryPeriods,
  useClosePeriod,
  useReopenPeriod,
} from "@/modules/warehouse/hooks/useInventoryPeriods";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import type { InventoryPeriod } from "@/modules/warehouse/types";
import { extractApiError } from "@/lib/errors";

/**
 * The one line a month has room for about its own history.
 *
 * Closed wins over reopened: a month closed, unlocked and closed again is
 * closed, and that is the state the reader is being asked about. The name is
 * optional because the column is — a period closed by a job rather than a
 * person still gets its date.
 */
function periodTrace(
  period: InventoryPeriod | undefined,
  isClosed: boolean,
  t: TFunction<"warehouse">,
): string | null {
  if (isClosed && period?.closed_at) {
    return period.closed_by
      ? t("periods.closedTrace", {
          user: period.closed_by,
          date: formatDate(period.closed_at),
        })
      : t("periods.closedTraceAnon", { date: formatDate(period.closed_at) });
  }
  if (!isClosed && period?.reopened_at) {
    return period.reopened_by
      ? t("periods.reopenedTrace", {
          user: period.reopened_by,
          date: formatDate(period.reopened_at),
        })
      : t("periods.reopenedTraceAnon", {
          date: formatDate(period.reopened_at),
        });
  }
  return null;
}

export default function InventoryPeriodPanel() {
  const { t } = useTranslation("warehouse");
  const canManage = useCanManage("warehouse");
  const [selectedYear, setSelectedYear] = useState(() =>
    new Date().getFullYear(),
  );
  const [confirmAction, setConfirmAction] = useState<{
    year: number;
    month: number;
    action: "close" | "reopen";
  } | null>(null);

  const {
    data: periods,
    isLoading,
    isError,
    error,
    refetch,
  } = useInventoryPeriods(selectedYear);
  const closePeriod = useClosePeriod();
  const reopenPeriod = useReopenPeriod();

  const months = Array.from({ length: 12 }, (_, i) => i + 1);

  const getPeriodForMonth = (month: number) =>
    periods?.find((p) => p.month === month);

  const handleConfirm = () => {
    if (!confirmAction) return;
    const { year, month, action } = confirmAction;
    const mutation = action === "close" ? closePeriod : reopenPeriod;
    mutation.mutate(
      { year, month },
      {
        onSuccess: () => {
          toast.success(
            action === "close"
              ? t("periods.closeSuccess")
              : t("periods.reopened"),
          );
          setConfirmAction(null);
        },
        onError: (err) => {
          toast.error(
            extractApiError(
              err,
              action === "close"
                ? t("periods.closeFailed")
                : t("periods.reopenFailed"),
            ),
          );
          setConfirmAction(null);
        },
      },
    );
  };

  // An unmarked grid is the same picture as a year with nothing closed.
  if (isError) {
    return (
      <QueryFailure
        error={error}
        message={t("errors.loadPeriodsFailed")}
        onRetry={() => refetch()}
      />
    );
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-20">
        <LoadingSpinner />
      </div>
    );
  }

  const today = new Date();
  const currentYear = today.getFullYear();
  const currentMonth = today.getMonth() + 1;
  const years = [currentYear - 1, currentYear, currentYear + 1];

  // Closing a month that has not happened yet locks out documents nobody has
  // written, and nothing on the row says so — the padlock looked identical to
  // the one on a month that is over.
  const isFuture = (month: number) =>
    selectedYear > currentYear ||
    (selectedYear === currentYear && month > currentMonth);
  const isCurrent = (month: number) =>
    selectedYear === currentYear && month === currentMonth;

  return (
    <div className="space-y-6">
      <Card className="overflow-hidden">
        <div className="px-4 sm:px-6 py-4">
          <div className="flex items-center gap-3 mb-4">
            <Select
              label={t("periods.yearLabel")}
              value={String(selectedYear)}
              onChange={(id) => setSelectedYear(Number(id))}
              options={years.map((y) => ({ id: String(y), name: String(y) }))}
            />
          </div>

          {/* Two columns need room for a month name and the lock beside it.
              Below 480px a tile is under 140px wide, the lock takes 40 of them, and
              the name — a single word that cannot break — was painted across
              the button. One column there; two from 480px up, where the pair
              measures clear. */}
          <div className="grid grid-cols-1 min-[480px]:grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
            {months.map((month) => {
              const period = getPeriodForMonth(month);
              const isClosed = period?.is_closed ?? false;
              const monthName = formatMonthName(selectedYear, month);
              // A month that was closed and then unlocked used to look
              // exactly like one nobody had ever touched — an empty cell
              // either way — while the API had been sending `reopened_at`,
              // `reopened_by` and the note all along. Whoever asks who took
              // the lock off March is asking a question the system can
              // answer.
              const wasReopened = !isClosed && !!period?.reopened_at;
              const trace = periodTrace(period, isClosed, t);

              return (
                <div
                  key={month}
                  className="flex items-start justify-between gap-2 rounded-lg border border-border px-3 py-2"
                >
                  <div className="min-w-0 space-y-0.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium text-on capitalize">
                        {monthName}
                      </span>
                      {isClosed && (
                        <Badge variant="danger">{t("periods.closed")}</Badge>
                      )}
                      {wasReopened && (
                        <Badge variant="warning">
                          {t("periods.reopenedBadge")}
                        </Badge>
                      )}
                      {!isClosed && isCurrent(month) && (
                        <Badge variant="info">{t("periods.current")}</Badge>
                      )}
                      {/* A month over with the lock off used to show
                          nothing at all — the same picture as a year with
                          nothing recorded — while the truth is that the
                          month is open and takes documents. Every other
                          state of a month already had its word. */}
                      {!isClosed &&
                        !wasReopened &&
                        !isCurrent(month) &&
                        !isFuture(month) && (
                          <Badge variant="success">{t("periods.open")}</Badge>
                        )}
                    </div>
                    {/* Under the name, not beside it. Two columns of tiles on
                        a phone leave 133px, and a month name and its status do
                        not both fit on that line: the name overflowed its own
                        column and was drawn over the status — "Październik"
                        and "Jeszcze się nie zaczął" on top of each other, on
                        the screen that closes a month for good. */}
                    {isFuture(month) && (
                      <p className="text-xs text-on-muted">
                        {t("periods.notStarted")}
                      </p>
                    )}
                    {trace && <p className="text-xs text-on-muted">{trace}</p>}
                    {period?.notes && (
                      <p className="text-xs text-on-muted italic break-words">
                        {period.notes}
                      </p>
                    )}
                  </div>
                  {/* The lock and the unlock both need warehouse:manage —
                      the key the periods endpoints check. Without it the row
                      is a record of the month, and the badge beside the name
                      already says whether it is closed. */}
                  {isFuture(month) || !canManage ? null : isClosed ? (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        setConfirmAction({
                          year: selectedYear,
                          month,
                          action: "reopen",
                        })
                      }
                      disabled={reopenPeriod.isPending}
                      aria-label={t("periods.reopenAria", {
                        month: monthName,
                        year: selectedYear,
                      })}
                    >
                      <Unlock size={14} />
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        setConfirmAction({
                          year: selectedYear,
                          month,
                          action: "close",
                        })
                      }
                      disabled={closePeriod.isPending}
                      aria-label={t("periods.closeAria", {
                        month: monthName,
                        year: selectedYear,
                      })}
                    >
                      <Lock size={14} />
                    </Button>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </Card>

      {confirmAction && (
        <ConfirmDialog
          open={!!confirmAction}
          title={
            confirmAction.action === "close"
              ? t("periods.confirmClose")
              : t("periods.confirmReopen")
          }
          message={
            confirmAction.action === "close"
              ? t("periods.confirmCloseMessage", {
                  month: formatMonthName(
                    confirmAction.year,
                    confirmAction.month,
                  ),
                  year: confirmAction.year,
                })
              : t("periods.confirmReopenMessage", {
                  month: formatMonthName(
                    confirmAction.year,
                    confirmAction.month,
                  ),
                  year: confirmAction.year,
                })
          }
          variant={confirmAction.action === "close" ? "default" : "danger"}
          onConfirm={handleConfirm}
          onCancel={() => setConfirmAction(null)}
        />
      )}
    </div>
  );
}
