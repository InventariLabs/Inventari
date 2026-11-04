import {
  useState,
  useEffect,
  useCallback,
  useMemo,
  useRef,
  Suspense,
  lazy,
} from "react";
import { Outlet, Link, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Settings, Search, ChevronLeft } from "lucide-react";
import { useModules } from "@/contexts/ModulesContext";
import { useAuthStore } from "@/store/authStore";
import { BrandLogo } from "@/components/ui/BrandLogo";
import LoadingSpinner from "@/components/LoadingSpinner";
import { useProfileTheme } from "@/hooks/useProfileTheme";
import { useActiveProfile } from "@/hooks/useActiveProfile";
import { useRoleCheck } from "@/hooks/useHasRole";
import { useRouteScroll } from "@/hooks/useRouteScroll";
import { useShellBack } from "@/hooks/useShellBack";
import { moduleRegistry, applyNavOverrides } from "@/lib/moduleRegistry";
import type { ModuleNavItem } from "@/lib/moduleRegistry";
import { makeTDynamic } from "@/lib/i18nHelpers";
const NotificationTray = lazy(
  () => import("@/modules/announcements/components/NotificationTray"),
);
const NotificationsWebSocketBridge = lazy(() =>
  import("@/modules/announcements/components/NotificationsWebSocketBridge").then(
    (m) => ({ default: m.default }),
  ),
);
import { ThemeToggle } from "./ThemeToggle";
import { LanguageSelector } from "./LanguageSelector";
import { CommandPalette } from "./CommandPalette";
import { Slot } from "./Slot";
import { MobileModuleNav } from "./shell/MobileModuleNav";
import { ModuleSwitcher } from "./shell/ModuleSwitcher";
import { UserMenu } from "./shell/UserMenu";
import { FocusModeMarker } from "./shell/FocusModeMarker";
import { useNavLeaveGuard } from "@/hooks/useNavLeaveGuard";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { DemoSandboxNotice } from "@/components/demo/DemoSandboxNotice";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

