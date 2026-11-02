import { describe, it, expect, vi } from "vitest";
import { createElement, type ReactNode } from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Item, StorageLocationNode } from "@/types";
import {
  buildStorageComposition,
  groupAttention,
  mergeAttention,
  useDashboardAttention,
} from "@/modules/inventory/hooks/useDashboardAttention";
import { useItems } from "@/modules/inventory/hooks/useItems";
import { itemsApi } from "@/lib/api/items";
import { useAttentionCounts } from "@/modules/shared/hooks/useAttentionCounts";

vi.mock("@/modules/inventory/hooks/useItems", () => ({
  useItems: vi.fn(),
}));

vi.mock("@/lib/api/items", () => ({
  itemsApi: { getLowStockProducts: vi.fn().mockResolvedValue([]) },
}));

function withClient({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return createElement(QueryClientProvider, { client }, children);
}

// `attentionCount` stays real — it is the shape of the answer under test,
// not a boundary.
vi.mock("@/modules/shared/hooks/useAttentionCounts", async (importOriginal) => {
  const actual =
    await importOriginal<
      typeof import("@/modules/shared/hooks/useAttentionCounts")
    >();
  return { ...actual, useAttentionCounts: vi.fn() };
});

function node(
  id: string,
  subtree: number,
  children: StorageLocationNode[] = [],
): StorageLocationNode {
  return {
    id,
    name: id,
    parent_id: null,
    usage: "internal",
    location_type_id: null,
    short_code: null,
    context_tag: null,
    items_count:
      subtree - children.reduce((s, c) => s + c.subtree_items_count, 0),
    subtree_items_count: subtree,
    children_count: 0,
    children,
  };
}

function item(id: string, location: string, template = `t-${id}`): Item {
  return {
    id,
    name: `Item ${id}`,
    quantity: "1",
    is_deleted: false,
    location_id: location,
    template_id: template,
  } as Item;
}

describe("mergeAttention", () => {
  it("counts a record that is both expiring and short once, as expiring", () => {
    const yoghurt = item("yoghurt", "fridge");
    const merged = mergeAttention({
      expired: [],
      expiring: [yoghurt],
      low: [yoghurt, item("peas", "freezer")],
    });
    expect(merged.map((r) => [r.item.id, r.kind])).toEqual([
      ["yoghurt", "expiring"],
      ["peas", "low"],
    ]);
  });

  it("lets expired outrank everything else", () => {
    const milk = item("milk", "fridge");
    const merged = mergeAttention({
      expired: [milk],
      expiring: [milk],
      low: [milk],
    });
    expect(merged).toHaveLength(1);
    expect(merged[0].kind).toBe("expired");
  });
});

describe("groupAttention", () => {
  it("leaves short stock to the products list, which has a row per product", () => {
    // A threshold belongs to the product, and a product used up has no
    // shelf record to group: its row comes from the products list.
    const groups = groupAttention([
      { item: item("peas-a", "freezer", "peas"), kind: "low" },
      { item: item("peas-b", "basement", "peas"), kind: "low" },
      { item: item("milk", "fridge"), kind: "expired" },
    ]);
    expect(groups.map((g) => [g.kind, g.items.map((i) => i.id)])).toEqual([
      ["expired", ["milk"]],
    ]);
  });

  it("keeps expiring records apart even when they share a product", () => {
    const groups = groupAttention([
      { item: item("yog-a", "fridge", "yog"), kind: "expiring" },
      { item: item("yog-b", "fridge", "yog"), kind: "expiring" },
    ]);
    expect(groups).toHaveLength(2);
  });
});

describe("buildStorageComposition", () => {
  const fridge = node("fridge", 24, [node("fridge-door", 4)]);
  const freezer = node("freezer", 52, [
    node("drawer", 30, [node("drawer-top", 10)]),
  ]);
  const empty = node("closet", 0);

  it("rolls nested locations up to the zone that holds them", () => {
    const comp = buildStorageComposition(
      [fridge, freezer],
      mergeAttention({
        expired: [item("milk", "fridge-door")],
        expiring: [item("yog", "fridge")],
        low: [item("peas", "drawer-top")],
      }),
    );
    expect(comp).toEqual([
      {
        zoneId: "fridge",
        count: 24,
        segments: { bad: 1, warn: 1, low: 0, ok: 22 },
      },
      {
        zoneId: "freezer",
        count: 52,
        segments: { bad: 0, warn: 0, low: 1, ok: 51 },
      },
    ]);
  });

  it("places a record deeper than the levels loaded by climbing the places above it", () => {
    // The overview reads two levels of the tree; a shelf three levels down is
    // known only by the chain of places above it, read by id.
    const comp = buildStorageComposition(
      [node("fridge", 24)],
      mergeAttention({
        expired: [item("milk", "shelf-3")],
        expiring: [],
        low: [],
      }),
      new Map([
        ["shelf-3", "rack-2"],
        ["rack-2", "fridge"],
        ["fridge", "site"],
        ["site", null],
      ]),
    );
    expect(comp[0].segments).toEqual({ bad: 1, warn: 0, low: 0, ok: 23 });
  });

  it("does not loop on a chain that closes on itself", () => {
    const comp = buildStorageComposition(
      [node("fridge", 2)],
      mergeAttention({
        expired: [item("milk", "a")],
        expiring: [],
        low: [],
      }),
      new Map([
        ["a", "b"],
        ["b", "a"],
      ]),
    );
    expect(comp[0].segments).toEqual({ bad: 0, warn: 0, low: 0, ok: 2 });
  });

  it("gives an empty zone an empty composition", () => {
    const [comp] = buildStorageComposition([empty], []);
    expect(comp).toEqual({
      zoneId: "closet",
      count: 0,
      segments: { bad: 0, warn: 0, low: 0, ok: 0 },
    });
  });

  it("ignores records outside the tree (locations a module owns)", () => {
    const [comp] = buildStorageComposition(
      [fridge],
      mergeAttention({
        expired: [item("asset", "module-owned-room")],
        expiring: [],
        low: [],
      }),
    );
    expect(comp.segments).toEqual({ bad: 0, warn: 0, low: 0, ok: 24 });
  });

  it("never lets the neutral mass go below zero", () => {
    // The lists are capped and the tree counts separately; a zone whose
    // count lags behind its anomalies must not draw a negative segment.
    const [comp] = buildStorageComposition(
      [node("shelf", 1)],
      mergeAttention({
        expired: [item("a", "shelf"), item("b", "shelf")],
        expiring: [],
        low: [],
      }),
    );
    expect(comp.segments.ok).toBe(0);
  });
});

function listResult(total: number, items: Item[] = []) {
  return { total, items } as unknown as ReturnType<typeof useItems>["data"];
}

const query = (data: ReturnType<typeof listResult>) =>
  ({ data }) as unknown as ReturnType<typeof useItems>;

describe("useDashboardAttention count", () => {
  it("reads the heading's number from the one count both screens share", () => {
    // The lists still feed the rows, and one of them is a page of a hundred
    // and fifty records of a single short product: a count derived from
    // them would undercount the low share and double the expiry totals the
    // statistics screen shows. The heading reads the endpoint instead.
    vi.mocked(useItems).mockImplementation((params) => {
      if (params?.only_expired) return query(listResult(9));
      if (params?.expiring_days) return query(listResult(8));
      if (params?.only_low_stock)
        return query(
          listResult(150, [
            item("a", "shelf", "t-1"),
            item("b", "shelf", "t-1"),
            item("c", "shelf", "t-2"),
          ]),
        );
      return query(listResult(0));
    });
    vi.mocked(useAttentionCounts).mockReturnValue({
      data: { expired: 2, expiring_soon: 3, low_stock: 1, records: 6 },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useAttentionCounts>);

    const { result } = renderHook(
      () =>
        useDashboardAttention({
          excludeModuleContexts: false,
          zones: [],
        }),
      { wrapper: withClient },
    );

    expect(result.current.count).toBe(2 + 3 + 1);
  });

  it("hands the module-data setting to the count", () => {
    vi.mocked(useItems).mockImplementation(() => query(listResult(0)));
    vi.mocked(useAttentionCounts).mockReturnValue({
      data: { expired: 0, expiring_soon: 0, low_stock: 0, records: 0 },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useAttentionCounts>);

    renderHook(
      () =>
        useDashboardAttention({
          excludeModuleContexts: true,
          zones: [],
        }),
      { wrapper: withClient },
    );

    // The heading must count the same rows the card's lists show.
    expect(useAttentionCounts).toHaveBeenCalledWith(true);
  });

  it("carries the short products, a used-up one included", async () => {
    vi.mocked(useItems).mockImplementation(() => query(listResult(0)));
    vi.mocked(useAttentionCounts).mockReturnValue({
      data: { expired: 0, expiring_soon: 0, low_stock: 1, records: 1 },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useAttentionCounts>);
    const spaghetti = {
      template_id: "t-spaghetti",
      name: "Spaghetti",
      on_hand: 0,
      minimum: 1,
      item_id: "i-1",
    };
    vi.mocked(itemsApi.getLowStockProducts).mockResolvedValueOnce([spaghetti]);

    const { result } = renderHook(
      () =>
        useDashboardAttention({
          excludeModuleContexts: false,
          zones: [],
        }),
      { wrapper: withClient },
    );

    await waitFor(() =>
      expect(result.current.lowProducts).toEqual([spaghetti]),
    );
  });
});
