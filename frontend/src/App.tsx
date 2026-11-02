import {
  createBrowserRouter,
  createMemoryRouter,
  createRoutesFromElements,
  RouterProvider,
  Route,
  Navigate,
  useLocation,
  useParams,
  type RouteObject,
} from "react-router-dom";
import {
  useEffect,
  Suspense,
  lazy,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { useAuthStore } from "./store/authStore";
import { useModules } from "./contexts/ModulesContext";
import { FocusLockGate } from "./components/FocusLockGate";
import {
  moduleRegistry,
  type FrontendModule,
  type ModuleRoute,
  type SettingsSection,
} from "./lib/moduleRegistry";
import { registerModules } from "./lib/moduleRegistry/moduleLoaders";
import { shellRoutes } from "./lib/moduleRegistry/shellRoutes";
import { RootRedirect, LauncherRoute } from "./components/RootRedirect";
import BackendUnavailable from "./components/BackendUnavailable";
import ModulesUnavailable from "./components/ModulesUnavailable";

// Shared Pages - Lazy Loaded
const LoginPage = lazy(() => import("./pages/LoginPage"));
const ForgotPasswordPage = lazy(() => import("./pages/ForgotPasswordPage"));
const ResetPasswordPage = lazy(() => import("./pages/ResetPasswordPage"));
const RegisterPage = lazy(() => import("./pages/RegisterPage"));
const PrivacyPage = lazy(() => import("./pages/PrivacyPage"));
const JoinOrganizationPage = lazy(
  () => import("./modules/settings/pages/JoinOrganizationPage"),
);
const OnboardingPage = lazy(
  () => import("./modules/onboarding/pages/OnboardingPage"),
);
// ErrorPage is not lazy on purpose: it is the route tree's `errorElement`, and
// an error screen that has to download before it can say anything is an error
// screen that may never arrive.
import ErrorPage from "./pages/ErrorPage";
const NotFoundPage = lazy(() => import("./pages/NotFoundPage"));

// App Store
const AppStore = lazy(() => import("./modules/settings/components/AppStore"));

// Settings Shell + sub-sections
const SettingsShell = lazy(() => import("./components/SettingsShell"));
const SettingsGeneralSection = lazy(
  () => import("./modules/settings/pages/SettingsGeneralSection"),
);
const SettingsMyModulesSection = lazy(
  () => import("./modules/settings/pages/SettingsMyModulesSection"),
);
const SettingsAboutSection = lazy(
  () => import("./modules/settings/pages/SettingsAboutSection"),
);
const SettingsProfileSection = lazy(
  () => import("./modules/settings/pages/SettingsProfileSection"),
);
const ModuleSettingsPage = lazy(
  () => import("./modules/settings/pages/ModuleSettingsPage"),
);
const SettingsAiSection = lazy(
  () => import("./modules/settings/pages/SettingsAiSection"),
);
const SettingsEmailSection = lazy(
  () => import("./modules/settings/pages/SettingsEmailSection"),
);
const AuditLogPage = lazy(
  () => import("./modules/settings/pages/AuditLogPage"),
);
const RolesPage = lazy(
  () => import("./modules/settings/components/roles/RolesPage"),
);

// AdminPage removed — admin functionality now lives in modules

// Shell components
import AppShell from "./components/AppShell";
import ModuleShell from "./components/ModuleShell";
import LoadingSpinner from "./components/LoadingSpinner";
import { OnboardingGuard } from "@/modules/onboarding/components/OnboardingGuard";

/** Redirect that preserves query-string and hash (e.g. /items?location_id=X → /inventory/items?location_id=X). */
function RedirectPreserving({ to }: { to: string }) {
  const { search, hash } = useLocation();
  return <Navigate to={`${to}${search}${hash}`} replace />;
}

/** Relative path of an absolute route path within a module base path. */
function relPath(absolutePath: string, basePath: string): string {
  const rel = absolutePath.replace(basePath, "").replace(/^\//, "");
  return rel || "";
}

/**
 * Whether this page load has had a signed-in session — read by PrivateRoute
 * to decide whether the address it turns away may ride along to the sign-in.
 *
 * It cannot live on the route component: a sign-out flips the module list to
 * its fallback, App rebuilds the router under a new key, and the PrivateRoute
 * rendering the redirect is a fresh instance — a ref there is already gone by
 * then, which is how the page the session ended on reached the next account.
 * Set in App, which no rebuild replaces, and never set by a page load that
 * starts signed out: that is an address opened signed out.
 */
let hadSession = false;

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading, authUnavailable } = useAuthStore();
  const location = useLocation();

  // The outage outranks the spinner. They can be true at once — the retry
  // runs with the previous "no answer" standing — and the reader is by then
  // looking at the screen that carries the button they pressed: the busy
  // state belongs on that button, not on a full-screen spinner that takes the
  // message away for as long as the ask lasts.
  //
  // "We could not ask" is not "you are not signed in": sending the reader to a
  // sign-in form that fails for the same reason loses the route for nothing.
  if (authUnavailable) {
    return <BackendUnavailable />;
  }

  if (isLoading) {
    return <LoadingSpinner fullScreen />;
  }

  if (!isAuthenticated) {
    // The address asked for rides along, so signing in continues to it — a
    // printed label opened signed out would otherwise lose its code. Not the
    // bare root (it is where signing in goes anyway, and it must not outrank
    // the demo launcher), and not the page a session ended on: `hadSession`
    // says this page load carried a session, so the address below is where
    // that session stopped, not where somebody opened signed out.
    const asked = `${location.pathname}${location.search}${location.hash}`;
    return (
      <Navigate
        to="/login"
        replace
        state={
          hadSession || location.pathname === "/" ? undefined : { from: asked }
        }
      />
    );
  }

  return <>{children}</>;
}

