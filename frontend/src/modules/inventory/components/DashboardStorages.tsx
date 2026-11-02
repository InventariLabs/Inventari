import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import type { StorageLocationNode } from "@/types";
import { Card, CardHeader, CardTitle } from "@/components/ui/Card";
import { CardLink } from "@/components/ui/CardLink";
import {
  CompositionLegend,
  CompositionRow,
  type CompositionSegment,
} from "@/components/ui/CompositionBar";
import { QueryError } from "@/components/ui/QueryResult";
import { StorageRequired } from "@/modules/shared/components/StorageRequired";
import { useStorageTypes } from "@/modules/shared/hooks/useStorages";
import type { StorageComposition } from "@/modules/inventory/hooks/useDashboardAttention";

/** Zones on the card; the storages list holds the rest. */
const MAX_ZONES = 6;

interface DashboardStoragesProps {
  storageZones: readonly StorageLocationNode[];
  composition: readonly StorageComposition[];
  /** The tree never arrived: say so rather than offer "add your first storage". */
  loadFailed?: boolean;
  onRetry?: () => void;
}

type Segments = StorageComposition["segments"];

function barSegments(s: Segments): CompositionSegment[] {
  return [
    { key: "bad", count: s.bad, tone: "danger" },
    { key: "warn", count: s.warn, tone: "warning" },
    { key: "low", count: s.low, tone: "info" },
    { key: "ok", count: s.ok, tone: "ok" },
  ];
}

/** The bar in words: "52 records: 1 expiring, 2 low stock". */
function barLabel(t: TFunction, count: number, s: Segments) {
  const parts = [
    s.bad > 0 && t("common:dashboard.composition.expired", { count: s.bad }),
    s.warn > 0 && t("common:dashboard.composition.expiring", { count: s.warn }),
    s.low > 0 && t("common:dashboard.composition.low", { count: s.low }),
  ].filter(Boolean);
  const head = t("common:dashboard.recordCount", { count });
  return parts.length > 0 ? `${head}: ${parts.join(", ")}` : head;
}

export default function DashboardStorages({
  storageZones,
  composition,
  loadFailed = false,
  onRetry,
}: DashboardStoragesProps) {
  const { t } = useTranslation("common");
  // The types only supply icons; a list that failed leaves the generic one.
  const { data: storageTypes } = useStorageTypes();
  const iconOf = new Map(storageTypes?.map((type) => [type.id, type.icon]));
  const byZone = new Map(composition.map((c) => [c.zoneId, c]));

  const zones = storageZones.slice(0, MAX_ZONES);
  const rows = zones.map((zone) => {
    const c = byZone.get(zone.id);
    const count = c?.count ?? zone.subtree_items_count;
    const segments = c?.segments ?? { bad: 0, warn: 0, low: 0, ok: count };
    return { zone, count, segments };
  });
  const maxCount = Math.max(0, ...rows.map((r) => r.count));

  return (
    <Card className="p-4 sm:p-5">
      <CardHeader className="flex-row items-baseline justify-between space-y-0 pb-2">
        <CardTitle>{t("common:dashboard.myStorages")}</CardTitle>
        <CardLink to="/inventory/locations" arrow className="text-xs">
          {t("common:dashboard.viewAll")}
        </CardLink>
      </CardHeader>

      {loadFailed ? (
        <QueryError onRetry={onRetry} />
      ) : rows.length === 0 ? (
        // The call to action used to land on the storage list, where the
        // reader had to find "add" a second time.
        <StorageRequired />
      ) : (
        <>
          <ul className="divide-y divide-border">
            {rows.map(({ zone, count, segments }) => (
              <CompositionRow
                key={zone.id}
                icon={
                  (zone.location_type_id &&
                    iconOf.get(zone.location_type_id)) ||
                  "Package"
                }
                name={zone.name}
                meta={zoneMeta(t, zone, segments)}
                count={count}
                maxCount={maxCount}
                segments={barSegments(segments)}
                ariaLabel={barLabel(t, count, segments)}
              />
            ))}
          </ul>
          <CompositionLegend
            className="pt-2"
            ariaLabel={t("common:dashboard.legend.label")}
            entries={[
              { key: "ok", tone: "ok", label: t("common:dashboard.legend.ok") },
              {
                key: "warn",
                tone: "warning",
                label: t("common:dashboard.legend.warn"),
              },
              {
                key: "bad",
                tone: "danger",
                label: t("common:dashboard.legend.bad"),
              },
              {
                key: "low",
                tone: "info",
                label: t("common:dashboard.legend.low"),
              },
            ]}
            bars={rows.map((r) => barSegments(r.segments))}
          />
        </>
      )}
    </Card>
  );
}

// Every count through t() with `count`: one language's plural rule written
// into a component is wrong in every language with more than two forms.
function zoneMeta(t: TFunction, zone: StorageLocationNode, s: Segments) {
  // The expired come first: the line used to name only what was expiring,
  // so "2 expiring" sat beside a red bar for the cheese already past its
  // date — the worst thing in the place was the one the words left out.
  return [
    zone.children_count > 0 &&
      t("common:dashboard.locationCount", { count: zone.children_count }),
    s.bad > 0 && t("common:dashboard.composition.expired", { count: s.bad }),
    s.warn > 0 && t("common:dashboard.composition.expiring", { count: s.warn }),
  ]
    .filter(Boolean)
    .join(" · ");
}
