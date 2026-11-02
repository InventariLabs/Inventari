import React from "react";
import { act, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { ModulesProvider } from "@/contexts/ModulesContext";
import InventoryDashboard from "../pages/InventoryDashboard";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter>{children}</MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
};

const zone = (id: string, name: string, contextTag?: string) => ({
  id,
  name,
  parent_id: null,
  usage: "internal",
  location_type_id: null,
  items_count: 0,
  subtree_items_count: 0,
  short_code: name.slice(0, 3).toUpperCase(),
  context_tag: contextTag ?? null,
  children: [],
});

/**
 * "My storage places" and the Storages tab are the same question asked twice.
 * The overview read the full tree while the tab read the scoped one, so one
 * organization showed six places on one screen and four on the next.
 */
describe("the storage tiles and the Storages tab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const treeRequests: URLSearchParams[] = [];

  function serveTree(showModuleData: boolean) {
    treeRequests.length = 0;
    server.use(
      http.get("*/stock-moves", () =>
        HttpResponse.json({
          items: [],
          total: 0,
          offset: 0,
          limit: 5,
          has_more: false,
        }),
      ),
      http.get("*/organizations/my", () =>
        HttpResponse.json({
          id: "org-1",
          name: "Test Org",
          currency: "PLN",
          settings: showModuleData ? { show_module_data: true } : {},
        }),
      ),
      http.get("*/locations/tree", ({ request }) => {
        const url = new URL(request.url);
        treeRequests.push(url.searchParams);
        const scoped =
          url.searchParams.get("exclude_module_contexts") === "true";
        return HttpResponse.json(
          scoped
            ? [zone("z1", "Cold Storage"), zone("z2", "Receiving")]
            : [
                zone("z1", "Cold Storage"),
                zone("z2", "Receiving"),
                zone("z3", "IT Workshop", "equipment"),
              ],
        );
      }),
    );
  }

  it("shows the places the Storages tab shows, not one more", async () => {
    serveTree(false);

    render(<InventoryDashboard />, { wrapper: createWrapper() });

    expect(await screen.findByText("Cold Storage")).toBeInTheDocument();
    expect(screen.getByText("Receiving")).toBeInTheDocument();
    expect(screen.queryByText("IT Workshop")).toBeNull();
    // The dashboard's suspended queries settle after the assertions; flush
    // them inside act so they are not picked up during teardown.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 100));
    });
  });

  it("reads the two levels the cards are made of, never the whole tree", async () => {
    serveTree(false);

    render(<InventoryDashboard />, { wrapper: createWrapper() });

    await screen.findByText("Cold Storage");
    // A warehouse of two thousand shelves answers a tree of 700 KB; the
    // cards are the places directly under each top-level place.
    expect(treeRequests.length).toBeGreaterThan(0);
    expect(treeRequests.every((q) => q.get("depth") === "2")).toBe(true);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 100));
    });
  });

  it("shows the module's places once the organization opts in", async () => {
    serveTree(true);

    render(<InventoryDashboard />, { wrapper: createWrapper() });

    expect(await screen.findByText("IT Workshop")).toBeInTheDocument();
    await act(async () => {
      await new Promise((r) => setTimeout(r, 100));
    });
  });
});