type AppProps = {
  /**
   * Where the route tree starts. A data router reads the address the browser
   * is already at, so the application never passes this — it exists for
   * tests, which have no address to be at and cannot write one either:
   * `window.location` survives `history.replaceState` in this jsdom.
   */
  initialEntries?: string[];
};

/** Counts the routers built, so each one can name the provider that renders it. */
let routerSeq = 0;

function App({ initialEntries }: AppProps = {}) {
  const { checkAuth, isAuthenticated, isLoading, authUnavailable } =
    useAuthStore();
  const {
    enabledModules,
    isLoading: isLoadingModules,
    modulesError,
    refreshModules,
  } = useModules();

  // The document's language follows the language on screen from the first
  // route, whatever route it is. index.html ships `lang="en"` for whatever
  // reads the document before React mounts, and a signed-out visitor meets
  // a Polish form on /login before any shell exists — left alone, a screen
  // reader pronounced that form in English phonetics and the browser
  // offered to translate the page it was already showing.
  const { i18n } = useTranslation();
  useEffect(() => {
    document.documentElement.lang = i18n.language?.substring(0, 2) ?? "en";
  }, [i18n.language]);

  // Modules register here, not at import time: importing a module.ts drags
  // in that module's registration code and its API layer, and none of it
  // belongs in the entry chunk a signed-out visitor downloads or in the
  // first paint of an organization that switched the module off. The import
  // is the registration (a side effect of the module file), so this effect
  // is the whole act; it re-runs when the enabled list changes — an
  // organization or module switch imports what arrived with it.
  // The list whose chunks are actually in the registry — not a boolean.
  // A boolean stays true for ever after the first registration, so when the
  // enabled list changed while the new chunks were still importing, the memo
  // below rebuilt the routes too early, `setModulesRegistered(true)` then
  // changed no state, and nothing ever rebuilt them: the page stayed a 404
  // until a full reload.
  const [registeredFor, setRegisteredFor] = useState<readonly string[] | null>(
    null,
  );
  useEffect(() => {
    // The context hands the default install's list while the real one is in
    // flight — importing eighteen modules off that guess is exactly the
    // waste this replaced, and the gate above keeps the screen up anyway.
    // The list that survived a failed read is empty on purpose; a retry
    // re-runs this with whatever it brings.
    if (!isAuthenticated || isLoadingModules) return;
    let cancelled = false;
    registerModules(enabledModules).then(() => {
      if (cancelled) return;
      // ModulesContext applied the overrides when this list changed —
      // before these imports landed, so modules bringing i18n or theme
      // overrides had nothing in the registry to override with. Now they
      // are in, and the application has to read them again.
      moduleRegistry.applyI18nOverrides(enabledModules);
      moduleRegistry.applyThemeOverrides(enabledModules);
      setRegisteredFor(enabledModules);
    });
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, isLoadingModules, enabledModules]);

  // True only while the registry holds exactly the list on screen. Compared by
  // content, so a fresh array of the same names does not send the reader back
  // to the spinner; while the chunks are still importing it is false, the gate
  // below holds the spinner, and the memos build from a filled registry when
  // they land.
  const modulesRegistered =
    registeredFor !== null &&
    registeredFor.length === enabledModules.length &&
    registeredFor.every((name, index) => name === enabledModules[index]);

  // Separate modules into: those with module-scoped nav (wrapped in ModuleShell)
  // vs. those with flat routes (rendered directly in AppShell content area).
  // Both memos read the registry, and the enabled list can be in hand while
  // the module chunks are still importing — building against a half-filled
  // registry and never recomputing is how every module path ends up a 404.
  // Until registration lands the answers are empty; the gate above keeps
  // the screen on the spinner meanwhile.
  const { shellModules, flatRoutes } = useMemo(() => {
    if (!modulesRegistered) return { shellModules: [], flatRoutes: [] };

    const enabled = enabledModules
      .map((modName) => moduleRegistry.getModule(modName))
      .filter((mod): mod is FrontendModule => Boolean(mod));
    const mounted = shellRoutes(enabled);
    // Exclude index routes from flat list — RootRedirect owns the root index.
    return {
      shellModules: mounted.shellModules,
      flatRoutes: mounted.flatRoutes.filter((r) => !r.index),
    };
  }, [enabledModules, modulesRegistered]);

  // Dynamic settings sections contributed by enabled modules.
  const settingsSections = useMemo(
    () =>
      modulesRegistered
        ? moduleRegistry.getSettingsSections(enabledModules)
        : [],
    [enabledModules, modulesRegistered],
  );

  // Above the early returns on purpose: a hook is called on every render or
  // the rules of hooks have a word for it. The router is rebuilt when the
  // route tree changes — module registration at boot, and a profile switch
  // later. Each router gets its own `key` below: without a fresh provider per
  // router, a module leaving the list sent the reader away from the page they
  // were on — a legacy redirect rendered in its place.
  const { router, key: routerKey } = useMemo(() => {
    const routes = createAppRoutes(shellModules, flatRoutes, settingsSections);
    const created = initialEntries
      ? createMemoryRouter(routes, { initialEntries })
      : createBrowserRouter(routes);
    return { router: created, key: (routerSeq += 1) };
  }, [shellModules, flatRoutes, settingsSections, initialEntries]);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  // The flag PrivateRoute reads outlives the route tree: recorded here, in
  // the component no router rebuild replaces, and only once this page load
  // really holds a session (see `hadSession` above).
  useEffect(() => {
    if (isAuthenticated) hadSession = true;
  }, [isAuthenticated]);

  // The boot spinner belongs to a boot. With the outage screen up, the retry
  // keeps it: the reader is answering the message on that screen, and the
  // button names the attempt in flight. `authUnavailable` stands through the
  // retry for exactly this reason — see authStore.checkAuth.
  // The registration gate stands next to the two loads it depends on: the
  // module list and the module chunks themselves. Signed out, neither runs —
  // the sign-in screen needs no module registry, and holding it behind a
  // spinner would be waiting for work that is never coming.
  if (
    (isLoading && !authUnavailable) ||
    isLoadingModules ||
    (isAuthenticated && !modulesRegistered)
  ) {
    return <LoadingSpinner fullScreen />;
  }

  // The map of what this organization can do could not be read. Offering no
  // work is the honest answer — the navigation stays empty and the screen
  // names the outage, instead of a default install's module list standing in
  // for an answer the backend never gave.
  if (modulesError) {
    return <ModulesUnavailable onRetry={refreshModules} />;
  }

  return (
    <Suspense fallback={<LoadingSpinner fullScreen />}>
      <RouterProvider key={routerKey} router={router} />
    </Suspense>
  );
}

