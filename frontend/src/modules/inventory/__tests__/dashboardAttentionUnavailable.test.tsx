import React from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { ModulesProvider } from "@/contexts/ModulesContext";
import InventoryDashboard from "../pages/InventoryDashboard";
// The replenish door is the shopping lists' contribution to the dashboard;
// registering the module puts it on the screen as the app does.
import "@/modules/shopping_lists/module";

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

async function settle() {
  // The failed queries' retry transitions settle after the assertions;
  // this flushes them inside act instead of after the test.
  await act(async () => {
    await new Promise((r) => setTimeout(r, 100));
  });
}

/**
 * The overview exists to answer "is anything happening". A missing answer
 * read as "nothing" once told a reader all was well over eight products
 * below their threshold; the attention card inherited that invariant from
 * the tiles it replaced.
 */
describe("the overview when what needs attention does not arrive", () => {
  let attentionRequests = 0;

  beforeEach(() => {
    attentionRequests = 0;
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
      http.get("/api/v1/items", ({ request }) => {
        const p = new URL(request.url).searchParams;
        if (p.get("limit") === "1") {
          return HttpResponse.json({
            items: [],
            total: 88,
            offset: 0,
            limit: 1,
            has_more: true,
          });
        }
        attentionRequests += 1;
        return new HttpResponse(null, { status: 500 });
      }),
    );
  });

  it("says so, out loud, with a way to ask again", async () => {
    render(<InventoryDashboard />, { wrapper: createWrapper() });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/could not be loaded/i);
    const before = attentionRequests;
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(attentionRequests).toBeGreaterThan(before);
    await settle();
  });

  it("never reads the failure as all clear", async () => {
    render(<InventoryDashboard />, { wrapper: createWrapper() });

    await screen.findByRole("alert");
    expect(screen.queryByText(/all under control/i)).toBeNull();
    await settle();
  });

  it("shows no products count where everything it counts from failed", async () => {
    server.use(
      http.get("/api/v1/items", () => new HttpResponse(null, { status: 500 })),
      http.get(
        "*/locations/tree",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    render(<InventoryDashboard />, { wrapper: createWrapper() });

    // The attention card and the storages card each say so.
    expect((await screen.findAllByRole("alert")).length).toBeGreaterThan(0);
    expect(screen.queryByText(/\b0 records\b/)).toBeNull();
    expect(screen.queryByText(/\bin 0 places\b/)).toBeNull();
    await settle();
  });
});

describe("the overview's storages card when the storages did not arrive", () => {
  it("says so with a retry instead of inviting the reader to add the first storage", async () => {
    let treeRequests = 0;
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
      http.get("*/locations/tree", () => {
        treeRequests += 1;
        return new HttpResponse(null, { status: 500 });
      }),
    );

    render(<InventoryDashboard />, { wrapper: createWrapper() });

    const retry = await screen.findAllByRole("button", { name: /try again/i });
    expect(screen.queryByText(/add your first storage/i)).toBeNull();
    const before = treeRequests;
    await userEvent.click(retry[retry.length - 1]);
    await vi.waitFor(() => expect(treeRequests).toBeGreaterThan(before));
    await settle();
  });
});

describe("the overview's replenish door when the suggestions did not arrive", () => {
  it("offers a retry instead of making the door vanish", async () => {
    let asked = 0;
    server.use(
      http.get("/api/v1/modules/my", () =>
        HttpResponse.json([
          "core",
          "items",
          "locations",
          "categories",
          "shopping_lists",
        ]),
      ),
      http.get("*/stock-moves", () =>
        HttpResponse.json({
          items: [],
          total: 0,
          offset: 0,
          limit: 5,
          has_more: false,
        }),
      ),
      http.get("*/shopping-lists/suggestions", () => {
        asked += 1;
        return new HttpResponse(null, { status: 500 });
      }),
    );

    render(<InventoryDashboard />, { wrapper: createWrapper() });

    await settle();
    expect(asked).toBeGreaterThan(0);
    const before = asked;
    const retries = await screen.findAllByRole("button", {
      name: /try again/i,
    });
    // The attention card's retry also asks again; the door's is one of them.
    for (const retry of retries) await userEvent.click(retry);
    await settle();
    expect(asked).toBeGreaterThan(before);
  });
});
