import { csvCell, downloadCsv } from "@/lib/csv";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toAmount } from "@/utils/formatters";
import { Download } from "lucide-react";
import LoadingSpinner from "@/components/LoadingSpinner";
import { RecordNotFound } from "@/components/ui/RecordNotFound";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { QueryError } from "@/components/ui/QueryResult";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { isNotFoundError } from "@/lib/errors";
import { cn } from "@/lib/utils";
import { makeTDynamic } from "@/lib/i18nHelpers";
import { useStockTakeReport } from "../hooks/useStockTakes";
import StockTakeClosedLocations from "../components/StockTakeClosedLocations";
import StockTakePostingNote from "../components/StockTakePostingNote";
import type { StockTakeItem } from "../types/stock-takes";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import type { TranslateFn } from "@/types/i18n";

function sortByAbsDifference(items: StockTakeItem[]): StockTakeItem[] {
  return [...items].sort(
    (a, b) =>
      Math.abs(toAmount(b.difference) ?? 0) -
      Math.abs(toAmount(a.difference) ?? 0),
  );
}

/** Every quantity on this page is an amount *of something* — the same unit
 * the counting card showed when the number was typed, written the way the
 * reader's language writes numbers. */
function withUnit(
  t: TranslateFn,
  quantity: number | string | null | undefined,
  unit: string | null,
  rounding?: string | null,
): string {
  if (quantity == null) return "—";
  return formatQuantityLocalized(t, quantity, unit, rounding) || "—";
}

