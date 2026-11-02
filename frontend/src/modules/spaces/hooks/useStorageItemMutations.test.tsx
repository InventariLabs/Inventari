import React from "react";
import { renderHook, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { queryKeys } from "@/hooks/queries/keys";
import { server } from "@/test/mocks/server";
import {
  useConsumeItemFromStorage,
  useDeleteItemFromStorage,
} from "./useStorageItemMutations";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

/**
 * The caches a location's product writes mark stale. The requests they send
 * are pinned in shared/hooks/useStorageMutations.test.tsx; here, a write that
 * leaves the location's product list cached as it was (the row stays on
 * screen after the reader removed it) or keeps the archive stale fails.
 */
describe("location product writes refresh what they changed", () => {
  function clientAndWrapper() {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    return { invalidate, wrapper };
  }

  it("a removal refreshes the archive and the location's list", async () => {
    server.use(
      http.delete(
        "/api/v1/items/item-1",
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
    const { invalidate, wrapper } = clientAndWrapper();
    const { result } = renderHook(() => useDeleteItemFromStorage("loc-1"), {
      wrapper,
    });

    await act(() =>
      result.current.mutateAsync({
        itemId: "item-1",
        reason: "DAMAGED",
        notes: "dropped",
      }),
    );
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: queryKeys.items.archived,
    });
    expect(invalidate).toHaveBeenCalledWith(
      expect.objectContaining({
        queryKey: queryKeys.items.storageItems("loc-1"),
      }),
    );
  });

  it("a consume refreshes the location's list", async () => {
    server.use(
      http.patch("/api/v1/items/item-1/consume", () =>
        HttpResponse.json({ id: "item-1", quantity: "2" }),
      ),
    );
    const { invalidate, wrapper } = clientAndWrapper();
    const { result } = renderHook(() => useConsumeItemFromStorage("loc-1"), {
      wrapper,
    });

    await act(() => result.current.mutateAsync({ itemId: "item-1" }));
    expect(invalidate).toHaveBeenCalledWith(
      expect.objectContaining({
        queryKey: queryKeys.items.storageItems("loc-1"),
      }),
    );
  });
});
