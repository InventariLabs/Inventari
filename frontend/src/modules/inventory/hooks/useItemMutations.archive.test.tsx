import React from "react";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { queryKeys } from "@/hooks/queries/keys";
import {
  useUpdateItemQuantity,
  useBulkUpdateItems,
  useRestoreItem,
  usePurgeItem,
} from "./useItemMutations";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const invalidatedKeys = () =>
    invalidate.mock.calls.map((call) => JSON.stringify(call[0]?.queryKey));
  return { wrapper, invalidatedKeys };
}

const item = { id: "item-1", name: "Flour", quantity: 3 };

/**
 * The quantity, bulk, restore and purge doors each send one request and
 * refresh one set of lists. A wrong URL or body is a write that silently goes
 * nowhere, and a missing invalidation is a restored product that stays in the
 * archive list (or a purged one that lingers) until a reload.
 */
describe("useItemMutations — the quantity, bulk and archive doors", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sets the quantity on the item's own endpoint and refreshes its detail", async () => {
    let body: unknown;
    server.use(
      http.patch("/api/v1/items/item-1/quantity", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ ...item, quantity: 7 });
      }),
    );
    const { wrapper, invalidatedKeys } = setup();
    const { result } = renderHook(() => useUpdateItemQuantity(), { wrapper });

    act(() => result.current.mutate({ itemId: "item-1", quantity: 7 }));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(body).toEqual({ quantity: 7 });
    expect(invalidatedKeys()).toContain(
      JSON.stringify(queryKeys.items.detail("item-1")),
    );
    expect(invalidatedKeys()).toContain(JSON.stringify(queryKeys.items.all));
  });

  it("sends a bulk edit as one PATCH and refreshes the item lists", async () => {
    let body: unknown;
    server.use(
      http.patch("/api/v1/items/bulk", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ updated: 2 });
      }),
    );
    const { wrapper, invalidatedKeys } = setup();
    const { result } = renderHook(() => useBulkUpdateItems(), { wrapper });

    act(() =>
      result.current.mutate({
        item_ids: ["a", "b"],
        category_id: "cat-1",
      } as unknown as Parameters<typeof result.current.mutate>[0]),
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(body).toEqual({ item_ids: ["a", "b"], category_id: "cat-1" });
    expect(result.current.data).toEqual({ updated: 2 });
    expect(invalidatedKeys()).toContain(JSON.stringify(queryKeys.items.all));
  });

  it("restores an archived item and refreshes the archive list", async () => {
    const restoreCalls = vi.fn();
    server.use(
      http.post("/api/v1/items/item-1/restore", () => {
        restoreCalls();
        return HttpResponse.json(item);
      }),
    );
    const { wrapper, invalidatedKeys } = setup();
    const { result } = renderHook(() => useRestoreItem(), { wrapper });

    act(() => result.current.mutate("item-1"));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(restoreCalls).toHaveBeenCalledTimes(1);
    expect(invalidatedKeys()).toContain(
      JSON.stringify(queryKeys.items.archived),
    );
  });

  it("purges with the reason as a query parameter", async () => {
    let url = "";
    server.use(
      http.delete("/api/v1/items/item-1/purge", ({ request }) => {
        url = request.url;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const { wrapper, invalidatedKeys } = setup();
    const { result } = renderHook(() => usePurgeItem(), { wrapper });

    act(() => result.current.mutate({ itemId: "item-1", reason: "duplicate" }));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(new URL(url).searchParams.get("reason")).toBe("duplicate");
    expect(invalidatedKeys()).toContain(
      JSON.stringify(queryKeys.items.archived),
    );
  });

  it("purges without a reason parameter when none is given", async () => {
    let url = "";
    server.use(
      http.delete("/api/v1/items/item-1/purge", ({ request }) => {
        url = request.url;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const { wrapper } = setup();
    const { result } = renderHook(() => usePurgeItem(), { wrapper });

    act(() => result.current.mutate({ itemId: "item-1" }));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(new URL(url).searchParams.has("reason")).toBe(false);
  });
});
