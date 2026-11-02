import { useTranslation } from "react-i18next";
import { Scale } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { formatDateTime, formatQuantityValue } from "@/utils/formatters";
import type { Reconciliation } from "@/modules/stats/types/analytics";

interface Pair {
  key: string;
  name: string;
  meaning: string;
  count: number | null | undefined;
  total: string | null | undefined;
}

/**
 * What the previous scheduled pass measured for one of the pairs. A standing
 * gap in either is what the past left (ADR-022), so each is watched against
 * its predecessor rather than read on its own.
 */
interface PairPrevious {
  measuredAt: string;
  count: number;
  /** The wire's exact figure, printed the way the cells beside it print. */
  totalDisplay: string;
  /** Numeric, for the trend comparison only. */
  total: number;
}

/**
 * How a watched figure moved since the previous pass. The screen owes the
 * reader this distinction — "the gap is here by design" is an instruction
 * that only works when a figure that stopped standing is visible as one.
 */
type Trend = "grown" | "shrunk" | "standing";

const TREND_KEYS: Record<Trend, string> = {
  grown: "stats:reconciliation.grown",
  shrunk: "stats:reconciliation.shrunk",
  standing: "stats:reconciliation.standing",
};

const TREND_VARIANTS: Record<Trend, "warning" | "info" | "secondary"> = {
  grown: "warning",
  shrunk: "info",
  standing: "secondary",
};

const signOf = (delta: number): number => (delta > 0 ? 1 : delta < 0 ? -1 : 0);

/**
 * The two pair comparisons behind the drift warning admins receive.
 *
 * The warning names their counts; until this panel existed it pointed at a
 * screen that showed none of them — and at an address that did not resolve.
 * The pairs are one table because they are one question asked twice, and a
 * reader comparing them needs the columns to line up. The two pairs that
 * compared the records with the quant table ended with it (ADR-022), and so
 * did the verdict badge and the per-location breakdown that were theirs.
 */
export default function StockReconciliationPanel({
  data,
}: {
  data: Reconciliation;
}) {
  const { t } = useTranslation(["stats", "common"]);

  // The keys are written out, not built from `pair.key`: a template literal
  // makes the catalogue's own gate blind to them, and the price of that is an
  // allowlist entry saying the consumption is dynamic when it is not.
  const pairs: Pair[] = [
    {
      key: "quantMove",
      name: t("stats:reconciliation.pairs.quantMove.name"),
      meaning: t("stats:reconciliation.pairs.quantMove.meaning"),
      count: data.quant_move_drift_count,
      total: data.quant_move_drift_total,
    },
    {
      key: "layerQuant",
      name: t("stats:reconciliation.pairs.layerQuant.name"),
      meaning: t("stats:reconciliation.pairs.layerQuant.meaning"),
      count: data.layer_quant_drift_count,
      total: data.layer_quant_drift_total,
    },
  ];

  // A figure the server did not send is not a zero. Reads taken before a pair
  // joined the report carry null, and "—" is the honest rendering of that.
  // The rest goes through the quantity formatter: the server sends a Decimal
  // string padded to three places, and printed as it came "12.500" reads as
  // twelve thousand five hundred on a Polish screen.
  const figure = (value: number | string | null | undefined) =>
    value == null ? "—" : formatQuantityValue(value);

  // The pairs read their predecessor off the stored pass the drift
  // warning compares against — one record, so what the screen calls
  // "previous" is what decided the last warning.
  const previousOf = (pair: Pair): PairPrevious | null => {
    const stored = data.previous;
    if (!stored) return null;
    if (pair.key === "quantMove") {
      return {
        measuredAt: stored.measured_at,
        count: stored.quant_move_drift_count,
        totalDisplay: String(stored.quant_move_drift_total),
        total: Number(stored.quant_move_drift_total),
      };
    }
    if (pair.key === "layerQuant") {
      return {
        measuredAt: stored.measured_at,
        count: stored.layer_quant_drift_count,
        totalDisplay: String(stored.layer_quant_drift_total),
        total: Number(stored.layer_quant_drift_total),
      };
    }
    return null;
  };

  const trendOf = (pair: Pair): Trend | null => {
    const previous = previousOf(pair);
    if (!previous || pair.count == null) return null;
    const countTrend = signOf(Number(pair.count) - previous.count);
    const totalTrend = signOf(Number(pair.total ?? 0) - previous.total);
    if (countTrend > 0 || totalTrend > 0) return "grown";
    if (countTrend < 0 || totalTrend < 0) return "shrunk";
    return "standing";
  };

  return (
    <div className="space-y-6">
      <Card className="p-5">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 shrink-0 bg-primary-50 text-primary-600 rounded-xl flex items-center justify-center">
            <Scale size={20} />
          </div>
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-on">
              {t("stats:reconciliation.title")}
            </h2>
            <p className="text-sm text-on-secondary mt-1">
              {t("stats:reconciliation.subtitle", {
                count: data.items_scanned,
              })}
            </p>
          </div>
        </div>
      </Card>

      <Card className="p-0 overflow-hidden">
        <div className="relative overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">
              {t("stats:reconciliation.tableCaption")}
            </caption>
            <thead>
              <tr className="border-b border-border">
                <th
                  scope="col"
                  className="text-left px-4 py-2.5 text-[10px] font-medium text-on-muted uppercase tracking-widest"
                >
                  {t("stats:reconciliation.columns.pair")}
                </th>
                <th
                  scope="col"
                  className="text-right px-4 py-2.5 text-[10px] font-medium text-on-muted uppercase tracking-widest"
                >
                  {t("stats:reconciliation.columns.count")}
                </th>
                <th
                  scope="col"
                  className="text-right px-4 py-2.5 text-[10px] font-medium text-on-muted uppercase tracking-widest"
                >
                  {t("stats:reconciliation.columns.total")}
                </th>
              </tr>
            </thead>
            <tbody>
              {pairs.map((pair) => (
                <tr key={pair.key} className="border-b border-border/60">
                  <td className="px-4 py-3 align-top">
                    <p className="font-medium text-on">{pair.name}</p>
                    <p className="text-xs text-on-secondary mt-0.5">
                      {pair.meaning}
                    </p>
                    <p className="text-xs text-on-muted mt-1">
                      {t("stats:reconciliation.expectedGap")}
                    </p>
                    {(() => {
                      const previous = previousOf(pair);
                      if (!previous) {
                        return (
                          <p
                            className="text-xs text-on-muted mt-1"
                            data-testid={`previous-${pair.key}-none`}
                          >
                            {t("stats:reconciliation.noPrevious")}
                          </p>
                        );
                      }
                      const trend = trendOf(pair);
                      return (
                        <p
                          className="text-xs text-on-muted mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1"
                          data-testid={`previous-${pair.key}`}
                        >
                          <span>
                            {t("stats:reconciliation.previousLine", {
                              when: formatDateTime(previous.measuredAt),
                              howMany: figure(previous.count),
                              howMuch: figure(previous.totalDisplay),
                            })}
                          </span>
                          {trend && (
                            <Badge variant={TREND_VARIANTS[trend]}>
                              {t(TREND_KEYS[trend])}
                            </Badge>
                          )}
                        </p>
                      );
                    })()}
                  </td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums align-top text-on">
                    {figure(pair.count)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums align-top text-on">
                    {figure(pair.total)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
