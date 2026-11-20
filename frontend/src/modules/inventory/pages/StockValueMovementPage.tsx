/**
 * StockValueMovementPage — /inventory/stock/value-movement
 *
 * What the stock was worth when a period opened, what moved it, and what it
 * was worth when it closed — the three figures a bookkeeper asks for. The
 * opening and the closing are the stock-on-a-date report for the evening
 * before the first day and for the last one; the lines between are what the
 * cost layers say came in and went out.
 *
 * Like that report it refuses rather than guesses: a period that opens
 * before the ledger's first movement comes back with the boundary named, and
 * that sentence is printed where the table would be.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { FileDown, Info } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { DateInput } from "@/components/ui/DateInput";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryError } from "@/components/ui/QueryResult";
import { useFilteredList } from "@/hooks/useFilteredList";
import { useShowInventoryValue } from "@/modules/shared/hooks/useShowInventoryValue";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useMoney } from "@/hooks/useMoney";
import { extractApiError, isServerRefusal } from "@/lib/errors";
import {
  stockValueMovementApi,
  type StockValueMovement,
} from "../api/stockValueMovement";
import { downloadBlob } from "@/utils/helpers";
import { formatDate, todayIso } from "@/utils/formatters";
import { useStockValueMovement } from "../hooks/useStockValueMovement";

/** Whether the address names a calendar day. */
function isDay(value: string): boolean {
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !Number.isNaN(new Date(`${value}T00:00`).getTime())
  );
}

type LineKey =
  | "receipts"
  | "internal_receipts"
  | "used"
  | "disposed"
  | "dispatched"
  | "other_issues"
  | "work_in_progress_change"
  | "other_changes";

export default function StockValueMovementPage() {
  const { t } = useTranslation(["inventory", "common"]);
  const { setHeader } = useModulePageHeader();
  const money = useMoney();
  // The statement is nothing but value: where the profile withholds the
  // figure the screen says so instead of printing it, and offers no file.
  const showInventoryValue = useShowInventoryValue();

  // The period lives in the address, so a refresh keeps the statement and a
  // copied link opens the same one. It opens on the current month.
  const [today] = useState(todayIso);
  const filters = useFilteredList(
    {
      from: { default: "", urlKey: "from" },
      to: { default: today, urlKey: "to" },
    },
    { limit: 1, syncToUrl: true },
  );
  const to = isDay(String(filters.values.to))
    ? String(filters.values.to)
    : today;
  // No first day picked (a fresh page, or a link that names only the last
  // day — the stock-on-a-date screen's): the server opens the period on the
  // month that day is in, or on the first day its ledger can open on, so a
  // new organization is shown a statement and not a refusal. The field then
  // shows the day the statement came back for.
  const pickedFrom = isDay(String(filters.values.from))
    ? String(filters.values.from)
    : null;
  useEffect(() => {
    setHeader({
      title: t("inventory:valueMovement.title"),
      subtitle: t("inventory:valueMovement.subtitle"),
    });
  }, [setHeader, t]);

  const query = pickedFrom
    ? { date_from: pickedFrom, date_to: to }
    : { date_to: to };
  const {
    data: statement,
    isLoading,
    isError,
    error,
    refetch,
  } = useStockValueMovement(query, showInventoryValue);
  const from = pickedFrom ?? statement?.date_from ?? `${to.slice(0, 8)}01`;

  const download = async () => {
    try {
      toast.loading(t("common:actions.exporting"), { id: "value-movement" });
      const blob = await stockValueMovementApi.exportXlsx(query);
      downloadBlob(blob, `value_movement_${from}_${to}.xlsx`);
      toast.success(t("common:actions.exportSuccess"), {
        id: "value-movement",
      });
    } catch (caught) {
      toast.error(extractApiError(caught, t("common:actions.exportError")), {
        id: "value-movement",
      });
    }
  };

  return (
    <div className="space-y-6">
      <Card className="p-4">
        <div className="flex flex-wrap items-end gap-3">
          <DateInput
            label={t("inventory:valueMovement.from")}
            value={from}
            onChange={(value) => filters.setFilter("from", value)}
            wrapperClassName="w-full sm:w-48"
          />
          <DateInput
            label={t("inventory:valueMovement.to")}
            value={to}
            onChange={(value) => filters.setFilter("to", value || today)}
            presets={["today", "yesterday"]}
            wrapperClassName="w-full sm:w-48"
          />
          <div className="sm:ml-auto">
            <Button
              variant="outline"
              leftIcon={<FileDown size={16} />}
              onClick={() => void download()}
              disabled={
                !showInventoryValue ||
                !statement ||
                statement.value_source == null
              }
            >
              {t("common:actions.export")}
            </Button>
          </div>
        </div>
      </Card>

      {!showInventoryValue ? (
        <Card className="p-4">
          <div className="flex items-start gap-2 text-on-secondary" role="note">
            <Info size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
            <p className="text-sm">
              {t("inventory:valueMovement.valueHidden")}
            </p>
          </div>
        </Card>
      ) : isLoading ? (
        <LoadingSpinner />
      ) : isError && !isServerRefusal(error) ? (
        <QueryError error={error} onRetry={() => void refetch()} />
      ) : isError ? (
        // The refusal is the answer: it names the day the ledger starts, or
        // says the period ends before it begins.
        <Card className="p-4">
          <div className="flex items-start gap-2 text-on-secondary" role="note">
            <Info size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
            <p className="text-sm">
              {extractApiError(
                error,
                t("inventory:valueMovement.cannotAnswer"),
              )}
            </p>
          </div>
        </Card>
      ) : statement ? (
        <Statement statement={statement} money={money} />
      ) : null}
    </div>
  );
}

