import React, { Suspense, lazy } from "react";
import ReactDOM from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import { initI18n } from "./i18n/config";
import { dismissToastsOnLanguageChange } from "./i18n/dismissStaleToasts";
import { ModulesProvider } from "./contexts/ModulesContext";
import AppToaster from "./components/AppToaster";
import ErrorBoundary from "./components/ErrorBoundary";
import LoadingSpinner from "./components/LoadingSpinner";
import { initWebVitals } from "./utils/webVitals";
import { queryClient } from "./lib/queryClient";
import { watchSystemTheme } from "./store/themeStore";
import { isPublicPath } from "./publicRoutes";
import { installToastDefaults } from "./lib/toastDefaults";
import { installStaleChunkRecovery } from "./lib/staleChunk";

// Two trees, and the choice is made here rather than by the router, because it
// decides what gets downloaded. The public attestation page used to live inside
// `App`, which opened by loading every module.ts up front back then, so a
// visitor with no account was handed the whole application. Both are lazy so
// the bundler can keep them apart.
const App = lazy(() => import("./App"));
const PublicApp = lazy(() => import("./PublicApp"));

const isPublic = isPublicPath(window.location.pathname);

// Clean up old Service Workers (since PWA is currently disabled)
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.getRegistrations().then((registrations) => {
    for (const registration of registrations) {
      registration.unregister();
    }
  });
}

initWebVitals();

// A deploy renames every hashed chunk; a tab that still holds the old names
// reloads once instead of showing the reader a TypeError.
installStaleChunkRecovery();

// An error stays on screen as long as it takes to read it. Installed here
// rather than at every call site, because it is a rule about the kind of
// message, not about any one of them.
installToastDefaults();

// Keeps the interface in step with `prefers-color-scheme` while the theme is
// left on "system" — the default.
watchSystemTheme();

// The translations arrive as chunks of their own now — one language instead
// of five — so the first render waits for them: rendering before they land is
// a screen of raw keys. A `.then` rather than a top-level await, which the
// browsers this builds for do not all have.
void initI18n().then(() => {
  dismissToastsOnLanguageChange();

  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
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
    </React.StrictMode>,
  );
});
