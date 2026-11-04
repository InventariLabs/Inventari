import type { HTMLAttributes } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { FrontendModule } from "@/lib/moduleRegistry";
import { resolveModuleTarget } from "@/lib/moduleRegistry";
import { makeTDynamic } from "@/lib/i18nHelpers";
import { cn } from "@/lib/utils";

interface StatusBadge {
  count: number;
  label: string;
  failed?: boolean;
}

interface ModuleTileProps extends HTMLAttributes<HTMLAnchorElement> {
  module: FrontendModule;
  statusBadge?: StatusBadge | null;
  /**
   * The tile can be dragged to reorder it. The caller spreads `useSortable`'s
   * attributes and listeners on this component, and they land on the link —
   * the tile's one interactive element and the node the reader lands on. On
   * the `<li>` around it they made a `role="button"` holding a link, two tab
   * stops per tile, in a list that may hold only list items. All the flag
   * itself adds is the cursor: the whole card is the handle.
   */
  sortable?: boolean;
}

/**
 * ModuleTile — single module entry in the Launcher.
 *
 * Responsive dual layout:
 *   • Mobile (< md): compact vertical tile (app-drawer style).
 *   • Desktop (≥ md): square card — icon on top, name, description, status badge at bottom.
 */
export function ModuleTile({
  module,
  statusBadge,
  sortable,
  ...handle
}: ModuleTileProps) {
  const { t } = useTranslation("common");
  const tDyn = makeTDynamic(t);

  const cfg = module.launcher!;
  const dest = resolveModuleTarget(module);
  const Icon = cfg.icon;
  const displayName = tDyn(cfg.displayName);
  const description = cfg.description ? tDyn(cfg.description) : undefined;
  const badgeFailed = statusBadge?.failed === true;
  const failedNote = t("launcher.badgeUnavailable");
  // The hover title. The link takes its name from its content — the name,
  // the description, the count or the failed note it shows — because an
  // `aria-label` of the name alone left the rest out of what a voice user
  // can call it by (WCAG 2.5.3).
  const badgeLabel = badgeFailed
    ? `${displayName}, ${failedNote}`
    : statusBadge && statusBadge.count > 0
      ? `${displayName}, ${statusBadge.count} ${statusBadge.label}`
      : displayName;

  const hasStatusBadge = statusBadge && statusBadge.count > 0;
  const iconBg = cfg.color ?? "bg-surface-inset";
  const hasColor = !!cfg.color;

  // Shared focus / grab styles
  const baseLinkClasses = cn(
    "relative block rounded-2xl md:rounded-xl",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2",
    sortable && "cursor-grab active:cursor-grabbing",
  );

  return (
    <Link
      to={dest}
      className={baseLinkClasses}
      title={hasStatusBadge ? badgeLabel : undefined}
      {...handle}
    >
      {/* ── Mobile layout (< md) ── */}
      <div
        className={cn(
          "md:hidden flex flex-col items-center gap-1.5 px-1 pt-3 pb-2.5 rounded-2xl",
          "hover:bg-surface-raised active:scale-95 transition-all duration-150",
        )}
      >
        <div className="relative shrink-0">
          <div
            className={cn(
              "w-14 h-14 rounded-[18px] flex items-center justify-center shadow-sm",
              hasColor ? iconBg : "bg-surface-card border border-border",
            )}
          >
            <Icon
              size={26}
              strokeWidth={1.75}
              className={hasColor ? "text-white" : "text-on-muted"}
            />
          </div>
          {hasStatusBadge && (
            <span
              className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full bg-amber-500 text-amber-950 text-[10px] font-medium flex items-center justify-center leading-none"
              aria-hidden="true"
            >
              {statusBadge.count > 99 ? "99+" : statusBadge.count}
            </span>
          )}
        </div>
        <span
          className={cn(
            "text-xs font-medium text-center leading-tight line-clamp-2 w-full px-0.5 hyphens-auto break-words",
            hasColor ? "text-on" : "text-on-muted",
          )}
        >
          {displayName}
        </span>
        {badgeFailed && (
          <span className="text-[10px] text-on-muted leading-tight text-center">
            {failedNote}
          </span>
        )}
        {hasStatusBadge && (
          <span className="text-[10px] font-medium text-on-warning leading-tight text-center">
            {statusBadge.count > 99 ? "99+" : statusBadge.count}{" "}
            {statusBadge.label}
          </span>
        )}
      </div>

      {/* ── Desktop layout (≥ md) ── */}
      <div
        className={cn(
          "hidden md:flex flex-col items-center text-center p-5 rounded-xl min-h-[180px] justify-between",
          "bg-surface-card border border-border",
          "hover:bg-surface-raised hover:shadow-lg hover:border-primary-200/60",
          "active:scale-[0.98] transition-all duration-200",
        )}
      >
        {/* Top: icon + name + description */}
        <div className="flex flex-col items-center gap-1.5 w-full">
          <div
            className={cn(
              "w-14 h-14 rounded-2xl flex items-center justify-center shrink-0",
              hasColor ? iconBg : "bg-surface-raised",
            )}
          >
            <Icon
              size={28}
              strokeWidth={1.75}
              className={hasColor ? "text-white" : "text-on-muted"}
            />
          </div>
          <span className="text-sm font-semibold text-on leading-tight mt-1 line-clamp-2">
            {displayName}
          </span>
          {description && (
            <span className="text-xs text-on-muted leading-tight line-clamp-2">
              {description}
            </span>
          )}
        </div>

        {/* Bottom: status badge */}
        {badgeFailed && (
          <span className="text-xs text-on-muted mt-2">{failedNote}</span>
        )}
        {hasStatusBadge && (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-on-warning bg-amber-100 rounded-md px-2 py-0.5 mt-2">
            {statusBadge.count > 99 ? "99+" : statusBadge.count}{" "}
            {statusBadge.label}
          </span>
        )}
      </div>
    </Link>
  );
}
