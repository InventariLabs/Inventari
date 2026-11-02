/// <reference types="vitest/config" />
import path from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Group rules rather than a name function over every module, because
        // the default capture is recursive: with dependencies pulled in, the
        // react-markdown group took React with it, and every chunk holding
        // the markdown renderer preloaded React on every screen. With the
        // capture off, a group is exactly its matched files and shared
        // dependencies follow the bundler's own splitting.
        codeSplitting: {
          includeDependenciesRecursively: false,
          groups: [
            {
              // The translations, one chunk per language: two requests
              // before the first render (the reader's language plus English
              // behind it), however many namespaces ship. A name function
              // rather than a list, because the set of languages is data in
              // src/i18n, not config.
              name: (id) => {
                const locale =
                  id.match(/i18n\/locales\/(\w+)\/[\w-]+\.json$/) ??
                  id.match(/modules\/[^/]+\/i18n\/(\w+)\.json$/);
                return locale ? `i18n-${locale[1]}` : null;
              },
            },
            {
              name: "vendor-react",
              test: /[\\/]node_modules[\\/](react|react-dom|react-router-dom|scheduler)[\\/]/,
            },
            {
              // The core with its React binding. Left to the bundler, the
              // core's files were cut by whichever screens reached them: the
              // cut tied the entry to the App tree, so a signed-out visitor
              // downloaded it, and every new lazy import re-cut them.
              name: "vendor-query",
              test: /[\\/]node_modules[\\/]@tanstack[\\/](react-query|query-core)[\\/]/,
            },
            {
              name: "vendor-ui",
              test: /[\\/]node_modules[\\/](lucide-react|react-i18next|i18next)[\\/]/,
            },
            {
              // The exact package path: the renderer is loaded by three lazy
              // recipe components alone and belongs in no other chunk.
              name: "vendor-markdown",
              test: /[\\/]node_modules[\\/]react-markdown[\\/]/,
            },
          ],
        },
      },
    },
  },
  plugins: [react()],
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    // Merges the console gate's observations after the last worker exits and
    // writes src/test/console-baseline.json — only under
    // CONSOLE_BASELINE_WRITE, i.e. `npm run test:console-baseline`.
    globalSetup: "./src/test/consoleGateGlobal.ts",
    css: true,
    testTimeout: 15000,
    hookTimeout: 10000,
    // Each test file runs in its own forked process (full isolation).
    pool: "forks",
    exclude: [
      "node_modules",
      "dist",
      ".idea",
      ".git",
      ".cache",
      "tests/e2e/**", // Exclude Playwright e2e tests from Vitest
    ],
    coverage: {
      provider: "v8",
      reporter: ["text", "json", "html"],
      reportsDirectory: "./coverage",
      // The report covers the application, and every file of it — including
      // the ones no test imports, which is the point of a floor. Vitest 4
      // dropped `coverage.all`: without `include` only files some test loaded
      // are counted, and an untested page simply leaves the denominator.
      // Anything outside src/ is not the app: the Playwright helpers under
      // tests/e2e (2879 lines of api.ts at 0%) and the one-off review_*.cjs
      // scripts used to be counted as source under the old `all: true`.
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "node_modules",
        "src/test/**",
        "src/**/*.test.{ts,tsx}",
        "src/**/*.spec.{ts,tsx}",
        "src/**/*.d.ts",
        "src/i18n/**",
        "src/types/**",
        "src/main.tsx",
        "src/App.tsx",
        "src/__mocks__/**",
        "src/components/AppShell.tsx",
        "src/components/CommandPalette.tsx",
        "src/components/SettingsShell.tsx",
        "src/components/ModuleNav.tsx",
        "src/components/PageContainer.tsx",
        "src/components/ModeStrip.tsx",
        "src/components/ContentBanner.tsx",
        "src/components/ApiKeyDialog.tsx",
        "src/components/ApiKeyModal.tsx",
        "src/components/FieldBuilderEditForm.tsx",
        // src/modules/**/pages/** and src/modules/**/components/**
        // used to be excluded here on the grounds that Playwright covers
        // them. It does, partly — but the exclusion took 433 of 740 source
        // files out of the gate, so the thresholds below only ever described
        // a third of the frontend. The targeted exclusions above stay; those
        // components really are shell-level and e2e-only.
        "coverage/**",
        "scripts/**",
        "*.config.{ts,js,cjs,mjs}",
        "**/*.d.ts",
      ],
      // Measured on the whole frontend on 2026-10-28, on commit e57dca693
      // (origin/dev 125041aca plus behaviour tests for the equipment,
      // storage, stock-take and attestation screens), under the vitest 5 +
      // coverage-v8 5 instrument, which counts statements from the AST
      // instead of per source line: statements 89.18, branches 84.25,
      // functions 87.16, lines 90.67, over 1253 source files, from 1127 test
      // files running 10702 tests. These are "do not go below" marks rounded
      // down from what the suite achieves today — not a target.
      //
      // The slack is under a percentage point per metric, which is the point:
      // the headroom the numbers before 2026-09-26 left is what let a quarter
      // of the coverage go missing without the gate noticing.
      //
      // Raising or lowering any of these four is a separate decision from
      // keeping them, and it is a ratchet: a number here may not fall without
      // an explicit commit that also replaces the measurement above and says
      // in its message what was lost and why. See AGENTS.md, the pre-push gate.
      thresholds: {
        lines: 90,
        functions: 87,
        branches: 84,
        statements: 89,
      },
    },
  },
  server: {
    port: 5173,
    host: "0.0.0.0",
    allowedHosts: true,
    proxy: {
      "/api": {
        target: process.env.VITE_BACKEND_TARGET || "http://backend:8000",
        changeOrigin: true,
        ws: true,
        rewriteWsOrigin: true,
      },
      "/uploads": {
        target: process.env.VITE_BACKEND_TARGET || "http://backend:8000",
        changeOrigin: true,
      },
      "/public": {
        target: process.env.VITE_BACKEND_TARGET || "http://backend:8000",
        changeOrigin: true,
        bypass: (req) => {
          // Browser navigation requests (Accept: text/html) should be served
          // by Vite/React — only AJAX calls (axios/fetch) go to the backend.
          if (req.headers.accept?.includes("text/html")) {
            return "/index.html";
          }
        },
      },
    },
  },
});
