/**
 * StockAsOfPage — /inventory/stock/as-of
 *
 * What was in stock on a day. An auditor, an accountant closing a
 * quarter and an insurer after a fire all ask it, and until now the
 * application could only answer "what is on the shelf now".
 *
 * It refuses rather than guesses: a date before the ledger's first movement
 * comes back with the boundary named, and that sentence is the answer — so
 * it is printed where the table would be, not swallowed into a red toast.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Boxes, FileDown, Info, Printer } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ListControlBar } from "@/components/ui/ListControlBar";
import { DateInput } from "@/components/ui/DateInput";
import { LocationCombobox } from "@/module-sdk";
import { useLocationsById } from "@/module-sdk";
import { EmptyState } from "@/components/ui/EmptyState";
import LoadingSpinner from "@/components/LoadingSpinner";
import Pagination from "@/components/ui/Pagination";
import { useFilteredList } from "@/hooks/useFilteredList";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { downloadBlob } from "@/utils/helpers";
import { formatDate, formatDecimalQty, todayIso } from "@/utils/formatters";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { extractApiError, isServerRefusal } from "@/lib/errors";
import { QueryError } from "@/components/ui/QueryResult";
import { useMoney } from "@/hooks/useMoney";
import { useShowInventoryValue } from "@/modules/shared/hooks/useShowInventoryValue";
import { stockAsOfApi, type StockAsOfReport } from "@/lib/api/stockAsOf";
import type { TranslateFn } from "@/types/i18n";
import { useStockAsOf } from "../hooks/useStockAsOf";

/**
 * The last instant of the chosen day on the reader's own clock — the day
 * belongs to the report, and the clock that names the reader's days is
 * theirs, not UTC's. A `Z` here made a Tokyo reader's "September 12th"
 * answer for movements booked until 08:59 on the thirteenth.
 */
export function endOfDay(day: string): string {
  return new Date(`${day}T23:59:59.999`).toISOString();
}

/** Whether the address names a calendar day `endOfDay` can close. */
function isDay(value: string): boolean {
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !Number.isNaN(new Date(`${value}T00:00`).getTime())
  );
}

/** Rows per page: a phone reads fifty comfortably, and a page is one request. */
const PAGE_SIZE = 50;

interface StockAsOfResultProps {
  report: StockAsOfReport;
  day: string;
  showInventoryValue: boolean;
  money: (
    amount: number | string | null | undefined,
    currency?: string | null,
  ) => string;
  t: TranslateFn;
}

/**
 * The report proper: the shelves as a table, and the footnotes that qualify
 * it.
 *
 * The value switch lives here rather than as one condition per row, so a
 * profile that does not show stock value drops the money column, its total
 * and every cost-ledger note together, and keeps what the shelf held.
 */
