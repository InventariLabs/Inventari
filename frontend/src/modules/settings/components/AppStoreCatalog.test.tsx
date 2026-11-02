import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import AppStore from "./AppStore";
import { server } from "@/test/mocks/server";
import { tFor } from "@/test/mocks/i18n";
import * as modulesCtx from "@/contexts/ModulesContext";
import type { ModuleCategory } from "@/types";
import { onePage } from "@/test/mocks/page";

/**
 * Every module the backend offers is visible in the store under the default
 * filter — no module needs the right tab guessed to be found.
 *
 * The list is not written here: scripts/check-module-catalog.mjs carries the
 * backend's module directories into a snapshot, so a module added there fails
 * this without anybody editing it. The store itself is not consulted about
 * what exists — it answers the API, and the API is what this feeds it.
 */
const CATALOG: string[] = JSON.parse(
  readFileSync(join(process.cwd(), "scripts", "module-catalog.json"), "utf8"),
);

// Spread across the taxonomy on purpose: a filter that drops a whole bucket
// while claiming to show everything is exactly the failure being guarded.
const CATEGORIES: ModuleCategory[] = [
  "core",
  "business",
  "analytics",
  "integrations",
  "system",
  "other",
];

const catalogResponse = CATALOG.map((name, index) => ({
  name,
  display_name: name,
  description: `The ${name} module.`,
  icon: "box",
  category: CATEGORIES[index % CATEGORIES.length],
  requires: [],
  version: "0.1.0",
  requires_api_key: false,
}));

const mockAuthState = {
  user: { role: "admin", is_superuser: false },
  isAuthenticated: true,
  isLoading: false,
};

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector?: (s: typeof mockAuthState) => unknown) =>
    selector ? selector(mockAuthState) : mockAuthState,
}));

const Wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider
    client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
  >
    <BrowserRouter>{children}</BrowserRouter>
  </QueryClientProvider>
);

/** The name the store shows — the same lookup `useModuleLabels` performs. */
const labelOf = (name: string) =>
  tFor("modules")(`modules.${name}.name`, { defaultValue: name });

describe("AppStore shows every module the backend offers", () => {
  beforeEach(() => {
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: [],
      isModuleEnabled: () => false,
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
    server.use(
      http.get("/api/v1/modules/available", () =>
        HttpResponse.json(onePage(catalogResponse)),
      ),
    );
  });

  it("the catalog is not empty (the gate is not vacuous)", () => {
    // An empty snapshot would make the assertion below describe an empty world.
    expect(CATALOG.length).toBeGreaterThan(10);
    expect(CATALOG).toContain("recipes");
  });

  it("renders a tile for each of them", async () => {
    render(<AppStore />, { wrapper: Wrapper });

    // The grid, not the whole page: the filter sidebar and the header carry
    // module-shaped text of their own.
    const first = await screen.findByText(labelOf(CATALOG[0]));
    const grid = first.closest(".grid");
    expect(grid).not.toBeNull();

    const missing = CATALOG.filter(
      (name) =>
        within(grid as HTMLElement).queryAllByText(labelOf(name)).length === 0,
    );
    expect(
      missing,
      `the store hides ${missing.length} module(s) the API offers: ${missing.join(", ")}`,
    ).toEqual([]);
  });
});
