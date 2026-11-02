import { useEffect, useMemo, useState, Suspense, useCallback } from "react";
import { Outlet, Link, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  moduleRegistry,
  applyNavOverrides,
  type ModuleNavItem,
} from "@/lib/moduleRegistry";
import { useModules } from "@/contexts/ModulesContext";
import { useRoleCheck } from "@/hooks/useHasRole";
import { makeTDynamic } from "@/lib/i18nHelpers";
import { cn } from "@/lib/utils";
import LoadingSpinner from "@/components/LoadingSpinner";
import { FocusBackgroundFeatures } from "@/components/shell/FocusBackgroundFeatures";
import { PageHeader } from "@/components/ui/PageHeader";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ScrollRow } from "@/components/ui/ScrollRow";
import { useNavLeaveGuard } from "@/hooks/useNavLeaveGuard";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";

interface ModuleShellProps {
  moduleName: string;
}

export default function ModuleShell({ moduleName }: ModuleShellProps) {
  const { t } = useTranslation("common");
  const tDyn = makeTDynamic(t);
  const location = useLocation();
  const [headerData, setHeaderData] = useState<PageHeaderData>({});
  const { enabledModules, focusModule } = useModules();
  const canSee = useRoleCheck();
  // A form holding unsaved work asks before the module tabs throw it away.
  // The back arrow is guarded inside PageHeader.
  const { guardClick, confirmDialogProps } = useNavLeaveGuard();

  // The shell follows the same resolution as AppShell: normally the module
  // whose route tree this is (a hidden module opened by direct link keeps its
  // own shell), except that a core section the focus module adopted renders
  // under the focus module's banner, tabs and theme. When no adoption claims
  // the path this resolves back to `moduleName` and nothing below changes.
  const shellModule = moduleRegistry.getShellModule(
    location.pathname,
    enabledModules,
    focusModule,
  );
  const effectiveModuleName = shellModule?.name ?? moduleName;

  const moduleNav = moduleRegistry.getModuleNav(effectiveModuleName);
  const mod = moduleRegistry.getModule(effectiveModuleName);

  useEffect(() => {
    const cssVars = mod?.theme?.cssVariables;
    if (!cssVars) return;
    const root = document.documentElement;
    const originals: Record<string, string> = {};
    Object.entries(cssVars).forEach(([varName, value]) => {
      originals[varName] = root.style.getPropertyValue(varName) ?? "";
      root.style.setProperty(varName, value);
    });
    return () => {
      Object.entries(originals).forEach(([varName, original]) => {
        if (original === "") {
          root.style.removeProperty(varName);
        } else {
          root.style.setProperty(varName, original);
        }
      });
    };
  }, [mod?.theme?.cssVariables]);

  useEffect(() => {
    document.documentElement.dataset.module = effectiveModuleName;
    return () => {
      delete document.documentElement.dataset.module;
    };
  }, [effectiveModuleName]);

  const navOverrides = useMemo(
    () => moduleRegistry.getNavOverrides(enabledModules),
    [enabledModules],
  );

  const sortedItems: ModuleNavItem[] = useMemo(() => {
    if (!moduleNav) return [];
    // `mod` is the registry entry behind the effective shell module; when it
    // is missing there is nothing to adopt with, and the module's own items
    // are the whole answer.
    const items = mod
      ? moduleRegistry.getShellNavItems(mod, focusModule)
      : moduleNav.items;
    return applyNavOverrides(items, navOverrides)
      .filter((item) => canSee(item.roles))
      .filter(
        (item) =>
          !item.requiresModules ||
          item.requiresModules.some((name) => enabledModules.includes(name)),
      )
      .sort((a, b) => (a.order ?? 100) - (b.order ?? 100));
  }, [moduleNav, mod, focusModule, navOverrides, canSee, enabledModules]);

  const desktopItems = useMemo(
    () => sortedItems.filter((item) => item.showOnDesktop !== false),
    [sortedItems],
  );

  const showNavBar = desktopItems.length > 1;

  const hasExactMatch = useMemo(
    () => sortedItems.some((item) => location.pathname === item.path),
    [sortedItems, location.pathname],
  );

  const isActive = useCallback(
    (path: string) => {
      if (location.pathname === path) return true;
      if (hasExactMatch) return false;
      if (path === moduleNav?.basePath) return false;
      return location.pathname.startsWith(path + "/");
    },
    [location.pathname, hasExactMatch, moduleNav?.basePath],
  );

  /**
   * The nav item whose page this *is*, not the one it sits under.
   *
   * The tab underline follows the prefix, because a screen nested under a
   * section still belongs to that section. The page header must not: the
   * title and subtitle on a nav item describe that item's own screen, so a
   * prefix match handed the creation form the list's description ("Browse and
   * manage products") and made a zone's error screen introduce itself as the
   * storage list. Nested screens set their own header; where they set none,
   * an empty header is the honest answer.
   */
  const exactItem = useMemo(
    () => sortedItems.find((item) => location.pathname === item.path),
    [sortedItems, location.pathname],
  );

  if (!moduleNav) {
    return <Outlet />;
  }

  return (
    <PageHeaderContext.Provider
      value={{ data: headerData, setHeader: setHeaderData }}
    >
      {showNavBar ? (
        <nav
          aria-label={t("navigation.moduleNavigation")}
          onClickCapture={guardClick}
          className="hidden md:block px-3 lg:px-4 2xl:px-6 3xl:px-8 -mx-3 lg:-mx-4 2xl:-mx-6 3xl:-mx-8 -mt-3 lg:-mt-4 2xl:-mt-6 3xl:-mt-8 mb-4 md:mb-6 border-t border-b border-border bg-surface-card sticky top-[calc(3.5rem+var(--app-notice-height,0px))] z-[var(--z-module-nav)] h-11"
        >
          {/* The scroller is the inner row, not the bar: the bar's own borders
              run the full width of the page and a mask would fade them at the
              edges. Six tabs already overflow a 768px viewport. */}
          <ScrollRow className="flex items-center gap-0.5 h-full">
            {desktopItems.map((item) => {
              const active = isActive(item.path);
              const Icon = item.icon;
              const Badge = item.Badge;
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={cn(
                    "flex shrink-0 items-center gap-2 px-3 py-2 text-sm font-medium transition-colors whitespace-nowrap border-b-2 -mb-px",
                    // The underline and the weight carry "active"; the label
                    // stays on the neutral text token, because `primary-*` is
                    // repainted per product profile and a brand-on-surface pair
                    // cannot be kept above 4.5:1 centrally.
                    active
                      ? "text-on font-semibold border-primary-600"
                      : "text-on-secondary hover:text-on hover:bg-surface-raised/50 border-transparent",
                  )}
                  aria-current={active ? "page" : undefined}
                >
                  <Icon size={16} />
                  <span>{tDyn(item.labelKey)}</span>
                  {Badge && <Badge />}
                </Link>
              );
            })}
          </ScrollRow>
        </nav>
      ) : (
        // A module with a single screen renders no tabs — a tab that selects
        // the only page is noise. Its page must still start at the same height
        // as every other module's, so the band's space is reserved rather than
        // filled with a made-up tab.
        <div
          aria-hidden="true"
          className="hidden md:block h-11 -mt-3 lg:-mt-4 2xl:-mt-6 3xl:-mt-8 mb-4 md:mb-6"
        />
      )}

      <PageHeader
        title={
          headerData.title ||
          tDyn(exactItem?.titleKey ?? exactItem?.labelKey ?? "")
        }
        subtitle={headerData.subtitle || tDyn(exactItem?.subtitleKey ?? "")}
        actions={
          effectiveModuleName === focusModule ? (
            <>
              <FocusBackgroundFeatures
                key={focusModule}
                moduleName={focusModule}
              />
              {headerData.actions}
            </>
          ) : (
            headerData.actions
          )
        }
        backTo={headerData.backTo}
        statusBadge={headerData.statusBadge}
        // No horizontal padding below `md`: AppShell already pads the page, and
        // the second layer cost 24px of a 390px phone screen before the first
        // character of content. Desktop keeps the wider gutter.
        className="md:px-4 lg:px-6 pt-4 md:pt-6 pb-2 max-w-[1920px] mx-auto w-full"
      />

      <div className="md:px-4 lg:px-6 max-w-[1920px] mx-auto pb-8">
        <Suspense fallback={<LoadingSpinner />}>
          <Outlet />
        </Suspense>
      </div>

      <ConfirmDialog {...confirmDialogProps} />
    </PageHeaderContext.Provider>
  );
}
