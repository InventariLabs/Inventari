import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import { initI18n } from "./i18n/config";
import { dismissToastsOnLanguageChange } from "./i18n/dismissStaleToasts";
import Root from "./Root";
import { initWebVitals } from "./utils/webVitals";
import { watchSystemTheme } from "./store/themeStore";
import { installToastDefaults } from "./lib/toastDefaults";
import { installStaleChunkRecovery } from "./lib/staleChunk";

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

  // The page's one root. This module declares no component — the tree is
  // `Root` — so the dev server never runs it again in place: a hot update
  // that reaches it reloads the page instead.
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <Root />
    </React.StrictMode>,
  );
});
