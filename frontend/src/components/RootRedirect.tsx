import { Suspense, lazy } from "react";
import { Navigate } from "react-router-dom";
import { useModules } from "@/contexts/ModulesContext";
import { moduleRegistry, resolveModuleTarget } from "@/lib/moduleRegistry";
import { FocusLockGate } from "@/components/FocusLockGate";
import LoadingSpinner from "@/components/LoadingSpinner";

const LauncherPage = lazy(
  () => import("@/modules/launcher/components/Launcher"),
);

/**
 * The Launcher tile grid, always rendered — used both as the RootRedirect
 * fallback and directly at `/launcher`, the stable URL that keeps the
 * Launcher reachable when the root redirects to the focused module.
 */
export function LauncherRoute() {
  return (
    <Suspense fallback={<LoadingSpinner fullScreen />}>
      <FocusLockGate>
        <LauncherPage />
      </FocusLockGate>
    </Suspense>
  );
}

/**
 * Root index redirect.
 *
 * In single-module focus mode `/` navigates straight to the focused module —
 * the grid is not the home of an organization that narrowed itself to one
 * module. Otherwise the Launcher is the home, whatever the profile: a profile
 * colours the app, it does not choose where it opens. The Launcher remains
 * reachable at `/launcher`.
 */
export function RootRedirect() {
  const { enabledModules, focusModule, focusStatus } = useModules();

  // The Launcher must not flash in front of a focus the server has not yet
  // answered about: wait for the answer rather than start on the wrong screen.
  if (focusStatus === "loading") return <LoadingSpinner fullScreen />;

  // Guarded against looping: this component owns `/`, so a target that
  // resolves back to `/` is treated as no redirect. A module missing from
  // the enabled list has no registered routes either — fall through.
  if (focusModule && enabledModules.includes(focusModule)) {
    const focused = moduleRegistry.getModule(focusModule);
    const target = focused ? resolveModuleTarget(focused) : null;
    if (target && target !== "/") {
      return <Navigate to={target} replace />;
    }
  }
  return <LauncherRoute />;
}