export default function AppShell() {
  const { t } = useTranslation("common");
  const { enabledModules, hiddenModules, focusModule, focusStatus } =
    useModules();
  const { user, logout } = useAuthStore();
  const location = useLocation();
  const navigate = useNavigate();
  const [cmdOpen, setCmdOpen] = useState(false);
  const canSee = useRoleCheck();

  // Per-profile accent palette — applied after module
  // themes so the profile wins on conflicting keys.
  useProfileTheme();

  // Per-profile branding subtitle: "Inventari
  // for Home" / "Inventari for Business" — resolved from the active profile.
  const activeProfile = useActiveProfile();
  // Showing just one module narrows the workspace: the profile's label would
  // name a scope the shell no longer has, and the module switcher already
  // names the focused module.
  // Until the focus state is known the shell cannot tell which of the two it is in, so it claims neither.
  const subtitleKey =
    focusModule || (focusStatus ?? "ready") !== "ready"
      ? null
      : (activeProfile?.branding?.subtitle_key ?? null);
  // The launcher is set aside when just one module is shown; the root leads to the focused module.
  const homePath = focusModule ? "/" : "/launcher";
  useEffect(() => {
    const handleLogout = () => {
      logout();
      navigate("/login");
    };
    window.addEventListener("auth:logout", handleLogout);
    return () => window.removeEventListener("auth:logout", handleLogout);
  }, [logout, navigate]);

  // Owner recognition searches every enabled module, hidden ones included:
  // a route opened by direct link still needs its shell and header even when
  // focus mode keeps the module out of the navigation listings. On top of
  // that, a core section the focus module adopted (the label pool, the
  // scanner) renders under the focus module's banner — including printing's
  // flat `/labels/scan/:code`, the one entry a physical sticker has.
  const activeModule = moduleRegistry.getShellModule(
    location.pathname,
    enabledModules,
    focusModule,
  );

  // The header's own exits — the logo home link, the settings link, the links
  // inside the user menu and the module switcher — ask a dirty form before
  // they navigate. The module tabs and the mobile bar already route through
  // this gate; the header used to be the hole where the same address gave a
  // different answer depending on which control carried it.
  const { guardNavigate, guardClick, confirmDialogProps } = useNavLeaveGuard();

  const visibleModules = moduleRegistry.getVisibleModules(
    enabledModules,
    hiddenModules,
  );

  const moduleNav = activeModule?.moduleNav ?? null;
  // The page header's arrow is hidden on a phone, so the shell's must do what
  // it does: go back to the screen the person came from.
  const goBack = useShellBack(moduleNav?.basePath, homePath);

  useRouteScroll();

  const navOverrides = useMemo(
    () => moduleRegistry.getNavOverrides(enabledModules),
    [enabledModules],
  );

  const allNavItems = useMemo(() => {
    if (!moduleNav || !activeModule) return [];
    // The focus module's tabs gain its adopted core sections (deduped by
    // path); every other module keeps exactly its own items.
    const items = moduleRegistry.getShellNavItems(activeModule, focusModule);
    // The same two gates the module's desktop tabs pass (ModuleShell): the
    // bar used to skip the module one, so a tab whose screen needs another
    // module stayed on the phone with that module off.
    return applyNavOverrides(items, navOverrides)
      .filter((item) => canSee(item.roles))
      .filter(
        (item) =>
          !item.requiresModules ||
          item.requiresModules.some((name) => enabledModules.includes(name)),
      );
  }, [
    moduleNav,
    activeModule,
    focusModule,
    navOverrides,
    canSee,
    enabledModules,
  ]);

  const hasExactNavMatch = useMemo(
    () => allNavItems.some((item) => location.pathname === item.path),
    [allNavItems, location.pathname],
  );

  const isActive = (path: string) => {
    if (location.pathname === path) return true;
    if (hasExactNavMatch) return false;
    if (path === moduleNav?.basePath) return false;
    return location.pathname.startsWith(path + "/");
  };

  const mobileNavItems = useMemo(() => {
    if (!allNavItems.length) return { bar: [], more: [], hasBar: false };
    const position = (i: ModuleNavItem) => i.mobileOrder ?? i.order ?? 100;
    const sorted = [...allNavItems].sort((a, b) => position(a) - position(b));
    const mobile = sorted.filter((i) => i.showOnMobile !== false);
    const hasBar = mobile.some((i) => i.mobileBar);
    return {
      bar: hasBar ? mobile.filter((i) => i.mobileBar) : mobile,
      more: hasBar ? mobile.filter((i) => !i.mobileBar) : [],
      hasBar,
    };
  }, [allNavItems]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setCmdOpen((v) => !v);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  const handleClosePalette = useCallback(() => setCmdOpen(false), []);

  const handleLogout = useCallback(async () => {
    await logout();
  }, [logout]);

  const isNopadRoute = ["/inventory/scan", "/scan"].some((p) =>
    location.pathname.startsWith(p),
  );

  const otherModuleLinks = useMemo(() => {
    return visibleModules
      .filter((mod) => mod !== activeModule)
      .filter((mod) => mod.moduleNav?.basePath && mod.launcher)
      .map((mod) => ({
        basePath: mod.moduleNav!.basePath!,
        displayName: makeTDynamic(t)(mod.launcher!.displayName),
        icon: mod.launcher!.icon,
      }));
  }, [visibleModules, activeModule, t]);

  const showMobileNav = mobileNavItems.bar.length > 1;

  // The strip under the bar (demo notice, `global_notifications`) is as tall
  // as what it holds, and zero when it holds nothing. The sticky bars of the
  // module below it stack under it by that height, so neither covers the
  // other once the page scrolls — see `--app-notice-height` in ModuleShell.
  // On a phone the strip scrolls away with the page instead of sticking (it
  // would cover a third of the screen, the camera viewfinder included), so it
  // takes nothing from the bars there: the height is published from `md:` up.
  const noticeStripRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const strip = noticeStripRef.current;
    if (!strip || typeof ResizeObserver === "undefined") return;
    // On the root, not on `main`: the page scrolls as a whole, and the scroll
    // padding that keeps a focused field clear of the bars is set there.
    const root = document.documentElement;
    const wide = window.matchMedia?.("(min-width: 768px)");
    const publish = () =>
      root.style.setProperty(
        "--app-notice-height",
        `${wide && !wide.matches ? 0 : strip.getBoundingClientRect().height}px`,
      );
    publish();
    const observer = new ResizeObserver(publish);
    observer.observe(strip);
    wide?.addEventListener("change", publish);
    return () => {
      observer.disconnect();
      wide?.removeEventListener("change", publish);
      root.style.removeProperty("--app-notice-height");
    };
  }, []);

  // `overflow-x-clip`, not `-hidden`: both cut off what runs past the side, but
  // `hidden` also turns the root into a scroll container that never scrolls (it
  // grows with its content), and every `sticky` element below it then sticks to
  // that box instead of the window — the module nav and the footer of a
  // full-page form scrolled away with the page.
  return (
    <div className="min-h-screen bg-surface overflow-x-clip">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[var(--z-notification)] focus:px-4 focus:py-2 focus:rounded-lg focus:bg-primary-700 dark:focus:bg-primary-800 focus:text-white focus:shadow-lg"
      >
        {t("common:a11y.skipToContent", "Skip to content")}
      </a>
      {/* ── Top Bar ────────────────────────────────────────────────── */}
      <header
        className="fixed top-0 left-0 right-0 z-[var(--z-app-bar)] h-14 bg-surface-card border-b border-border flex items-center px-3 lg:px-4 gap-2"
        onClickCapture={guardClick}
      >
        {/* ── Left: Logo + module breadcrumb ── */}
        <div className="flex items-center gap-1.5 min-w-0 flex-1 md:flex-none">
          {activeModule?.launcher ? (
            <>
              <Button
                onClick={() => guardNavigate(goBack)}
                variant="ghost"
                size="icon"
                className="md:hidden -ml-1 shrink-0 text-on-muted hover:text-on"
                aria-label={t("actions.back", "Back")}
              >
                <ChevronLeft size={18} />
              </Button>

              {/* `py-2.5` is the hit area, not the wordmark: on a phone
                  the bare link around the logo measured 151x24 — the wordmark's own
                  line box — on all 20 routes that show one. Ten pixels above
                  and below it fit inside the 56px header, so the logo keeps its
                  size and the thumb gets the 44px floor. */}
              <Link
                to={homePath}
                className="hidden md:flex items-center gap-2 py-2.5 text-base font-semibold text-primary-600 shrink-0 mr-1"
              >
                <BrandLogo subtitleKey={subtitleKey} />
              </Link>

              <ModuleSwitcher
                activeModule={activeModule}
                enabledModules={enabledModules}
                hiddenModules={hiddenModules}
              />
            </>
          ) : (
            <Link
              to={homePath}
              className="flex items-center gap-2 py-2.5 text-base font-semibold text-primary-600 shrink-0"
            >
              <BrandLogo subtitleKey={subtitleKey} />
            </Link>
          )}
          <FocusModeMarker />
        </div>

        {/* Below md the left group already grows to push the actions right;
            a second growing box would split the free room with it and cut
            the single-module marker down to a letter. */}
        <div className="hidden md:block flex-1" />

        {/* ── Right: actions ── */}
        <div className="flex items-center gap-1 shrink-0">
          <Button
            onClick={() => setCmdOpen(true)}
            variant="outline"
            size="sm"
            className="hidden sm:flex bg-transparent text-sm text-on-muted"
            aria-keyshortcuts="Control+K Meta+K"
          >
            <Search size={15} />
            {/* The words it shows are its name, read below `lg:` too, where
                the button is an icon: an `aria-label` that left them out
                named it something a voice user could not see to say. */}
            <span className="sr-only lg:not-sr-only">
              {t("commandPalette.placeholder")}
            </span>
            <kbd
              aria-hidden="true"
              className="hidden lg:inline px-1 rounded text-[10px] font-mono border border-border bg-surface text-on-muted"
            >
              ⌘K
            </kbd>
          </Button>

          <Button
            onClick={() => setCmdOpen(true)}
            variant="ghost"
            size="icon"
            className="sm:hidden text-on-muted"
            aria-label={t("commandPalette.placeholder")}
            aria-keyshortcuts="Control+K Meta+K"
          >
            <Search size={18} />
          </Button>

          {enabledModules.includes("announcements") && (
            <Suspense fallback={null}>
              <NotificationsWebSocketBridge />
              <NotificationTray />
            </Suspense>
          )}

          <Link
            to="/settings"
            className={cn(
              "hidden sm:flex p-2 rounded-lg transition-colors",
              // `primary-50` is already a dark tint under `.dark`; the icon
              // keeps `primary-600`, which clears the 3:1 graphics threshold in
              // both themes, unlike the `primary-400` step the override used
              // (it flips to a dark shade in dark mode).
              location.pathname.startsWith("/settings")
                ? "bg-primary-50 text-primary-600"
                : "text-on-muted hover:bg-surface-raised hover:text-on",
            )}
            aria-label={t("navigation.settings", "Settings")}
            aria-current={
              location.pathname.startsWith("/settings") ? "page" : undefined
            }
            title={t("navigation.settings", "Settings")}
          >
            <Settings size={18} />
          </Link>

          <div className="hidden sm:flex items-center gap-1">
            <ThemeToggle />
            <LanguageSelector align="right" />
          </div>

          <UserMenu user={user} onLogout={handleLogout} />
        </div>

        <ConfirmDialog {...confirmDialogProps} />
      </header>

      {/* ── Page Content ─────────────────────────────────────────────── */}
      <main
        id="main-content"
        className={cn(
          "pt-14",
          // compensate the fixed bottom bar (height + safe area) so
          // the last list row / form control is never hidden behind it.
          showMobileNav &&
            "pb-[calc(var(--mobile-nav-height)+env(safe-area-inset-bottom,0px))] md:pb-0",
        )}
      >
        <div
          ref={noticeStripRef}
          className="sticky max-md:static top-14 z-[var(--z-module-nav)]"
        >
          <DemoSandboxNotice />
          <Slot name="global_notifications" />
        </div>
        <div
          className={cn(
            !isNopadRoute && "p-3 lg:p-4 2xl:p-6 3xl:p-8",
            // The screen below the app bar — and above the bottom bar, whose
            // room `main` already pads in: counted twice, every short page
            // on a phone scrolled by the bar's height.
            showMobileNav
              ? "min-h-[calc(100dvh-3.5rem-var(--mobile-nav-height)-env(safe-area-inset-bottom,0px))] md:min-h-[calc(100dvh-3.5rem)]"
              : "min-h-[calc(100dvh-3.5rem)]",
          )}
        >
          {/* A screen on its way keeps the shell around it. */}
          <Suspense fallback={<LoadingSpinner />}>
            <Outlet />
          </Suspense>
        </div>
      </main>

      {/* ── Mobile Module Nav (rendered at same level as header) ── */}
      {showMobileNav && (
        <MobileModuleNav
          bar={mobileNavItems.bar}
          more={mobileNavItems.more}
          hasBar={mobileNavItems.hasBar}
          isActive={isActive}
          otherModules={otherModuleLinks}
        />
      )}

      {/* Cmd+K palette */}
      <CommandPalette open={cmdOpen} onClose={handleClosePalette} />
    </div>
  );
}