function StockAsOfResult({
  report,
  day,
  showInventoryValue,
  money,
  t,
}: StockAsOfResultProps) {
  const rows = report.items;
  // A product is worth what its priced receipts still hold; one whose shelf
  // holds nothing anybody priced is worth nothing anybody can state, and the
  // total has to say how much of the shelf it could not price. No figure is
  // stated where the profile does not show stock value, so nothing is "left
  // out of" it either. The count is the server's, over every page.
  const unpriced =
    showInventoryValue && report.value_source != null ? report.unpriced : 0;

  return (
    <>
      <div className="bg-surface-card rounded-xl sm:rounded-2xl shadow-sm border border-border overflow-hidden">
        <div className="relative overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <caption className="sr-only">
              {t("inventory:asOf.caption", {
                date: formatDate(day),
                organization: report.organization_name ?? "",
              })}
            </caption>
            <thead>
              <tr className="bg-surface-raised border-b border-border text-xs font-medium text-on-secondary uppercase tracking-wider">
                <th scope="col" className="px-4 py-3">
                  {t("inventory:asOf.columns.product")}
                </th>
                <th scope="col" className="px-4 py-3 text-right">
                  {t("inventory:asOf.columns.quantity")}
                </th>
                {showInventoryValue && (
                  <th scope="col" className="px-4 py-3 text-right">
                    {t("inventory:asOf.columns.value")}
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.product_template_id}
                  className="border-b border-border last:border-0 text-sm"
                >
                  <td className="px-4 py-2.5 text-on">
                    {row.product_name ?? "—"}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-on whitespace-nowrap">
                    {formatQuantityLocalized(
                      t,
                      formatDecimalQty(row.quantity),
                      row.uom_symbol,
                    )}
                  </td>
                  {showInventoryValue && (
                    <td className="px-4 py-2.5 text-right tabular-nums text-on whitespace-nowrap">
                      {row.value != null ? money(Number(row.value)) : "—"}
                    </td>
                  )}
                </tr>
              ))}
              {showInventoryValue && report.total_value != null && (
                <tr className="text-sm font-semibold bg-surface-raised">
                  <td className="px-4 py-3 text-on">
                    {t("inventory:asOf.total")}
                  </td>
                  <td className="px-4 py-3" />
                  <td className="px-4 py-3 text-right tabular-nums text-on whitespace-nowrap">
                    {money(Number(report.total_value))}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="space-y-1 text-xs text-on-muted px-1">
        <p>
          {t("inventory:asOf.completeFrom", {
            date: formatDate(report.complete_from),
          })}
        </p>
        {unpriced > 0 && (
          <p>{t("inventory:asOf.unpriced", { count: unpriced })}</p>
        )}
        {showInventoryValue && report.value_source == null && (
          // Not a zero dressed as a valuation: `purchase_price` is a
          // field on a form today and cannot say what a shelf was worth
          // last month (decision D2 of the standards audit).
          <p>{t("inventory:asOf.noValueSource")}</p>
        )}
        {showInventoryValue && Boolean(report.excluded_currency_rows) && (
          <p>
            {t("inventory:asOf.excludedCurrency", {
              count: report.excluded_currency_rows ?? 0,
            })}
          </p>
        )}
      </div>
    </>
  );
}

