import { useTranslation } from "react-i18next";
import { AlertTriangle, Wrench } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { fleetSize } from "@/modules/equipment/components/assetUtils";
import { useEquipmentDashboard } from "@/modules/equipment/hooks/useEquipment";

/**
 * The fleet's totals on the equipment overview: asset counts, plus the
 * warranty and maintenance lines that need a look.
 */
export function EquipmentDashboardWidget() {
  const { t } = useTranslation("equipment");
  const { data, isLoading } = useEquipmentDashboard();

  if (isLoading) {
    return (
      <Card className="p-4 animate-pulse">
        <div className="mb-3 flex items-center gap-2">
          <div className="h-4 w-4 rounded bg-surface-inset" />
          <div className="h-4 w-24 rounded bg-surface-inset" />
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="rounded-lg bg-surface-raised p-2 text-center"
            >
              <div className="mx-auto h-6 w-8 rounded bg-surface-inset" />
              <div className="mx-auto mt-1 h-2.5 w-14 rounded bg-surface-inset" />
            </div>
          ))}
        </div>
      </Card>
    );
  }

  if (!data) return null;

  const hasAlerts = data.warranty_alerts.length > 0;

  return (
    <Card className="p-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile label={t("dashboard.total_assets")} value={fleetSize(data)} />
        <StatTile
          label={t("dashboard.active_assignments")}
          value={data.active_assignments}
          accent="info"
        />
        <StatTile
          label={t("dashboard.in_maintenance")}
          value={data.in_maintenance}
          accent="warning"
        />
        <StatTile
          label={t("dashboard.retired")}
          value={data.retired}
          accent="secondary"
        />
      </div>

      {hasAlerts && (
        <div className="mt-3 flex items-center gap-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-700 dark:bg-surface-raised dark:border-amber-800/40 dark:text-amber-400">
          <AlertTriangle size={14} />
          <span>
            {t("dashboard.warrantyAlertsCount", {
              count: data.warranty_alerts.length,
            })}
          </span>
        </div>
      )}

      {data.in_maintenance > 0 && (
        <div className="mt-2 flex items-center gap-2 rounded-lg bg-blue-50 border border-blue-200 px-3 py-2 text-xs text-on-info">
          <Wrench size={14} />
          <span>
            {t("dashboard.fleet.in_service", { count: data.in_maintenance })}
          </span>
        </div>
      )}
    </Card>
  );
}

interface StatTileProps {
  label: string;
  value: number;
  accent?: "info" | "warning" | "secondary";
}

function StatTile({ label, value, accent }: StatTileProps) {
  const accentClass =
    accent === "info"
      ? "text-on-info"
      : accent === "warning"
        ? "text-on-warning"
        : accent === "secondary"
          ? "text-on-secondary"
          : "text-on";

  return (
    <div className="rounded-lg bg-surface-raised border border-border p-2 text-center">
      <div className={`text-xl font-semibold ${accentClass}`}>{value}</div>
      <div className="mt-0.5 text-[10px] text-on-secondary">{label}</div>
    </div>
  );
}
