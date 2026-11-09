import * as React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { useAuthStore } from "@/store/authStore";
import { signInWith } from "@/test/auth";
import { useHiddenItemCount } from "./useItems";
import { useInventoryActionItems } from "./useInventoryActionItems";
import { useStorageLocationLabels } from "@/modules/shared/hooks/useStorageLocationLabels";

/**
 * Three hooks that derive a number, a tile or a name from a request. When the
 * request fails they have nothing to say, and say exactly that: no hidden
 * count, the name the row came with — and, for the launcher, a tile that says
 * the stock takes could not be read, since no tile at all would look like
 * "nothing in progress".
 */
function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={client}>
      <ModulesProvider>
        <MemoryRouter>{children}</MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
}

const fail = (path: string) =>
  http.get(path, () => HttpResponse.json({ detail: "boom" }, { status: 500 }));

beforeEach(() => {
  useAuthStore.setState({ isAuthenticated: true, isLoading: false });
  server.resetHandlers();
  server.use(
    http.get("/api/v1/modules/my", () =>
      HttpResponse.json([
        "core",
        "items",
        "locations",
        "categories",
        "stock_takes",
      ]),
    ),
  );
});

describe("useHiddenItemCount — the probe failed", () => {
  it("reports nothing hidden rather than a count it does not have", async () => {
    server.use(fail("/api/v1/items"));
    const { result } = renderHook(
      () => useHiddenItemCount(true, false, 3, false),
      {
        wrapper,
      },
    );

    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(result.current).toBe(0);
  });

  it("counts the difference when the probe answers", async () => {
    server.use(
      http.get("/api/v1/items", () =>
        HttpResponse.json({ items: [], total: 10, offset: 0, limit: 1 }),
      ),
    );
    const { result } = renderHook(
      () => useHiddenItemCount(true, false, 3, false),
      {
        wrapper,
      },
    );

    await waitFor(() => expect(result.current).toBe(7));
  });

  it("steps aside when either count stopped at the cap", async () => {
    // Both lists stopped counting at ten thousand: their difference says
    // nothing about what the module filter hides.
    let answered = false;
    server.use(
      http.get("/api/v1/items", () => {
        answered = true;
        return HttpResponse.json({
          items: [],
          total: 10000,
          total_capped: true,
          offset: 0,
          limit: 1,
        });
      }),
    );
    const { result } = renderHook(
      () => useHiddenItemCount(true, false, 9000, false),
      { wrapper },
    );

    await waitFor(() => expect(answered).toBe(true));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(result.current).toBe(0);
  });
});

describe("useInventoryActionItems — the stock takes request failed", () => {
  it("says the stock takes could not be read instead of claiming none are in progress", async () => {
    // A role that may read them: for one that may not, nothing is asked.
    signInWith(["stock_takes:read"]);
    server.use(fail("/api/v1/stock-takes"));
    const { result } = renderHook(() => useInventoryActionItems(), { wrapper });

    // The hook retries once before it gives up, one second apart.
    await waitFor(() => expect(result.current).toHaveLength(1), {
      timeout: 5000,
    });
    expect(result.current[0]).toMatchObject({
      id: "inventory-stock-takes-unavailable",
      severity: "error",
      linkTo: "/inventory/stock-takes",
    });
    expect(result.current[0].count).toBeUndefined();
  });
});

describe("useStorageLocationLabels — the locations request failed", () => {
  it("keeps the name the row came with", async () => {
    server.use(fail("/api/v1/locations"));
    const { result } = renderHook(() => useStorageLocationLabels(["loc-1"]), {
      wrapper,
    });

    await waitFor(() =>
      expect(result.current("loc-1", "Shelf 1")).toBe("Shelf 1"),
    );
    expect(result.current("loc-1", null)).toBeNull();
  });
});