/**
 * The application's route tree, as the elements it is declared in.
 *
 * This is the seam the error screen is tested at: `createAppRoutes` turns this
 * into a data router's route objects, and a test can build the same tree with
 * one route planted to fail. Keeping the declaration in JSX keeps the diff
 * that moved the router honest — the routes below are the routes that were
 * here before, only no longer under a `<Routes>` element.
 */
export function appRouteTree(
  shellModules: FrontendModule[],
  flatRoutes: ModuleRoute[],
  settingsSections: SettingsSection[],
) {
  return (
    <>
      {/* Public routes */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/privacy" element={<PrivacyPage />} />
      <Route path="/reset-password/:token" element={<ResetPasswordPage />} />
      <Route path="/join" element={<JoinOrganizationPage />} />
      {/* Old invitation links name the code in the path; without this
            route they fell through the catch-all to "/" and, signed out,
            silently on to /login — the own-organization trap. */}
      <Route path="/join/:token" element={<JoinOrganizationPage />} />
      {/* The attestation link an employee opens from an email is served by
            `PublicApp`, a tree of its own — see publicRoutes.ts. It cannot
            live here: the glob above hands whoever reaches this file every
            module in the application. */}
      {/* Onboarding — protected (requires auth) but outside AppShell */}
      <Route
        path="/onboarding"
        element={
          <PrivateRoute>
            <OnboardingPage />
          </PrivateRoute>
        }
      />
      {/* Protected routes — AppShell replaces Layout */}
      <Route
        path="/"
        element={
          <PrivateRoute>
            <OnboardingGuard>
              {/* No error boundary around the shell: a route that throws is
                    the route tree's own failure, and `createAppRoutes` names
                    the screen for it. A boundary here would answer in its own
                    words — one screen for one failure. */}
              <AppShell />
            </OnboardingGuard>
          </PrivateRoute>
        }
      >
        {/* Home — Launcher tile grid, or the focused module when just one module is shown */}
        <Route index element={<RootRedirect />} />
        {/* Launcher stays reachable at a stable URL even when the root
              index redirects to the focused module */}
        <Route path="launcher" element={<LauncherRoute />} />

        {/* Module-scoped routes wrapped in ModuleShell (modules with moduleNav) */}
        {shellModules.map((mod) => {
          const base = mod.moduleNav!.basePath; // e.g. '/inventory'
          const baseSegment = base.replace(/^\//, ""); // 'inventory'
          return (
            <Route
              key={mod.name}
              path={`${baseSegment}/*`}
              element={<ModuleShell moduleName={mod.name} />}
            >
              {mod.routes.map((route) => {
                const rel = relPath(route.path, base);
                const element = (
                  <RouteGate requiresModules={route.requiresModules}>
                    <route.component />
                  </RouteGate>
                );
                if (rel === "") {
                  return (
                    <Route key={`${mod.name}-index`} index element={element} />
                  );
                }
                return <Route key={route.path} path={rel} element={element} />;
              })}
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          );
        })}

        {/* Flat module routes (modules without moduleNav — old-style single-path modules) */}
        {flatRoutes.map((route) => (
          <Route
            key={route.path}
            path={
              route.path.startsWith("/") ? route.path.substring(1) : route.path
            }
            element={<route.component />}
          />
        ))}

        {/* App Store (admin-only, guard inside component) */}
        <Route
          path="apps"
          element={
            <FocusLockGate>
              <AppStore />
            </FocusLockGate>
          }
        />

        {/* Settings (SettingsShell with sidebar + sub-sections) */}
        <Route path="settings" element={<SettingsShell />}>
          <Route index element={<SettingsGeneralSection />} />
          <Route path="my-modules" element={<SettingsMyModulesSection />} />
          {/* "My modules" is one screen for the module set and the
                single-module toggles; the two addresses that used to hold one
                half each survive so a bookmark still lands on the whole. */}
          <Route
            path="workspace"
            element={<Navigate to="/settings/my-modules" replace />}
          />
          <Route
            path="focus"
            element={<Navigate to="/settings/my-modules" replace />}
          />
          <Route path="about" element={<SettingsAboutSection />} />
          <Route path="profile" element={<SettingsProfileSection />} />
          {/* The whole content of this page was a sentence and a button
                pointing at /apps — which is also where the sidebar has always
                linked. The address survives for bookmarks. */}
          <Route path="modules" element={<Navigate to="/apps" replace />} />
          <Route path="modules/:name" element={<ModuleSettingsPage />} />
          <Route path="ai" element={<SettingsAiSection />} />
          <Route path="email" element={<SettingsEmailSection />} />
          {/* "Developer" held the mail server and the AI connections under a
                name that described neither. The address survives as an alias so
                a bookmark still lands somewhere. */}
          <Route
            path="developer"
            element={<Navigate to="/settings/ai" replace />}
          />
          <Route path="audit-log" element={<AuditLogPage />} />
          {/* Access & Roles — the RBAC matrix; admin-only by default
                (settingsAccess.ts denies what is not explicitly member-listed). */}
          <Route path="roles" element={<RolesPage />} />
          {/* Module-contributed settings sections */}
          {settingsSections.map((section) => (
            <Route
              key={section.path}
              path={section.path}
              element={<section.component />}
            />
          ))}
        </Route>

        {/* --- Backward-compatibility redirect aliases --- */}
        {/* Webhooks lived on a flat route as well as in settings. The flat
              one had no PageHeaderContext above it, so its header — carrying
              the only "Add webhook" button once the list was non-empty — went
              nowhere. One screen, one address: the settings one, which is
              where the sidebar has always pointed. */}
        <Route
          path="webhooks"
          element={<Navigate to="/settings/webhooks" replace />}
        />
        {/* Inventory paths */}
        <Route
          path="items"
          element={<RedirectPreserving to="/inventory/items" />}
        />
        <Route
          path="items/add"
          element={<Navigate to="/inventory/items/add" replace />}
        />
        <Route path="items/:id" element={<ItemsIdRedirect />} />
        <Route
          path="categories"
          element={<Navigate to="/inventory/categories" replace />}
        />
        <Route
          path="scan"
          element={<RedirectPreserving to="/inventory/scan" />}
        />
        {/* The address a printed QR opens (see backend scan_links): one
              letter, because every byte of it is a module on the label. */}
        <Route path="s/*" element={<ShortScanRedirect />} />
        {/* Spaces paths (storages now live under /inventory) */}
        <Route
          path="storages"
          element={<Navigate to="/inventory/locations" replace />}
        />
        <Route path="storages/:id" element={<StoragesIdRedirect />} />
        {/* Labels path (now under /inventory) */}
        <Route
          path="labels"
          element={<Navigate to="/inventory/labels" replace />}
        />
        {/* Stats paths (now under /inventory/stats) */}
        <Route
          path="stats"
          element={<Navigate to="/inventory/stats" replace />}
        />
        <Route
          path="stats/inventory"
          element={<Navigate to="/inventory/stats" replace />}
        />
        <Route
          path="stats/analytics"
          element={<Navigate to="/inventory/stats/analytics" replace />}
        />
        {/* Stock takes paths (now under /inventory/stock-takes) */}
        <Route
          path="stock-takes"
          element={<Navigate to="/inventory/stock-takes" replace />}
        />
        <Route
          path="stock-takes/:id/counting"
          element={<StockTakesIdRedirect />}
        />

        {/* 404 inside AppShell */}
        <Route path="*" element={<NotFoundPage />} />
      </Route>
      {/* Unknown top-level paths → redirect to home */}
      <Route path="*" element={<Navigate to="/" replace />} />{" "}
    </>
  );
}

/**
 * The route tree as a data router's route objects.
 *
 * `errorElement` is armed only by a data router, so this is where the error
 * screen is actually wired: every top-level route is handed the
 * same `ErrorPage`, which is why the tree above carries none of its own. The
 * `.map` is the whole point of the seam — one place, one screen, no route
 * left to fail into the boundary above the router.
 */
export function createAppRoutes(
  shellModules: FrontendModule[],
  flatRoutes: ModuleRoute[],
  settingsSections: SettingsSection[],
): RouteObject[] {
  return createRoutesFromElements(
    appRouteTree(shellModules, flatRoutes, settingsSections),
  ).map((route) => ({ ...route, errorElement: <ErrorPage /> }));
}

/** Dynamic redirect for /storages/:id → /inventory/locations/:id */
function StoragesIdRedirect() {
  const { id } = useParams<{ id: string }>();
  return <Navigate to={`/inventory/locations/${id ?? ""}`} replace />;
}

/** Renders a route only while one of the modules it needs is enabled; else the 404. */
function RouteGate({
  requiresModules,
  children,
}: {
  requiresModules?: string[];
  children: ReactNode;
}) {
  const { enabledModules } = useModules();
  if (
    requiresModules &&
    !requiresModules.some((name) => enabledModules.includes(name))
  ) {
    return <NotFoundPage />;
  }
  return <>{children}</>;
}

/** Dynamic redirect for /stock-takes/:id/counting → /inventory/stock-takes/:id/counting */
function StockTakesIdRedirect() {
  const { id } = useParams<{ id: string }>();
  return (
    <Navigate to={`/inventory/stock-takes/${id ?? ""}/counting`} replace />
  );
}

/**
 * `/s/<code>` → the scanner, with the code as `?code=`. A catch-all rather
 * than `:code`, so a document number keeps its slashes (`/s/IN/2026/0001`).
 */
function ShortScanRedirect() {
  const code = useParams()["*"] ?? "";
  return (
    <Navigate
      to={
        code
          ? `/inventory/scan?code=${encodeURIComponent(code)}`
          : "/inventory/scan"
      }
      replace
    />
  );
}

/** Dynamic redirect for the legacy /items/:id → /inventory/items/{id}. */
function ItemsIdRedirect() {
  const { id } = useParams<{ id: string }>();
  return (
    <Navigate
      to={
        id ? `/inventory/items/${encodeURIComponent(id)}` : "/inventory/items"
      }
      replace
    />
  );
}

export default App;