interface StatementProps {
  statement: StockValueMovement;
  money: (amount: number | string | null | undefined) => string;
}

function Statement({ statement, money }: StatementProps) {
  const { t } = useTranslation(["inventory"]);

  // An organization that keeps no cost history has quantities and no
  // figure: say that, instead of a column of dashes dressed as a statement.
  if (statement.value_source == null || statement.opening_value == null) {
    return (
      <Card className="p-4">
        <div className="flex items-start gap-2 text-on-secondary" role="note">
          <Info size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
          <p className="text-sm">
            {t("inventory:valueMovement.noValueSource")}
          </p>
        </div>
      </Card>
    );
  }

  // The lines between the opening and the closing. The first three always
  // print — a period in which nothing was used says so; the rest print only
  // when they hold something, so a statement is not padded with rows that
  // apply to few organizations.
  const lines: { key: LineKey; label: string; always: boolean }[] = [
    {
      key: "receipts",
      label: t("inventory:valueMovement.lines.receipts"),
      always: true,
    },
    {
      key: "internal_receipts",
      label: t("inventory:valueMovement.lines.internal_receipts"),
      always: false,
    },
    {
      key: "used",
      label: t("inventory:valueMovement.lines.used"),
      always: true,
    },
    {
      key: "disposed",
      label: t("inventory:valueMovement.lines.disposed"),
      always: true,
    },
    {
      key: "dispatched",
      label: t("inventory:valueMovement.lines.dispatched"),
      always: false,
    },
    {
      key: "other_issues",
      label: t("inventory:valueMovement.lines.other_issues"),
      always: false,
    },
    {
      key: "work_in_progress_change",
      label: t("inventory:valueMovement.lines.work_in_progress_change"),
      always: false,
    },
    {
      key: "other_changes",
      label: t("inventory:valueMovement.lines.other_changes"),
      always: false,
    },
  ];
  const shown = lines.filter(
    ({ key, always }) => always || Number(statement[key] ?? 0) !== 0,
  );

  return (
    <>
      <div className="bg-surface-card rounded-xl sm:rounded-2xl shadow-sm border border-border overflow-hidden">
        <div className="relative overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <caption className="sr-only">
              {t("inventory:valueMovement.caption", {
                from: formatDate(statement.date_from),
                to: formatDate(statement.date_to),
                organization: statement.organization_name ?? "",
              })}
            </caption>
            <thead>
              <tr className="bg-surface-raised border-b border-border text-xs font-medium text-on-secondary uppercase tracking-wider">
                <th scope="col" className="px-4 py-3">
                  {t("inventory:valueMovement.columns.line")}
                </th>
                <th scope="col" className="px-4 py-3 text-right">
                  {t("inventory:valueMovement.columns.value")}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-border text-sm font-semibold bg-surface-raised">
                <th scope="row" className="px-4 py-3 text-left text-on">
                  {t("inventory:valueMovement.opening", {
                    date: formatDate(statement.date_from),
                  })}
                </th>
                <td className="px-4 py-3 text-right tabular-nums text-on whitespace-nowrap">
                  {money(Number(statement.opening_value))}
                </td>
              </tr>
              {shown.map(({ key, label }) => (
                <tr key={key} className="border-b border-border text-sm">
                  <th
                    scope="row"
                    className="px-4 py-2.5 text-left font-normal text-on"
                  >
                    {label}
                  </th>
                  <td className="px-4 py-2.5 text-right tabular-nums text-on whitespace-nowrap">
                    {money(Number(statement[key] ?? 0))}
                  </td>
                </tr>
              ))}
              <tr className="text-sm font-semibold bg-surface-raised">
                <th scope="row" className="px-4 py-3 text-left text-on">
                  {t("inventory:valueMovement.closing", {
                    date: formatDate(statement.date_to),
                  })}
                </th>
                <td className="px-4 py-3 text-right tabular-nums text-on whitespace-nowrap">
                  {money(Number(statement.closing_value))}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="space-y-1 text-xs text-on-muted px-1">
        <p>
          {t("inventory:valueMovement.completeFrom", {
            date: formatDate(statement.complete_from),
          })}
        </p>
        {Boolean(statement.excluded_currency_receipts) && (
          <p>
            {t("inventory:valueMovement.excludedCurrency", {
              count: statement.excluded_currency_receipts ?? 0,
            })}
          </p>
        )}
      </div>
    </>
  );
}
