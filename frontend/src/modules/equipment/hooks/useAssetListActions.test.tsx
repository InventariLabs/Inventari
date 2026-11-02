import React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";

import { server } from "@/test/mocks/server";
import { ReadableError } from "@/lib/errors";
import { useAssetListActions } from "./useAssetListActions";

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    loading: vi.fn(),
  },
}));

vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useModules: () => ({
    enabledModules: ["equipment"],
    isModuleEnabled: () => true,
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

vi.mock("@/utils/helpers", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/utils/helpers")>()),
  downloadBlob: vi.fn(),
}));

interface Asset {
  id: string;
  name: string;
  label_code?: string | null;
  holder_name?: string | null;
}

function asset(n: number, extra: Partial<Asset> = {}): Asset {
  return { id: `asset-${n}`, name: `Laptop ${n}`, ...extra };
}

/** The list requests the hook made, newest last. */
let listRequests: URLSearchParams[];

function serveList(items: Asset[], total = items.length) {
  server.use(
    http.get("/api/v1/equipment/assets", ({ request }) => {
      const params = new URL(request.url).searchParams;
      listRequests.push(params);
      return HttpResponse.json({
        items,
        total,
        offset: Number(params.get("offset") ?? 0),
        limit: 50,
        has_more: total > Number(params.get("offset") ?? 0) + 50,
      });
    }),
  );
}

let address = "";

function AddressProbe() {
  const location = useLocation();
  address = location.search;
  return null;
}

function renderList(entry = "/equipment/assets") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[entry]}>
        <AddressProbe />
        {children}
      </MemoryRouter>
    </QueryClientProvider>
  );
  return renderHook(() => useAssetListActions(), { wrapper });
}

const lastList = () => listRequests[listRequests.length - 1];

beforeEach(() => {
  listRequests = [];
  address = "";
  server.use(
    http.get("/api/v1/items/archived", () =>
      HttpResponse.json({ items: [], total: 0, offset: 0, limit: 50 }),
    ),
  );
});

describe("useAssetListActions — sorting is server-side", () => {
  it("a new column starts ascending, the same column flips, the dropdown sets both", async () => {
    serveList([asset(1)]);
    const { result } = renderList();
    await waitFor(() => expect(result.current.items).toHaveLength(1));
    expect(lastList().get("sort")).toBe("created_at");
    expect(lastList().get("sort_dir")).toBe("desc");

    act(() => result.current.handleSortChange("name"));
    await waitFor(() => expect(lastList().get("sort")).toBe("name"));
    expect(lastList().get("sort_dir")).toBe("asc");

    act(() => result.current.handleSortChange("name"));
    await waitFor(() => expect(lastList().get("sort_dir")).toBe("desc"));

    act(() => result.current.applySort("created_at", "asc"));
    await waitFor(() => expect(lastList().get("sort")).toBe("created_at"));
    expect(lastList().get("sort_dir")).toBe("asc");
  });
});

describe("useAssetListActions — paging", () => {
  it("turns pages by fifty, stops at the last page and at the first, and drops the selection on a turn", async () => {
    serveList([asset(1), asset(2)], 120);
    const { result } = renderList();
    await waitFor(() => expect(result.current.total).toBe(120));

    act(() => result.current.toggleSelect("asset-1"));
    expect(result.current.selectedIds.has("asset-1")).toBe(true);

    act(() => result.current.onNext());
    await waitFor(() => expect(lastList().get("offset")).toBe("50"));
    expect(result.current.selectedIds.size).toBe(0);

    act(() => result.current.onNext());
    await waitFor(() => expect(result.current.skip).toBe(100));
    // 100 + 50 is past 120: there is no fourth page to ask for.
    act(() => result.current.onNext());
    expect(result.current.skip).toBe(100);

    act(() => result.current.onPrev());
    act(() => result.current.onPrev());
    act(() => result.current.onPrev());
    await waitFor(() => expect(result.current.skip).toBe(0));
  });

  it("does not turn the page of a list that is still empty", async () => {
    serveList([], 0);
    const { result } = renderList();
    await waitFor(() => expect(listRequests).toHaveLength(1));
    act(() => result.current.onNext());
    expect(result.current.skip).toBe(0);
  });
});

describe("useAssetListActions — selection", () => {
  it("select-all takes the page, a second press clears it, and the whole-set widening counts the total", async () => {
    serveList([asset(1), asset(2)], 61);
    const { result } = renderList();
    await waitFor(() => expect(result.current.items).toHaveLength(2));

    act(() => result.current.toggleSelectAll());
    expect([...result.current.selectedIds]).toEqual(["asset-1", "asset-2"]);
    expect(result.current.selectedCount).toBe(2);

    act(() => result.current.toggleSelectAll());
    expect(result.current.selectedIds.size).toBe(0);

    act(() => result.current.selectAllMatching());
    expect(result.current.allMatching).toBe(true);
    expect(result.current.selectedCount).toBe(61);

    // Touching one checkbox narrows the action back to the page.
    act(() => result.current.toggleSelect("asset-1"));
    expect(result.current.allMatching).toBe(false);
    expect(result.current.selectedCount).toBe(1);
  });
});

