import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { recordRequests } from "@/test/requestLog";
import { onePage } from "@/test/mocks/page";
import { queryKeys } from "@/hooks/queries/keys";
import {
  useAddShoppingItemsToAList,
  useClearPurchasedItems,
  useConvertToPO,
  useDeleteShoppingItem,
  useDeleteShoppingList,
  useShoppingListDetail,
  useShoppingListStats,
  useShoppingSuggestionsPreview,
  useToggleShoppingItem,
  useUpdateShoppingList,
} from "./useShoppingLists";
import type { ShoppingList } from "@/modules/shopping_lists/types/shopping";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const modules = vi.hoisted(() => ({ enabled: true }));
vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    isLoading: false,
    isModuleEnabled: () => modules.enabled,
  }),
}));

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
);

beforeEach(() => {
  modules.enabled = true;
  client = new QueryClient();
});

/**
 * Ticking an item off, clearing the bought ones and turning a list into a
 * purchase order each go to their own endpoint; the wrong one buys, or
 * un-buys, the wrong thing.
 */
describe("shopping list writes", () => {
  type Case = [
    string,
    () => { mutateAsync: (vars: never) => Promise<unknown> },
    unknown,
    { method: string; path: string; body?: unknown },
  ];
  const cases: Case[] = [
    [
      "useDeleteShoppingList",
      useDeleteShoppingList,
      "l1",
      { method: "DELETE", path: "/shopping-lists/l1" },
    ],
    [
      "useUpdateShoppingList",
      useUpdateShoppingList,
      { id: "l1", name: "Party" },
      { method: "PUT", path: "/shopping-lists/l1", body: { name: "Party" } },
    ],
    [
      "useToggleShoppingItem marks an open item bought",
      () => useToggleShoppingItem("l1"),
      { itemId: "i1", currentStatus: false },
      { method: "PATCH", path: "/shopping-lists/l1/items/i1/purchase" },
    ],
    [
      "useToggleShoppingItem takes a bought item back",
      () => useToggleShoppingItem("l1"),
      { itemId: "i1", currentStatus: true },
      { method: "PATCH", path: "/shopping-lists/l1/items/i1/unpurchase" },
    ],
    [
      "useClearPurchasedItems",
      () => useClearPurchasedItems("l1"),
      undefined,
      { method: "DELETE", path: "/shopping-lists/l1/items/purchased" },
    ],
    [
      "useDeleteShoppingItem",
      () => useDeleteShoppingItem("l1"),
      "i1",
      { method: "DELETE", path: "/shopping-lists/l1/items/i1" },
    ],
    [
      "useAddShoppingItemsToAList",
      useAddShoppingItemsToAList,
      { listId: "l1", items: [{ name: "milk" }] },
      { method: "POST", path: "/shopping-lists/l1/items/bulk" },
    ],
    [
      "useConvertToPO with a supplier",
      () => useConvertToPO("l1"),
      "s1",
      {
        method: "POST",
        path: "/shopping-lists/l1/convert-to-po",
        body: { supplier_id: "s1" },
      },
    ],
    [
      "useConvertToPO without one",
      () => useConvertToPO("l1"),
      undefined,
      {
        method: "POST",
        path: "/shopping-lists/l1/convert-to-po",
        body: { supplier_id: null },
      },
    ],
  ];

  it.each(cases)(
    "%s sends the request its button promised",
    async (_n, hook, vars, expected) => {
      const log = recordRequests(() => ({}));
      const { result } = renderHook(hook, { wrapper });
      await act(() => result.current.mutateAsync(vars as never));
      expect(log).toHaveLength(1);
      expect(log[0]).toMatchObject(expected);
    },
  );

  it("refreshes the lists after an item is ticked", async () => {
    recordRequests(() => ({}));
    client.setQueryDefaults(queryKeys.shoppingLists.all, { gcTime: Infinity });
    client.setQueryData(queryKeys.shoppingLists.all, []);
    const { result } = renderHook(() => useToggleShoppingItem("l1"), {
      wrapper,
    });
    await act(() =>
      result.current.mutateAsync({ itemId: "i1", currentStatus: false }),
    );
    expect(
      client.getQueryState(queryKeys.shoppingLists.all)?.isInvalidated,
    ).toBe(true);
  });
});

describe("shopping list reads", () => {
  it("reads one list by id, and nothing when none is named", async () => {
    const log = recordRequests(() => ({ id: "l1", items: [] }));
    const idle = renderHook(() => useShoppingListDetail(undefined), {
      wrapper,
    });
    renderHook(() => useShoppingListDetail("l1"), { wrapper });
    await waitFor(() => expect(log).toHaveLength(1));
    expect(log[0]).toMatchObject({ method: "GET", path: "/shopping-lists/l1" });
    expect(idle.result.current.fetchStatus).toBe("idle");
  });

  it("previews the suggestions for the chosen sources only while enabled", async () => {
    const log = recordRequests(() => ({ items: [] }));
    const off = renderHook(() => useShoppingSuggestionsPreview(false), {
      wrapper,
    });
    expect(off.result.current.fetchStatus).toBe("idle");
    renderHook(
      () => useShoppingSuggestionsPreview(true, { include_low_stock: true }),
      { wrapper },
    );
    await waitFor(() => expect(log).toHaveLength(1));
    expect(log[0]).toMatchObject({
      method: "GET",
      path: "/shopping-lists/suggestions",
      query: { include_low_stock: "true" },
    });
  });
});

describe("useShoppingListStats", () => {
  const lists = [{ id: "l1" }, { id: "l2" }] as ShoppingList[];
  const item = (name: string, bought: boolean) => ({
    name,
    is_purchased: bought,
  });

  it("counts each list's items and names the first three on its card", async () => {
    recordRequests((req) =>
      req.path === "/shopping-lists/l1"
        ? {
            id: "l1",
            items: [
              item("a", true),
              item("b", false),
              item("c", false),
              item("d", true),
            ],
          }
        : { id: "l2", items: [] },
    );
    const { result } = renderHook(() => useShoppingListStats(lists), {
      wrapper,
    });
    await waitFor(() => expect(Object.keys(result.current)).toHaveLength(2));
    expect(result.current.l1).toEqual({
      total: 4,
      purchased: 2,
      names: ["a", "b", "c"],
    });
    expect(result.current.l2).toEqual({ total: 0, purchased: 0, names: [] });
  });

  it("asks nothing when the module is off", async () => {
    modules.enabled = false;
    const log = recordRequests(() => onePage([]));
    const { result } = renderHook(() => useShoppingListStats(lists), {
      wrapper,
    });
    await new Promise((r) => setTimeout(r, 20));
    expect(result.current).toEqual({});
    expect(log).toHaveLength(0);
  });
});
