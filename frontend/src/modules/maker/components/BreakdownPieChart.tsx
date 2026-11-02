import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { Card } from "@/components/ui/Card";
import { formatNumberLocale, formatQuantityValue } from "@/utils/formatters";
import type { CostBreakdownResponse } from "@/modules/maker/types/maker";
import { EmptyState } from "@/components/ui/EmptyState";

interface BreakdownPieChartProps {
  breakdown: CostBreakdownResponse;
}

const PIE_COLORS = [
  "#0d9488", // teal-600
  "#f59e0b", // amber-500
  "#6366f1", // indigo-500
  "#ef4444", // red-500
  "#8b5cf6", // violet-500
  "#10b981", // emerald-500
  "#f97316", // orange-500
  "#3b82f6", // blue-500
];

function shortTemplateId(id: string): string {
  return id.slice(0, 8);
}

function formatPct(pct: string | null): string {
  if (!pct) return "—";
  // The share is not a measured quantity, but it is still a number the
  // reader reads: write it the way the shared formatter writes quantities,
  // not the way the wire sent it ("33.333333%").
  return `${formatQuantityValue(pct)}%`;
}

/**
 * Pie chart visualisation of a CostBreakdownResponse.
 *
 * Skips entries with `null` cost (no layer-average rate) — those are
 * already surfaced separately in `missing_cost_lines`.
 */
export function BreakdownPieChart({ breakdown }: BreakdownPieChartProps) {
  const { t } = useTranslation("maker");

  const slices = useMemo(() => {
    return breakdown.entries
      .filter((e) => e.cost !== null)
      .map((e, idx) => ({
        name: e.child_template_name ?? shortTemplateId(e.child_template_id),
        fullId: e.child_template_id,
        value: Number(e.cost ?? "0"),
        percentage: e.percentage_of_total,
        unit: e.unit,
        qty: e.consumed_qty,
        color: PIE_COLORS[idx % PIE_COLORS.length] as string,
      }))
      .sort((a, b) => b.value - a.value);
  }, [breakdown]);

  if (slices.length === 0) {
    return <EmptyState variant="compact" title={t("preview.chart.empty")} />;
  }

  return (
    <Card className="p-4 space-y-3">
      <h3 className="text-xs uppercase tracking-widest text-on-muted font-medium px-1">
        {t("preview.chart.title")}
      </h3>
      <div className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={slices}
              dataKey="value"
              nameKey="name"
              innerRadius={45}
              outerRadius={75}
              paddingAngle={2}
              stroke="none"
            >
              {slices.map((slice) => (
                <Cell key={slice.fullId} fill={slice.color} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                background: "var(--color-surface-card)",
                border: "1px solid var(--color-border)",
                borderRadius: 8,
                fontSize: 12,
              }}
              formatter={(_value, _name, item) => {
                const payload = item.payload as (typeof slices)[number];
                return [
                  `${formatNumberLocale(payload.value, 2)} (${formatPct(payload.percentage)})`,
                  payload.name,
                ];
              }}
            />
            <Legend
              verticalAlign="bottom"
              height={36}
              iconSize={8}
              wrapperStyle={{ fontSize: 11 }}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
