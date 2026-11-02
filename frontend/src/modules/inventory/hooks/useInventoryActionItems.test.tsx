/**
 * The row exists to take the user back to the stock take still being counted.
 * Linking to the item list instead made the one action the tile exists for
 * land on the wrong screen.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import * as React from "react";

import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { useAuthStore } from "@/store/authStore";
import { useInventoryActionItems } from "./useInventoryActionItems";

const MODULES_WITH_STOCK_TAKES = [
  "core",
  "items",
  "locations",
  "categories",
  "stock_takes",
];

function renderItems() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return renderHook(() => useInventoryActionItems(), {
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>
        <ModulesProvider>{children}</ModulesProvider>
      </QueryClientProvider>
    ),
  });
}

beforeEach(() => {
  useAuthStore.setState({ isAuthenticated: true, isLoading: false });
  server.resetHandlers();
  server.use(
    http.get("/api/v1/modules/my", () =>
      HttpResponse.json(MODULES_WITH_STOCK_TAKES),
    ),
    http.get("/api/v1/stock-takes", () =>
      HttpResponse.json({ ...onePage([]), total: 2 }),
    ),
  );
});

describe("useInventoryActionItems", () => {
  it("opens the stock takes it counts, not the item list", async () => {
    const { result } = renderItems();

    await waitFor(() => expect(result.current).toHaveLength(1));
    expect(result.current[0].linkTo).toBe(
      "/inventory/stock-takes?status=in_progress",
    );
    expect(result.current[0].count).toBe(2);
  });

  it("stays quiet when no stock take is in progress", async () => {
    let requested = 0;
    server.use(
      http.get("/api/v1/stock-takes", () => {
        requested += 1;
        return HttpResponse.json(onePage([]));
      }),
    );

    const { result } = renderItems();

    // Wait for the query to actually resolve, so the empty result reflects
    // the answer — not the loading state that precedes it.
    await waitFor(() => expect(requested).toBeGreaterThan(0));
    expect(result.current).toEqual([]);
  });

  it("asks nothing of an organization without the stock-takes module", async () => {
    let modulesAnswered = 0;
    let stockTakesRequested = 0;
    server.use(
      http.get("/api/v1/modules/my", () => {
        modulesAnswered += 1;
        return HttpResponse.json(["core", "items", "locations", "categories"]);
      }),
      http.get("/api/v1/stock-takes", () => {
        stockTakesRequested += 1;
        return HttpResponse.json(onePage([]));
      }),
    );

    const { result } = renderItems();

    // The module list has arrived and does not name stock_takes: the tile
    // has nothing to say, so the endpoint is not asked at all.
    await waitFor(() => expect(modulesAnswered).toBeGreaterThan(0));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(result.current).toEqual([]);
    expect(stockTakesRequested).toBe(0);
  });
});
