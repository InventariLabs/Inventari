import { Suspense, lazy } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { ModulesProvider } from "./contexts/ModulesContext";
import AppToaster from "./components/AppToaster";
import ErrorBoundary from "./components/ErrorBoundary";
import LoadingSpinner from "./components/LoadingSpinner";
import { queryClient } from "./lib/queryClient";
import { isPublicPath } from "./publicRoutes";

// Two trees, and the choice is made here rather than by the router, because it
// decides what gets downloaded. The public attestation page used to live inside
// `App`, which opened by loading every module.ts up front back then, so a
// visitor with no account was handed the whole application. Both are lazy so
// the bundler can keep them apart.
const App = lazy(() => import("./App"));
const PublicApp = lazy(() => import("./PublicApp"));

const isPublic = isPublicPath(window.location.pathname);

/**
 * Everything the page draws, under the root `main.tsx` creates.
 *
 * It is a component of its own, not JSX inline in `main.tsx`, because of the
 * dev server: a module that declares a component — the two lazy trees above
 * count — accepts its own hot updates, and accepting means being run again.
 * Run again here, that re-renders this tree in place. Run again in
 * `main.tsx`, it created a second root on the same container, and the two
 * trees tore the page apart while a module was being installed.
 */
export default function Root() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        {/* No router here: each tree mounts its own *data* router, which is
          the only kind that arms a route's `errorElement`. The choice above
          stays a plain conditional so neither tree is imported for the
          other's visitor. */}
        <Suspense fallback={<LoadingSpinner fullScreen />}>
          {isPublic ? (
            <PublicApp />
          ) : (
            <ModulesProvider>
              <App />
            </ModulesProvider>
          )}
        </Suspense>
        {/* Both trees report failures this way — the attestation page's
          confirm and dispute are mutations like any other. */}
        <AppToaster />
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