describe("useAssetListActions — the filters live in the address", () => {
  it("writes location and checked-out into the address and clears them again", async () => {
    serveList([asset(1)]);
    const { result } = renderList();
    await waitFor(() => expect(result.current.items).toHaveLength(1));

    act(() => result.current.handleLocationFilter("loc-1"));
    act(() => result.current.handleCheckedOutChange(true));
    await waitFor(() => expect(lastList().get("location_id")).toBe("loc-1"));
    expect(lastList().get("checked_out")).toBe("true");
    expect(address).toContain("location=loc-1");
    expect(address).toContain("checked_out=1");

    act(() => result.current.handleLocationFilter(""));
    act(() => result.current.handleCheckedOutChange(false));
    await waitFor(() => expect(address).toBe(""));
  });

  it("the archive tab drops a narrowing it cannot honour from the address", async () => {
    serveList([asset(1)]);
    const { result } = renderList("/equipment/assets?status=AVAILABLE");
    await waitFor(() => expect(result.current.statusFilter).toBe("AVAILABLE"));

    act(() => result.current.setListTab("archived"));
    await waitFor(() => expect(address).toBe("?tab=archived"));
    expect(result.current.listTab).toBe("archived");
  });
});

describe("useAssetListActions — printing labels for the selection", () => {
  it("says so and asks for nothing when no selected asset has a label", async () => {
    const exported = vi.fn();
    server.use(
      http.get("/api/v1/labels/pool/export/png", () => {
        exported();
        return new HttpResponse(new Blob(["png"]));
      }),
    );
    serveList([asset(1, { label_code: null })]);
    const { result } = renderList();
    await waitFor(() => expect(result.current.items).toHaveLength(1));
    act(() => result.current.toggleSelect("asset-1"));

    await act(() => result.current.handleBulkPrintLabels());
    expect(toast.error).toHaveBeenCalledWith(
      "None of the selected assets has a label code yet.",
    );
    expect(exported).not.toHaveBeenCalled();
  });

  it("asks for the selected assets' codes only", async () => {
    let codes: string[] = [];
    server.use(
      http.get("/api/v1/labels/pool/export/png", ({ request }) => {
        codes = new URL(request.url).searchParams.getAll("short_codes");
        return new HttpResponse(new Blob(["png"]));
      }),
    );
    serveList([
      asset(1, { label_code: "AB12" }),
      asset(2, { label_code: "CD34" }),
    ]);
    const { result } = renderList();
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    act(() => result.current.toggleSelect("asset-2"));

    await act(() => result.current.handleBulkPrintLabels());
    expect(codes).toEqual(["CD34"]);
  });

  it("reports a failed download instead of saving nothing in silence", async () => {
    server.use(
      http.get("/api/v1/labels/pool/export/png", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    serveList([asset(1, { label_code: "AB12" })]);
    const { result } = renderList();
    await waitFor(() => expect(result.current.items).toHaveLength(1));
    act(() => result.current.toggleSelect("asset-1"));

    await act(() => result.current.handleBulkPrintLabels());
    expect(toast.error).toHaveBeenCalled();
  });
});

describe("useAssetListActions — bulk return", () => {
  it("refuses to open over a selection where nothing is out", async () => {
    serveList([asset(1)]);
    const { result } = renderList();
    await waitFor(() => expect(result.current.items).toHaveLength(1));
    act(() => result.current.toggleSelect("asset-1"));

    act(() => result.current.openBulkReturn());
    expect(toast.error).toHaveBeenCalledWith(
      "None of the selected assets is currently out.",
    );
    expect(result.current.showBulkReturn).toBe(false);
  });

  it("returns only the selected assets that are out, then closes and clears", async () => {
    let body: { item_ids?: string[] } = {};
    server.use(
      http.post("/api/v1/equipment/items/bulk-return", async ({ request }) => {
        body = (await request.json()) as typeof body;
        return HttpResponse.json({ checked_in: 1, errors: [] });
      }),
    );
    serveList([asset(1, { holder_name: "Ann" }), asset(2)]);
    const { result } = renderList();
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    act(() => result.current.toggleSelectAll());
    expect(result.current.returnableCount).toBe(1);

    act(() => result.current.openBulkReturn());
    expect(result.current.showBulkReturn).toBe(true);

    act(() => result.current.handleBulkReturn({ condition: "GOOD" } as never));
    await waitFor(() => expect(result.current.showBulkReturn).toBe(false));
    expect(body.item_ids).toEqual(["asset-1"]);
    expect(toast.success).toHaveBeenCalled();
    expect(result.current.selectedIds.size).toBe(0);
  });

  it("names the rows a partial return left behind", async () => {
    server.use(
      http.post("/api/v1/equipment/items/bulk-return", () =>
        HttpResponse.json({
          checked_in: 1,
          errors: [{ item_id: "asset-2", error: "no active assignment" }],
        }),
      ),
    );
    serveList([
      asset(1, { holder_name: "Ann" }),
      asset(2, { holder_name: "Bob" }),
    ]);
    const { result } = renderList();
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    act(() => result.current.toggleSelectAll());

    act(() => result.current.handleBulkReturn({ condition: "GOOD" } as never));
    await waitFor(() => expect(toast.warning).toHaveBeenCalled());
    const [, options] = vi.mocked(toast.warning).mock.calls[0];
    expect(String((options as { description: string }).description)).toContain(
      "Laptop 2",
    );
  });
});

describe("useAssetListActions — purging one archived asset", () => {
  it("keeps the dialog open with the blocker in words when documents hold the asset", async () => {
    server.use(
      http.post("/api/v1/equipment/items/bulk-purge", () =>
        HttpResponse.json({
          purged: 0,
          errors: [
            {
              item_id: "asset-1",
              error: "referenced by documents",
              code: "PURGE_BLOCKED_DOCUMENTS",
              blocks: [{ count: 3 }],
            },
          ],
        }),
      ),
    );
    serveList([asset(1)]);
    const { result } = renderList();
    await waitFor(() => expect(result.current.items).toHaveLength(1));
    act(() => result.current.setPurgeTarget("asset-1"));

    const attempt = result.current.handleSinglePurge("asset-1");
    await expect(attempt).rejects.toBeInstanceOf(ReadableError);
    await expect(attempt).rejects.toThrow(
      "Linked to posted documents (3) — cannot be permanently deleted",
    );
    expect(result.current.purgeTarget).toBe("asset-1");
  });

  it("says a stock take holds it, and falls back to the server's words otherwise", async () => {
    server.use(
      http.post("/api/v1/equipment/items/bulk-purge", async ({ request }) => {
        const [id] = (await request.json()) as string[];
        return HttpResponse.json({
          purged: 0,
          errors: [
            id === "asset-1"
              ? { item_id: id, error: "x", code: "PURGE_BLOCKED_STOCK_TAKES" }
              : { item_id: id, error: "held for another reason" },
          ],
        });
      }),
    );
    serveList([asset(1), asset(2)]);
    const { result } = renderList();
    await waitFor(() => expect(result.current.items).toHaveLength(2));

    await expect(result.current.handleSinglePurge("asset-1")).rejects.toThrow(
      "Recorded in a stock take (0) — cannot be permanently deleted",
    );
    await expect(result.current.handleSinglePurge("asset-2")).rejects.toThrow(
      "held for another reason",
    );
  });

  it("closes the dialog once the asset is gone", async () => {
    server.use(
      http.post("/api/v1/equipment/items/bulk-purge", () =>
        HttpResponse.json({ purged: 1, errors: [] }),
      ),
    );
    serveList([asset(1)]);
    const { result } = renderList();
    await waitFor(() => expect(result.current.items).toHaveLength(1));
    act(() => result.current.setPurgeTarget("asset-1"));

    await act(() => result.current.handleSinglePurge("asset-1"));
    expect(toast.success).toHaveBeenCalledWith("Asset permanently deleted");
    expect(result.current.purgeTarget).toBeNull();
  });
});

describe("useAssetListActions — bulk edit", () => {
  it("sends the selection with the action, and reports the rows it could not change", async () => {
    let body: Record<string, unknown> = {};
    server.use(
      http.patch("/api/v1/equipment/assets/bulk", async ({ request }) => {
        body = (await request.json()) as typeof body;
        return HttpResponse.json({
          updated: 1,
          errors: [{ item_id: "asset-2", error: "locked" }],
        });
      }),
    );
    serveList([asset(1), asset(2)]);
    const { result } = renderList();
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    act(() => result.current.toggleSelectAll());
    act(() => result.current.setBulkEditAction("change_location"));

    act(() =>
      result.current.handleBulkEdit("change_location", {
        location_id: "loc-9",
      }),
    );
    await waitFor(() => expect(result.current.bulkEditAction).toBeNull());
    expect(body).toEqual({
      item_ids: ["asset-1", "asset-2"],
      action: "change_location",
      data: { location_id: "loc-9" },
    });
    expect(toast.warning).toHaveBeenCalled();
  });

  it("confirms a clean edit with the count it changed", async () => {
    server.use(
      http.patch("/api/v1/equipment/assets/bulk", () =>
        HttpResponse.json({ updated: 2, errors: [] }),
      ),
    );
    serveList([asset(1), asset(2)]);
    const { result } = renderList();
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    act(() => result.current.toggleSelectAll());

    act(() =>
      result.current.handleBulkEdit("change_status", { status: "AVAILABLE" }),
    );
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("2 assets updated"),
    );
  });
});
