import React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { signInWith, signOut } from "@/test/auth";
import { itemsApi } from "@/lib/api/items";
import type { Item } from "@/types";
import { useItemQuickActions } from "./useItemQuickActions";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/api/items", () => ({
  itemsApi: {
    consume: vi.fn(),
  },
}));

function kgItem(overrides: Partial<Item> = {}): Item {
  return {
    id: "item-1",
    location_id: "storage-1",
    category_id: null,
    name: "Beef",
    brand: null,
    description: null,
    weight: null,
    uom_id: "uom-kg",
    uom: {
      rounding: "1",
      id: "uom-kg",
      symbol: "kg",
      name: "Kilograms",
      category_name: "WEIGHT",
    },
    quantity: "2",
    added_date: "2026-09-01T00:00:00Z",
    expiry_date: null,
    freeze_date: null,
    shelf_location: null,
    image_url: null,
    metadata: null,
    is_deleted: false,
    deleted_at: null,
    deletion_reason: null,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    barcode: undefined,
    serial_number: null,
    ...overrides,
  };
}

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider
    client={
      new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      })
    }
  >
    {children}
  </QueryClientProvider>
);

describe("useItemQuickActions", () => {
  beforeEach(() => {
    signInWith(["items:read", "items:write"]);
    vi.mocked(itemsApi.consume).mockResolvedValue(
      kgItem({ quantity: "1", is_deleted: false }),
    );
  });

  afterEach(() => {
    signOut();
  });

  /**
   * The button says "Remove 1 unit" and the record holds 2 kg. It used to
   * consume the whole record for units measured by weight or volume: a reader
   * who asked for one kilogram lost two, and the "Add 1 unit" beside it adds
   * exactly one. Reverting the fix makes this test expect 2 and fail.
   */
  it("takes one unit — not the whole record — when the label promises one unit", async () => {
    const onDone = vi.fn();
    const { result } = renderHook(
      () => useItemQuickActions(kgItem(), { onDone, onMove: vi.fn() }),
      { wrapper },
    );

    const consume = result.current.actions.find(
      (action) => action.id === "consume",
    );
    expect(consume).toBeDefined();

    act(() => consume!.onClick());

    await waitFor(() => {
      expect(itemsApi.consume).toHaveBeenCalledWith(
        "item-1",
        1,
        "USED",
        undefined,
      );
    });
    expect(onDone).toHaveBeenCalled();
  });
});
