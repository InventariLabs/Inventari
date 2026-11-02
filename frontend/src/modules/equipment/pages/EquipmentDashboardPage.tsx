import { useEffect, useMemo } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Plus } from "lucide-react";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useHasRole } from "@/module-sdk";
import { AttentionCard } from "@/components/ui/AttentionCard";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import { EquipmentDashboardWidget } from "@/modules/equipment/components/EquipmentDashboardWidget";
import { FleetValuationWidget } from "@/modules/equipment/components/FleetValuationWidget";
import { FleetCompositionCard } from "@/modules/equipment/components/dashboard/FleetCompositionCard";
import { RecentAssignments } from "@/modules/equipment/components/dashboard/RecentAssignments";
import { toFleetAttention } from "@/modules/equipment/components/dashboard/fleetAttention";
import {
  fleetSize,
  getEquipmentMeta,
} from "@/modules/equipment/components/assetUtils";
import {
  useEquipmentDashboard,
  useOverdueAssignments,
} from "@/modules/equipment/hooks/useEquipment";
import {
  bucketFleet,
  useFleetAssets,
} from "@/modules/equipment/hooks/useFleetComposition";
import { useFleetValuation } from "@/modules/equipment/hooks/useValuation";

/** Overdue returns fetched for the card. */
const OVERDUE_LIMIT = 20;

/**
 * EquipmentDashboardPage — the overview at /equipment.
 *
 * The same skeleton as the inventory overview: what needs attention (or one
 * line saying nothing does), the fleet by category, then the latest
 * check-outs beside the fleet's valuation. The list of assignments with its
 * search lives on the asset list, filtered to what is checked out.
 */
export default function EquipmentDashboardPage() {
  const { t } = useTranslation("equipment");
  useAddAssetHeader();

  const dashboard = useEquipmentDashboard();
  const overdue = useOverdueAssignments(OVERDUE_LIMIT);
  const fleet = useFleetAssets();
  // The widget's own query, read here only for the layout: with nothing to
  // value it draws nothing, and the check-outs take the full width.
  // The fleet's purchase prices and book value are the organization's
  // finances, not what a member needs to hand out or return a laptop: only
  // administrators and managers see the roll-up (a member still sees the
  // value of one asset on its own page).
  const canSeeValuation = useHasRole(["admin", "manager"]);
  const valuation = useFleetValuation(canSeeValuation).data;
  const hasValuation =
    canSeeValuation &&
    valuation != null &&
    (valuation.asset_count > 0 || valuation.excluded_count > 0);

  const warrantyEnding = dashboard.data?.warranty_alerts;
  const rows = useMemo(
    () =>
      fleet.data
        ? bucketFleet(
            fleet.data,
            new Set((warrantyEnding ?? []).map((w) => w.item_id)),
          )
        : undefined,
    [fleet.data, warrantyEnding],
  );

  // A retired asset nobody holds is out of the fleet: its warranty running
  // out is not something to act on, and an old fleet has many of them.
  const idle = (status: string) =>
    (fleet.data ?? []).filter(
      (a) => a.holder_name == null && getEquipmentMeta(a).status === status,
    );
  const retired = new Set(idle("RETIRED").map((a) => a.id));
  const inFleet = (w: { item_id: string }) => !retired.has(w.item_id);
  const attention = toFleetAttention(
    {
      overdue: overdue.data?.items ?? [],
      warrantyEnding: (warrantyEnding ?? []).filter(inFleet),
      warrantyExpired: (dashboard.data?.expired_warranty_alerts ?? []).filter(
        inFleet,
      ),
      inService: idle("MAINTENANCE"),
    },
    t,
  );

  // A count that did not arrive is left out of the sentence, never read as
  // zero. Retired assets are out of the fleet, as they are out of the bars.
  const d = dashboard.data;
  const summary = d
    ? [
        t("dashboard.summary.assets", { count: fleetSize(d) }),
        t("dashboard.summary.issued", { count: d.active_assignments }),
      ].join(" · ")
    : undefined;

  const failed = dashboard.isError || overdue.isError || fleet.isError;

  return (
    <div className="space-y-6">
      <AttentionCard
        items={attention}
        attentionLabel={t("dashboard.attention.heading", {
          count: attention.length,
        })}
        summary={summary}
        linkLabel={t("dashboard.view_all")}
        linkHref="/equipment/assets"
        // Its link opens every asset, not the ones counted here, so the rows
        // past the first few have nowhere else to be read.
        showAllLabel={t("common:dashboard.attention.showAll", {
          count: attention.length,
        })}
        quiet={{
          okText: t("dashboard.attention.quiet"),
          linkLabel: t("dashboard.fleet.link"),
          linkHref: "/equipment/assets",
        }}
        loading={dashboard.isLoading || overdue.isLoading || fleet.isLoading}
        unavailable={
          failed
            ? {
                message: t("dashboard.attention.unavailable"),
                retryLabel: t("common:actions.retry"),
                partialLabel: t("common:dashboard.attention.partial"),
                onRetry: () => {
                  if (dashboard.isError) void dashboard.refetch();
                  if (overdue.isError) void overdue.refetch();
                  if (fleet.isError) void fleet.refetch();
                },
              }
            : undefined
        }
      />

      {/* The fleet's totals, one strip of four numbers: they used to sit on
          the inventory overview, where a stock reader met warranties. */}
      <EquipmentDashboardWidget />

      <FleetCompositionCard
        rows={rows}
        isLoading={fleet.isLoading}
        error={fleet.error}
        onRetry={() => void fleet.refetch()}
      />

      <div
        className={cn(
          // A bare `auto` track (no grid-cols below lg) sizes itself to the
          // valuation table's min-content and pushes both cards past a phone
          // screen, where the root's overflow-x-hidden clips them out of
          // reach. A zero-min track is what lets the cards shrink instead.
          "grid grid-cols-[minmax(0,1fr)] gap-6",
          hasValuation && "lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]",
        )}
      >
        <RecentAssignments />
        {canSeeValuation && <FleetValuationWidget />}
      </div>
    </div>
  );
}

/** "Add asset" in the module header, for those who may write. */
function useAddAssetHeader() {
  const { t } = useTranslation("equipment");
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("equipment");
  useEffect(() => {
    setHeader({
      actions: canWrite ? (
        <div className="ml-auto">
          {/* inline-flex on the anchor itself: an inline <a> around a 44px
              button reports the line box — 21px — to anything that measures
              it, while the button it wraps is already at the floor. */}
          <Link to="/equipment/add" className="inline-flex">
            <Button leftIcon={<Plus size={16} />}>
              {t("dashboard.add_asset")}
            </Button>
          </Link>
        </div>
      ) : undefined,
    });
  }, [t, setHeader, canWrite]);
}
