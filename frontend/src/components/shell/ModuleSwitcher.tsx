import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ChevronDown, LayoutGrid } from "lucide-react";
import {
  moduleRegistry,
  resolveModuleTarget,
  type FrontendModule,
} from "@/lib/moduleRegistry";
import { useHasPermission } from "@/hooks/useHasPermission";
import { makeTDynamic } from "@/lib/i18nHelpers";
import { cn } from "@/lib/utils";

interface ModuleSwitcherProps {
  activeModule: FrontendModule;
  enabledModules: string[];
  /** Modules focus mode hides from navigation listings. */
  hiddenModules?: string[];
}

/**
 * ModuleSwitcher — header breadcrumb dropdown listing every visible module.
 *
 * The only persistent cross-module navigation on desktop: deep links and
 * the single-module view land the user inside a module and module tab bars are
 * module-local, so without this the rest of the workspace is reachable
 * only via the command palette.
 *
 * Interaction pattern mirrors `UserMenu` (useState + outside mousedown,
 * Escape closes, role="menu").
 */
export function ModuleSwitcher({
  activeModule,
  enabledModules,
  hiddenModules = [],
}: ModuleSwitcherProps) {
  const { t } = useTranslation("common");
  const tDyn = makeTDynamic(t);
  const isAdmin = useHasPermission("admin:access");
  const [open, setOpen] = useState(false);
  // A dirty form is asked by the shell header this switcher sits in — its
  // capture handler sees the links inside this menu before the router does,
  // so the switcher carries no gate of its own.

  useEffect(() => {
    if (!open) return;
    const onMouseDown = (e: MouseEvent) => {
      if (!(e.target as Element).closest("[data-module-switcher]")) {
        setOpen(false);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onMouseDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const modules = moduleRegistry
    .getVisibleModules(enabledModules, hiddenModules)
    .sort((a, b) =>
      tDyn(a.launcher!.displayName).localeCompare(
        tDyn(b.launcher!.displayName),
      ),
    );

  // A one-entry dropdown switches nothing — focus mode leaves exactly one
  // visible module, so the switcher steps aside and the breadcrumb keeps
  // just the logo.
  if (modules.length <= 1) return null;

  const ActiveIcon = activeModule.launcher!.icon;

  return (
    <div className="relative" data-module-switcher>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex items-center gap-1.5 rounded-lg px-1.5 py-3 md:py-1 md:mx-1 text-sm font-semibold text-on hover:bg-surface-raised transition-colors"
      >
        <ActiveIcon size={16} className="shrink-0 text-on-muted" />
        <span>{tDyn(activeModule.launcher!.displayName)}</span>
        {/* The module it shows starts the name, and what the button does
            follows it, read but not shown. An `aria-label` of the purpose
            alone left out the one word on screen, so a voice user had nothing
            visible to call it by. The space collapses between flex items on
            screen and keeps the two parts two words in the name. */}{" "}
        <span className="sr-only">{t("navigation.switchModule")}</span>
        <ChevronDown size={14} className="shrink-0 text-on-muted" />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute left-0 top-full mt-1 w-max min-w-56 max-w-[calc(100vw-2rem)] max-h-[70vh] overflow-y-auto rounded-xl border border-border bg-surface-card shadow-2xl py-1 z-[var(--z-module-nav)]"
        >
          {modules.map((mod) => {
            const Icon = mod.launcher!.icon;
            const isActive = mod.name === activeModule.name;
            return (
              <Link
                key={mod.name}
                to={resolveModuleTarget(mod)}
                role="menuitem"
                onClick={() => setOpen(false)}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  "flex items-center gap-2.5 px-4 py-2 text-sm transition-colors",
                  isActive
                    ? "bg-primary-50 text-on font-semibold"
                    : "text-on-secondary hover:bg-surface-raised",
                )}
              >
                <Icon size={15} className="shrink-0" />
                <span>{tDyn(mod.launcher!.displayName)}</span>
              </Link>
            );
          })}
          <div className="mt-1 border-t border-border pt-1">
            {/* One door to "which modules do I see": the settings screen that
                decides it. Choosing them is the administrator's job, so a
                member keeps the link that opens the module grid instead of a
                screen whose controls are not theirs. */}
            <Link
              to={isAdmin ? "/settings/my-modules" : "/launcher"}
              role="menuitem"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2.5 px-4 py-2 text-sm text-on-secondary hover:bg-surface-raised transition-colors"
            >
              <LayoutGrid size={15} className="shrink-0" />
              {isAdmin
                ? t("settings.tabs.myModules")
                : t("navigation.allModules", "All modules")}
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