export default function StockAsOfPage() {
  const { t } = useTranslation(["inventory", "common"]);
  const { setHeader } = useModulePageHeader();
  const money = useMoney();
  // The value is a business metric: the home profile presets it off and an
  // admin can flip it back. The report stays — what the shelves held is
  // quantity, not a metric — but the money column, its total and the
  // cost-ledger notes go with the switch.
  const showInventoryValue = useShowInventoryValue();

  // The report opens on the reader's own day — `toISOString()` answers in
  // UTC, which west of Greenwich is tomorrow for the whole evening. The day
  // and the place live in the address, so a refresh keeps the report and a
  // copied link opens the same one; today is the absence of a day, so a
  // link to "now" still means now when it is opened next week. A warehouse
  // of a hundred thousand products is read a page at a time, and another
  // day or another place is another report: back to its first page.
  const [today] = useState(todayIso);
  const filters = useFilteredList(
    {
      day: { default: today, urlKey: "date" },
      location: { default: "", urlKey: "location" },
    },
    {
      limit: PAGE_SIZE,
      syncToUrl: true,
      // The stock list links here with what it was narrowed to, so the
      // reader keeps the product they were looking at.
      urlSearchKey: "search",
    },
  );
  // A day typed into the address, or a cleared field, must not take the
  // page down with it: the report cannot end a day that does not exist.
  const day = isDay(String(filters.values.day))
    ? String(filters.values.day)
    : today;
  const locationId = String(filters.values.location);
  const { skip: offset, setSkip: setOffset, limit, setLimit } = filters;

  useEffect(() => {
    setHeader({
      title: t("inventory:asOf.title"),
      subtitle: showInventoryValue
        ? t("inventory:asOf.subtitle")
        : t("inventory:asOf.subtitleNoValue"),
    });
  }, [setHeader, t, showInventoryValue]);

  const query = {
    as_of: endOfDay(day),
    location_id: locationId || undefined,
    search: filters.search || undefined,
  };
  const {
    data: report,
    isLoading,
    isError,
    error,
    refetch,
  } = useStockAsOf({ ...query, limit, offset });

  // With one place picked, the empty answer is about that place — saying
  // "the warehouse" answered for the whole organization instead.
  const selectedLocation = useLocationsById([locationId]).byId.get(locationId);

  const download = async (kind: "xlsx" | "pdf") => {
    try {
      toast.loading(t("common:actions.exporting"), { id: "as-of-export" });
      const blob =
        kind === "xlsx"
          ? await stockAsOfApi.exportXlsx(query)
          : await stockAsOfApi.exportPdf(query);
      downloadBlob(blob, `stock_${day}.${kind}`);
      toast.success(t("common:actions.exportSuccess"), { id: "as-of-export" });
    } catch (caught) {
      toast.error(extractApiError(caught, t("common:actions.exportError")), {
        id: "as-of-export",
      });
    }
  };

  const rows = report?.items ?? [];

  return (
    <div className="space-y-6">
      <ListControlBar
        search={{
          value: filters.searchInput,
          onChange: filters.setSearchInput,
          placeholder: t("inventory:asOf.searchPlaceholder"),
        }}
      />
      <Card className="p-4">
        <div className="flex flex-wrap items-end gap-3">
          <DateInput
            label={t("inventory:asOf.date")}
            value={day}
            onChange={(value) => filters.setFilter("day", value || today)}
            presets={["today", "yesterday", "minus1Month"]}
            wrapperClassName="w-full sm:w-48"
          />
          <LocationCombobox
            label={t("inventory:asOf.location")}
            title={t("inventory:asOf.location")}
            wrapperClassName="w-full sm:w-64"
            value={locationId}
            onChange={(value) => filters.setFilter("location", value)}
            placeholder={t("inventory:asOf.everywhere")}
            searchPlaceholder={t("common:actions.search")}
            emptyMessage={t("common:noResults")}
            clearable
            clearLabel={t("inventory:asOf.everywhere")}
          />
          <div className="flex gap-2 sm:ml-auto">
            <Button
              variant="outline"
              leftIcon={<FileDown size={16} />}
              onClick={() => void download("xlsx")}
              disabled={!report}
            >
              {t("common:actions.export")}
            </Button>
            <Button
              variant="outline"
              leftIcon={<Printer size={16} />}
              onClick={() => void download("pdf")}
              disabled={!report}
            >
              {t("inventory:asOf.print")}
            </Button>
          </div>
        </div>
      </Card>

      {isLoading ? (
        <LoadingSpinner />
      ) : isError && !isServerRefusal(error) ? (
        // The server failing is not an answer about the date: say so, and
        // let the reader ask again.
        <QueryError onRetry={() => void refetch()} />
      ) : isError ? (
        // The refusal is the answer: it names the day the ledger starts and
        // says that nothing before it is known -- not zero.
        <Card className="p-4">
          <div className="flex items-start gap-2 text-on-secondary" role="note">
            <Info size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
            <p className="text-sm">
              {extractApiError(error, t("inventory:asOf.cannotAnswer"))}
            </p>
          </div>
        </Card>
      ) : rows.length === 0 || !report ? (
        <EmptyState
          icon={Boxes}
          title={t("inventory:asOf.empty.title")}
          description={
            filters.search.trim()
              ? t("inventory:asOf.empty.descriptionSearch", {
                  search: filters.search.trim(),
                })
              : selectedLocation
                ? t("inventory:asOf.empty.descriptionAt", {
                    location: selectedLocation.name,
                  })
                : t("inventory:asOf.empty.description")
          }
        />
      ) : (
        <>
          <StockAsOfResult
            report={report}
            day={day}
            showInventoryValue={showInventoryValue}
            money={money}
            t={t}
          />
          <Pagination
            skip={offset}
            limit={limit}
            total={report.total}
            onPrev={() => setOffset(Math.max(0, offset - limit))}
            onNext={() => setOffset(offset + limit)}
            onPageChange={(page) => setOffset((page - 1) * limit)}
            onLimitChange={(next) => {
              setLimit(next);
              setOffset(0);
            }}
          />
        </>
      )}
    </div>
  );
}
