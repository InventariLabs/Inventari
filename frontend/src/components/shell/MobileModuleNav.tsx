import { useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { MoreHorizontal, type LucideIcon } from "lucide-react";
import { makeTDynamic } from "@/lib/i18nHelpers";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useNavLeaveGuard } from "@/hooks/useNavLeaveGuard";
import type { ModuleNavItem } from "@/lib/moduleRegistry";
import { cn } from "@/lib/utils";

interface ModuleLink {
  basePath: string;
  displayName: string;
  icon: LucideIcon;
}

interface MobileModuleNavProps {
  bar: ModuleNavItem[];
  more: ModuleNavItem[];
  hasBar: boolean;
  isActive: (path: string) => boolean;
  otherModules?: ModuleLink[];
}

/** Mobile bottom navigation bar for the active module (rendered by AppShell). */
export function MobileModuleNav({
  bar,
  more,
  hasBar,
  isActive,
  otherModules = [],
}: MobileModuleNavProps) {
  const { t } = useTranslation("common");
  const tDyn = makeTDynamic(t);
  const [moreOpen, setMoreOpen] = useState(false);
  // The mobile bar is the phone's module menu — the same exit the desktop
  // tabs guard. The capture handler stops a blocked click before
  // the router or the more-menu's own close handler sees it.
  const { guardClick, confirmDialogProps } = useNavLeaveGuard();

  return (
    // A `<nav>`, so the phone's rotor finds the application's main navigation
    // where the desktop band already is one. It was a plain `<div>`: at 390px
    // the desktop band is `display:none`, which left the document with no
    // navigation landmark at all.
    <nav
      aria-label={t("navigation.moduleNavigation")}
      // the bar background extends under the iOS home indicator via
      // safe-area padding; the h-[var(--mobile-nav-height)] row keeps the
      // interactive content above it. Height is shared with AppShell.
      // z-index follows the layer system (--z-module-nav) — the
      // literal 45 was not an override of any real conflict.
      onClickCapture={guardClick}
      className="md:hidden fixed bottom-0 left-0 right-0 bg-surface-card border-t border-border pb-[env(safe-area-inset-bottom,0px)] z-[var(--z-module-nav)]"
    >
      {moreOpen && (
        <div className="border-t border-border bg-surface-card max-h-[60vh] overflow-y-auto">
          {hasBar && more.length > 0 && (
            <div className="grid grid-cols-3 gap-1 p-3">
              {more.map((item: ModuleNavItem) => {
                const active = isActive(item.path);
                const Icon = item.icon;
                const Badge = item.Badge;
                const labelKey = item.mobileLabelKey ?? item.labelKey;
                return (
                  <Link
                    key={item.path}
                    to={item.path}
                    onClick={() => setMoreOpen(false)}
                    className={cn(
                      "flex flex-col items-center justify-center py-2.5 rounded-xl transition-colors",
                      active
                        ? // The tint carries "active"; the label stays on the
                          // neutral token — `text-primary-600` on the card
                          // measured 3.77:1 light / 3.95:1 dark at the bar's
                          // 10px, and no primary pair survives the profile
                          // ramp repaints centrally (UI_GUIDELINES §1.1).
                          "bg-primary-50 font-semibold text-on"
                        : "text-on-secondary hover:text-on hover:bg-surface-raised/50",
                    )}
                    aria-current={active ? "page" : undefined}
                  >
                    <Icon size={20} strokeWidth={active ? 2.5 : 2} />
                    <span className="text-[10px] mt-1 leading-tight flex items-center gap-1 max-w-full">
                      <span className="truncate max-w-full min-w-0">
                        {tDyn(labelKey)}
                      </span>
                      {Badge && (
                        <span className="shrink-0">
                          <Badge />
                        </span>
                      )}
                    </span>
                  </Link>
                );
              })}
            </div>
          )}
          {otherModules.length > 0 && (
            <div className="border-t border-border px-3 py-2">
              <p className="text-[10px] font-medium uppercase tracking-widest text-on-muted px-1 mb-1">
                {t("navigation.modules", { defaultValue: "Modules" })}
              </p>
              <div className="grid grid-cols-3 gap-1">
                {otherModules.map((mod) => {
                  const Icon = mod.icon;
                  return (
                    <Link
                      key={mod.basePath}
                      to={mod.basePath}
                      onClick={() => setMoreOpen(false)}
                      className="flex flex-col items-center justify-center py-2.5 rounded-xl text-on-secondary hover:text-on hover:bg-surface-raised/50 transition-colors"
                    >
                      <Icon size={20} strokeWidth={2} />
                      <span className="text-[10px] mt-1 leading-tight truncate max-w-full">
                        {mod.displayName}
                      </span>
                    </Link>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
      <div className="flex h-[var(--mobile-nav-height)] items-center justify-around px-1">
        {bar.map((item: ModuleNavItem) => {
          const active = isActive(item.path);
          const Icon = item.icon;
          const Badge = item.Badge;
          const labelKey = item.mobileLabelKey ?? item.labelKey;
          return (
            <Link
              key={item.path}
              to={item.path}
              onClick={() => setMoreOpen(false)}
              className={cn(
                "flex flex-col w-full items-center justify-center py-2 rounded-xl transition-colors",
                active
                  ? // Weight and the heavier icon stroke carry "active";
                    // the label stays on the neutral token — the desktop
                    // band's reason verbatim (UI_GUIDELINES §1.1).
                    "font-semibold text-on"
                  : "text-on-muted hover:text-on-secondary",
              )}
              aria-label={tDyn(labelKey)}
              aria-current={active ? "page" : undefined}
            >
              <Icon size={20} strokeWidth={active ? 2.5 : 2} />
              <span className="text-[10px] mt-0.5 leading-tight flex items-center gap-1 max-w-full">
                {/* the label truncates, the badge never clips — the
                    old `truncate max-w-[60px]` on the wrapper pushed the
                    counter outside the item and rendered a green sliver. */}
                <span className="truncate max-w-full min-w-0">
                  {tDyn(labelKey)}
                </span>
                {Badge && (
                  <span className="shrink-0">
                    <Badge />
                  </span>
                )}
              </span>
            </Link>
          );
        })}
        {hasBar && more.length > 0 && (
          <Button
            type="button"
            onClick={() => setMoreOpen((v) => !v)}
            variant="ghost"
            size="contentSm"
            className={cn(
              "flex-col w-full py-2 rounded-xl gap-0.5 hover:bg-transparent active:bg-transparent",
              // Same neutral-token rule as the bar's tabs above.
              moreOpen
                ? "font-semibold text-on"
                : "text-on-muted hover:text-on-secondary",
            )}
            aria-label={t("navigation.more", { defaultValue: "More" })}
            aria-expanded={moreOpen}
          >
            <MoreHorizontal size={20} strokeWidth={moreOpen ? 2.5 : 2} />
            <span className="text-[10px] mt-0.5 leading-tight">
              {t("navigation.more", { defaultValue: "More" })}
            </span>
          </Button>
        )}
      </div>

      <ConfirmDialog {...confirmDialogProps} />
    </nav>
  );
}