export default function StockTakeReportPage() {
  const { t } = useTranslation(["stock_takes", "common"]);
  const tDyn = makeTDynamic(t);
  const { id } = useParams<{ id: string }>();
  const { setHeader } = useModulePageHeader();
  const {
    data: report,
    isLoading,
    isError,
    error,
    refetch,
  } = useStockTakeReport(id);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    if (!report) {
      // Still a way back. An empty header left this screen with no title, no
      // arrow and, when the request failed, nothing at all to press.
      setHeader({ backTo: "/inventory/stock-takes" });
      return;
    }
    setHeader({
      title: report.stock_take_name,
      subtitle: report.location_name || undefined,
      backTo: "/inventory/stock-takes",
    });
  }, [report, setHeader]);

  const discrepancies = useMemo(
    () =>
      sortByAbsDifference([
        // Both kinds of difference belong in the default view: the rows that
        // must be explained, and the rows the tolerance accepted without an
        // explanation. The second kind used to vanish here — reported as a
        // perfect match while its correction sat in the ledger.
        ...(report?.discrepancy_items ?? []),
        ...(report?.tolerated_items ?? []),
        // And the rows nobody counted. They match nothing — they were never
        // looked at — so leaving them out of this view let an empty list
        // claim "every item matched" beside a "Not counted" card.
        ...(report?.all_items ?? []).filter(
          (item) => item.counted_quantity == null,
        ),
      ]),
    [report],
  );
  const visibleItems = showAll
    ? sortByAbsDifference(report?.all_items ?? [])
    : discrepancies;

  const durationMinutes =
    report?.started_at && report.completed_at
      ? Math.max(
          0,
          Math.round(
            (new Date(report.completed_at).getTime() -
              new Date(report.started_at).getTime()) /
              60000,
          ),
        )
      : null;

  const handleExport = () => {
    if (!report) return;
    // The file lands in a binder as counting evidence, so every row names
    // its unit and the table carries the count's day, storage and starter —
    // the same facts the movements export attaches to each of its rows.
    const localMoment = (iso: string | null | undefined) =>
      iso ? new Date(iso).toLocaleString() : "";
    const headers = [
      t("report.name"),
      t("item.expected"),
      t("item.counted"),
      t("report.unit"),
      t("report.difference"),
      t("report.location"),
      t("report.reason"),
      t("report.notes"),
      t("report.storage"),
      t("report.startedAt"),
      t("report.completedAt"),
      t("report.startedBy"),
    ];
    const rows = sortByAbsDifference(report.all_items).map((item) =>
      [
        csvCell(item.item_name),
        item.system_quantity ?? "",
        item.counted_quantity ?? "",
        csvCell(item.uom_symbol ?? ""),
        item.difference ?? "",
        csvCell(item.shelf_location ?? ""),
        csvCell(
          item.discrepancy_reason_code
            ? tDyn(`reasons.discrepancy.codes.${item.discrepancy_reason_code}`)
            : "",
        ),
        csvCell(item.notes ?? ""),
        csvCell(report.location_name ?? ""),
        csvCell(localMoment(report.started_at)),
        csvCell(localMoment(report.completed_at)),
        csvCell(report.started_by_name ?? ""),
      ].join(","),
    );
    const csv = [headers.map(csvCell).join(","), ...rows].join("\n");
    downloadCsv(
      csv,
      `${report.stock_take_name.replace(/[^\w-]+/g, "_")}-report.csv`,
    );
  };

  if (isLoading) {
    return <LoadingSpinner />;
  }

  if (isError && !isNotFoundError(error)) {
    return <QueryError onRetry={refetch} />;
  }

  // This one had no way onwards at all — a sentence in the middle of an
  // empty page, on a route reached from a link somebody else sent.
  if (!report) {
    return (
      <RecordNotFound
        title={t("notFound")}
        backTo="/inventory/stock-takes"
        backLabel={t("common:actions.back")}
      />
    );
  }

  const summaryCards = [
    {
      key: "perfectMatches",
      value: report.perfect_matches,
      tone: "text-accent-600",
    },
    {
      key: "toleratedDifferences",
      value: report.tolerated_differences,
      tone: "text-on",
    },
    { key: "overstock", value: report.overstock, tone: "text-on-primary" },
    { key: "understock", value: report.understock, tone: "text-on-warning" },
    { key: "notCounted", value: report.not_counted, tone: "text-on-muted" },
  ] as const;

  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {summaryCards.map((card) => (
          <Card key={card.key} className="p-4 flex flex-col gap-1">
            <p className="text-[10px] font-medium text-on-muted uppercase tracking-wide">
              {tDyn(`report.${card.key}`)}
            </p>
            <p className={cn("text-2xl font-semibold", card.tone)}>
              {card.value}
            </p>
          </Card>
        ))}
        <Card className="p-4 flex flex-col gap-1">
          <p className="text-[10px] font-medium text-on-muted uppercase tracking-wide">
            {t("report.duration")}
          </p>
          <p className="text-2xl font-semibold text-on">
            {durationMinutes !== null
              ? t("report.durationValue", { minutes: durationMinutes })
              : "—"}
          </p>
        </Card>
      </div>

      <StockTakePostingNote report={report} />

      <StockTakeClosedLocations closedLocations={report.closed_locations} />

      {/* Toggle + export */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setShowAll((prev) => !prev)}
        >
          {showAll ? t("report.showDifferencesOnly") : t("report.showAll")}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          leftIcon={<Download size={16} />}
          onClick={handleExport}
        >
          {t("report.exportCsv")}
        </Button>
      </div>

      {/* Items */}
      {visibleItems.length === 0 ? (
        <p className="text-sm text-on-muted py-8 text-center">
          {/* A take with no lines holds nothing that matched, tolerance or
              not. "Every item matched" is a claim about lines that exist. */}
          {report.all_items.length === 0
            ? t("report.empty")
            : t("report.noDiscrepancies")}
        </p>
      ) : (
        <div className="space-y-2">
          {visibleItems.map((item) => (
            <Card
              // A unit counted away from its record's location is one line
              // reported twice: the shortage where expected, the surplus
              // where found.
              key={`${item.id}:${item.location_id ?? ""}`}
              className="p-3 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4"
            >
              <div className="flex-1 min-w-0">
                <p className="font-medium text-on truncate">{item.item_name}</p>
                {item.shelf_location && (
                  <p className="text-xs text-on-muted">
                    {t("report.location")}: {item.shelf_location}
                  </p>
                )}
                {/* The count found the difference; this is the only place
                    that says what made it. Without it the report answers
                    "how much" and never "why", which is the question asked
                    of it. */}
                {/* Which rows were looked at twice, and whether the two
                    looks agreed. A recount that confirms the first number is
                    the strongest thing a stock take can say; one that does
                    not is worth knowing before anybody trusts the figure. */}
                {(item.counts ?? []).length > 1 && (
                  <p className="text-xs text-on-secondary">
                    {(() => {
                      const passes = item.counts ?? [];
                      const first = passes[passes.length - 2].quantity;
                      const second = passes[passes.length - 1].quantity;
                      return t(
                        first === second
                          ? "report.countedTwiceAgreed"
                          : "report.countedTwiceDisagreed",
                        { first, second },
                      );
                    })()}
                  </p>
                )}
                {item.discrepancy_reason_code && (
                  <p className="text-xs text-on-secondary">
                    {tDyn(
                      `reasons.discrepancy.codes.${item.discrepancy_reason_code}`,
                    )}
                    {item.discrepancy_reason
                      ? ` — ${item.discrepancy_reason}`
                      : ""}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-3 text-sm shrink-0">
                <span className="text-on-secondary">
                  {t("item.expected")}:{" "}
                  <strong>
                    {withUnit(
                      t,
                      item.system_quantity,
                      item.uom_symbol?.trim() || null,
                      item.uom_rounding,
                    )}
                  </strong>
                </span>
                <span className="text-on-secondary">
                  {t("item.counted")}:{" "}
                  <strong>
                    {withUnit(
                      t,
                      item.counted_quantity,
                      item.uom_symbol?.trim() || null,
                      item.uom_rounding,
                    )}
                  </strong>
                </span>
                {(() => {
                  const difference = toAmount(item.difference);
                  if (difference == null || difference === 0) return null;
                  const unit = item.uom_symbol?.trim() || null;
                  return (
                    <Badge
                      variant={
                        // A difference the tolerance accepted is not a
                        // discrepancy — it asked for no explanation and got
                        // none. Naming it here is what keeps the report
                        // honest about what "perfect" would have hidden.
                        item.is_discrepancy === 0
                          ? "info"
                          : difference > 0
                            ? "danger"
                            : "warning"
                      }
                      className="text-[10px]"
                    >
                      {item.is_discrepancy === 0 && t("report.withinTolerance")}
                      {difference > 0 ? "+" : ""}
                      {withUnit(t, difference, unit, item.uom_rounding)}
                    </Badge>
                  );
                })()}
                {/* Counted: — is easy to read past; this says what the dash
                    is, in the same words as the summary card. */}
                {item.counted_quantity == null && (
                  <Badge variant="outline" className="text-[10px]">
                    {t("report.itemNotCounted")}
                  </Badge>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
