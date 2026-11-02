import { Link } from "react-router-dom";
import { Package, BarChart3, AlertTriangle, TrendingDown } from "lucide-react";
import type { AttentionCounts, OverviewStats } from "@/types";
import { TranslateFn } from "@/types/i18n";

type Props = {
  t: TranslateFn;
  overview: OverviewStats;
  /** The expiry shares, from the one count the health card above reads. */
  attentionCounts: AttentionCounts;
  /** The one expiry decision — see `useTracksExpiry` in shared. */
  tracksExpiry?: boolean;
};

/**
 * One overview tile: coloured icon chip, value, caption — wrapped in a link.
 *
 * Four identical copies lived in this file. Local rather than shared with
 * `maker/ProductionOrderStats`: it looks like the same idea but lays out
 * differently (label above the value), so one component would need a layout
 * variant per caller.
 */
function OverviewTile({
  to,
  icon,
  chipClass,
  valueClass,
  value,
  label,
}: {
  to: string;
  icon: React.ReactNode;
  chipClass: string;
  valueClass: string;
  value: number;
  label: string;
}) {
  return (
    <Link to={to}>
      <div className="bg-surface-card border border-border rounded-2xl p-3 flex items-center gap-3 hover:border-border transition-colors">
        <div
          className={`w-9 h-9 ${chipClass} rounded-xl flex items-center justify-center shrink-0`}
        >
          {icon}
        </div>
        <div>
          <p className={`text-xl font-semibold ${valueClass} leading-none`}>
            {value}
          </p>
          <p className="text-[10px] font-medium text-on-muted uppercase tracking-wide mt-0.5">
            {label}
          </p>
        </div>
      </div>
    </Link>
  );
}

export function StatsOverviewCards({
  t,
  overview,
  attentionCounts,
  tracksExpiry,
}: Props) {
  return (
    <div className="grid grid-cols-2 gap-2">
      <OverviewTile
        to="/inventory/items"
        icon={<Package size={18} />}
        chipClass="bg-accent-50 text-accent-600"
        valueClass="text-on"
        value={overview?.total_items || 0}
        label={t("stats:records")}
      />
      <OverviewTile
        to="/inventory/locations"
        icon={<BarChart3 size={18} />}
        chipClass="bg-primary-50 text-primary-700 dark:bg-primary-500/10 dark:text-primary-500"
        valueClass="text-primary-700 dark:text-primary-500"
        value={overview?.total_locations || 0}
        label={t("stats:places")}
      />
      {/* The same decision the health card above reads, from the same count:
          these tiles used to read the overview — a second computation of
          the numbers beside them. And these two used to be unconditional,
          so a workspace the card had just told "you keep no dates"
          answered "0 expiring, 8 expired" one click lower. */}
      {tracksExpiry && (
        <>
          <OverviewTile
            to="/inventory/items?filter=expiring"
            icon={<AlertTriangle size={18} />}
            chipClass="bg-amber-50 text-on-warning dark:bg-amber-500/10"
            valueClass="text-on-warning"
            value={attentionCounts.expiring_soon}
            label={t("stats:expiringSoon")}
          />
          <OverviewTile
            to="/inventory/items?filter=expired"
            icon={<TrendingDown size={18} />}
            chipClass="bg-red-50 text-on-danger dark:bg-red-500/10"
            valueClass="text-on-danger"
            value={attentionCounts.expired}
            label={t("stats:expired")}
          />
        </>
      )}
    </div>
  );
}
