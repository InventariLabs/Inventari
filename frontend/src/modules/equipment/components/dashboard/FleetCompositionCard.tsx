import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Card, CardHeader, CardTitle } from "@/components/ui/Card";
import { CardLink } from "@/components/ui/CardLink";
import {
  CompositionLegend,
  CompositionRow,
  type CompositionSegment,
} from "@/components/ui/CompositionBar";
import { QueryFailure } from "@/components/ui/QueryResult";
import { getCategoryLabel } from "@/modules/equipment/components/assetUtils";
import type {
  FleetCategoryRow,
  FleetSegments,
} from "@/modules/equipment/hooks/useFleetComposition";

/** Categories on the card; the asset list, filtered, holds the rest. */
const MAX_CATEGORIES = 6;

function barSegments(s: FleetSegments): CompositionSegment[] {
  return [
    { key: "issued", count: s.issued, tone: "active" },
    { key: "service", count: s.service, tone: "info" },
    // Beside the rest of the shelf it is part of.
    { key: "warn", count: s.warn, tone: "warning" },
    { key: "ok", count: s.ok, tone: "ok" },
  ];
}

/** Where the row's assets are: "11 checked out · 1 in maintenance". */
function whereabouts(t: TFunction, s: FleetSegments) {
  return [
    s.issued > 0 && t("dashboard.summary.issued", { count: s.issued }),
    s.service > 0 && t("dashboard.fleet.in_service", { count: s.service }),
  ].filter((p): p is string => Boolean(p));
}

/** The bar in words: "13 assets: 11 checked out, 1 available, warranty ending". */
function barLabel(t: TFunction, row: FleetCategoryRow) {
  const head = t("dashboard.summary.assets", { count: row.count });
  const s = row.segments;
  const said = [
    ...whereabouts(t, s),
    ...(s.warn > 0
      ? [t("dashboard.fleet.warranty_ending", { count: s.warn })]
      : []),
  ];
  return said.length > 0 ? `${head}: ${said.join(", ")}` : head;
}

interface FleetCompositionCardProps {
  rows: readonly FleetCategoryRow[] | undefined;
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
}

/** The fleet by category: how big each is and where its assets are. */
export function FleetCompositionCard({
  rows,
  isLoading,
  error,
  onRetry,
}: FleetCompositionCardProps) {
  const { t } = useTranslation("equipment");
  const shown = (rows ?? []).slice(0, MAX_CATEGORIES);
  const maxCount = Math.max(0, ...shown.map((r) => r.count));

  return (
    <Card className="p-4 sm:p-5">
      <CardHeader className="flex-row items-baseline justify-between space-y-0 pb-2">
        <CardTitle>{t("dashboard.fleet.title")}</CardTitle>
        <CardLink to="/equipment/assets" arrow className="text-xs">
          {t("dashboard.fleet.link")}
        </CardLink>
      </CardHeader>

      {error ? (
        <QueryFailure error={error} onRetry={onRetry} />
      ) : isLoading ? (
        <div aria-busy="true" className="space-y-3 py-2.5">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-8 animate-pulse rounded bg-surface-inset"
            />
          ))}
        </div>
      ) : shown.length === 0 ? (
        <p className="py-2.5 text-sm text-on-secondary">
          {t("dashboard.fleet.empty")}
        </p>
      ) : (
        <>
          <ul className="divide-y divide-border">
            {shown.map((row) => (
              <CompositionRow
                key={row.key}
                icon={row.category?.icon || "Package"}
                name={
                  row.category
                    ? getCategoryLabel(t, row.category)
                    : t("dashboard.fleet.uncategorised")
                }
                href={
                  row.category
                    ? `/equipment/assets?category=${row.category.id}&hide_retired=1`
                    : undefined
                }
                meta={whereabouts(t, row.segments).join(" · ") || undefined}
                count={row.count}
                maxCount={maxCount}
                segments={barSegments(row.segments)}
                ariaLabel={barLabel(t, row)}
              />
            ))}
          </ul>
          <CompositionLegend
            className="pt-2"
            ariaLabel={t("dashboard.legend.label")}
            entries={[
              { key: "ok", tone: "ok", label: t("dashboard.legend.ok") },
              {
                key: "issued",
                tone: "active",
                label: t("dashboard.legend.issued"),
              },
              {
                key: "warn",
                tone: "warning",
                label: t("dashboard.legend.warn"),
              },
              {
                key: "service",
                tone: "info",
                label: t("dashboard.legend.service"),
              },
            ]}
            bars={shown.map((r) => barSegments(r.segments))}
          />
        </>
      )}
    </Card>
  );
}
