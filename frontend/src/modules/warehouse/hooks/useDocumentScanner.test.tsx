import { describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { serveLocations } from "@/test/serveLocations";
import { useDocumentScanner } from "./useDocumentScanner";

const scan = vi.hoisted(() => vi.fn());
let locationRequests: URLSearchParams[] = [];

vi.mock("@/lib/api/labels", () => ({ labelsApi: { scan } }));
vi.mock("@/hooks/useScanCamera", () => ({
  useScanCamera: () => ({
    isCameraActive: false,
    scannerError: null,
    isTorchOn: false,
    toggleTorch: vi.fn(),
    restartCamera: vi.fn(),
  }),
}));
vi.mock("react-router-dom", () => ({ useNavigate: () => vi.fn() }));
// Keys with their options, so a test can read what a message was given.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: object) =>
      options ? `${key} ${JSON.stringify(options)}` : key,
  }),
}));
const toastWarning = vi.hoisted(() => vi.fn());
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    warning: toastWarning,
  }),
}));

describe("useDocumentScanner — a product's own label", () => {
  it("adds the labelled product as a line, with its own code", async () => {
    scan.mockResolvedValue({
      status: "assigned",
      label_code: "STM-EHBH",
      action: "show_quick_actions",
      item: {
        id: "item-1",
        name: "Lean Quark",
        barcode: "5901234123457",
        uom_id: "uom-1",
      },
    });
    const onAddOrIncrementLine = vi.fn();
    const { result } = renderHook(() =>
      useDocumentScanner({ onAddOrIncrementLine, onOpenQuickAdd: vi.fn() }),
    );

    await act(async () => {
      result.current.handleCodeScanned("http://host/s/STM-EHBH");
    });

    await waitFor(() => expect(onAddOrIncrementLine).toHaveBeenCalled());
    await waitFor(() => expect(result.current.scanLoading).toBe(false));
    expect(onAddOrIncrementLine.mock.calls[0][0]).toMatchObject({
      item_id: "item-1",
      name: "Lean Quark",
      barcode: "5901234123457",
    });
  });
});

describe("useDocumentScanner — a product scanned into a dispatch", () => {
  const record = (id: string, locationId: string, extra = {}) => ({
    id,
    location: `Shelf ${locationId}`,
    location_id: locationId,
    expiry_date: null,
    created_at: "2026-01-01T00:00:00",
    quantity: 5,
    ...extra,
  });

  const scanStock = async (
    items: unknown[],
    options: {
      sourceLocationId?: string;
      strategy?: "FIFO" | "FEFO";
      /** The organization's places, as the server holds them. */
      places?: Array<{ id: string; name: string; parent_id?: string | null }>;
    },
  ) => {
    locationRequests = serveLocations(options.places ?? []);
    scan.mockResolvedValue({
      status: "product_stock",
      label_code: "5901234123457",
      action: "show_stock_actions",
      stock_summary: {
        total_quantity: 10,
        unit: "pcs",
        removal_strategy: options.strategy ?? "FIFO",
        template: { id: "tpl-1", name: "Lean Quark" },
        items,
      },
    });
    const onAddOrIncrementLine = vi.fn();
    const { result } = renderHook(() =>
      useDocumentScanner({
        onAddOrIncrementLine,
        onOpenQuickAdd: vi.fn(),
        stock: { locationId: options.sourceLocationId ?? null },
      }),
    );
    await act(async () => {
      result.current.handleCodeScanned("5901234123457");
    });
    await waitFor(() => expect(result.current.scanLoading).toBe(false));
    await waitFor(() => expect(scan).toHaveBeenCalled());
    return onAddOrIncrementLine;
  };

  it("takes the record standing in the source location, not the newest anywhere", async () => {
    const onAdd = await scanStock(
      [
        record("elsewhere-newest", "loc-b", { created_at: "2026-03-01" }),
        record("here", "loc-a"),
      ],
      { sourceLocationId: "loc-a" },
    );

    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(1));
    expect(onAdd.mock.calls[0][0].item_id).toBe("here");
  });

  it("takes a record on a shelf below the zone the document leaves from", async () => {
    // A dispatch from a zone takes from the shelves under it, and the record
    // a person scans there is one the confirmation can plan; refusing it as
    // "not in the source" sent them to pick the very shelf by hand.
    const onAdd = await scanStock(
      [
        record("outside", "loc-b", { created_at: "2025-12-01" }),
        record("below", "bin-1"),
      ],
      {
        sourceLocationId: "zone",
        places: [
          { id: "zone", name: "Zone", parent_id: null },
          { id: "bin-1", name: "Bin 1", parent_id: "zone" },
          { id: "loc-b", name: "Shelf B", parent_id: null },
        ],
      },
    );

    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(1));
    expect(onAdd.mock.calls[0][0].item_id).toBe("below");
    // Only the shelves the product stands on were asked about: the zone's
    // own list is not read to find them.
    const asked = locationRequests.filter((request) => request.has("under"));
    expect(asked).toHaveLength(1);
    expect(asked[0].getAll("ids").sort()).toEqual(["bin-1", "loc-b"]);
  });

  it("skips an empty record on the shelf", async () => {
    const onAdd = await scanStock(
      [record("empty", "loc-a", { quantity: 0 }), record("full", "loc-a")],
      { sourceLocationId: "loc-a" },
    );

    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(1));
    expect(onAdd.mock.calls[0][0].item_id).toBe("full");
  });

  it("takes the oldest record when the product leaves first in, first out", async () => {
    const onAdd = await scanStock(
      [
        record("newer", "loc-a", { created_at: "2026-02-01" }),
        record("older", "loc-a", { created_at: "2026-01-01" }),
      ],
      { sourceLocationId: "loc-a", strategy: "FIFO" },
    );

    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(1));
    expect(onAdd.mock.calls[0][0].item_id).toBe("older");
  });

  it("takes the earliest best-before when the product leaves first expired, first out", async () => {
    const onAdd = await scanStock(
      [
        record("undated", "loc-a", { created_at: "2026-01-01" }),
        record("late", "loc-a", { expiry_date: "2027-06-01" }),
        record("soon", "loc-a", { expiry_date: "2026-11-01" }),
      ],
      { sourceLocationId: "loc-a", strategy: "FEFO" },
    );

    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(1));
    expect(onAdd.mock.calls[0][0].item_id).toBe("soon");
  });

  it("says so and adds nothing when the source location has none, naming where there is stock", async () => {
    toastWarning.mockClear();
    const onAdd = await scanStock([record("elsewhere", "loc-b")], {
      sourceLocationId: "loc-a",
    });

    await waitFor(() => expect(toastWarning).toHaveBeenCalledTimes(1));
    expect(onAdd).not.toHaveBeenCalled();
    expect(toastWarning.mock.calls[0][0]).toContain(
      "warehouse:scan.notInSource",
    );
  });

  it("names each place once with its summed quantity", async () => {
    toastWarning.mockClear();
    await scanStock(
      [
        record("a1", "loc-b", { quantity: 7, location: "Source A" }),
        record("c1", "loc-c", { quantity: 2, location: "Source C" }),
        record("a2", "loc-b", { quantity: 5, location: "Source A" }),
        record("a3", "loc-b", { quantity: 4, location: "Source A" }),
      ],
      { sourceLocationId: "loc-a" },
    );

    await waitFor(() => expect(toastWarning).toHaveBeenCalledTimes(1));
    expect(toastWarning.mock.calls[0][0]).toContain(
      '"places":"Source A (16), Source C (2)"',
    );
  });

  it("says there is no stock anywhere when every record is empty", async () => {
    toastWarning.mockClear();
    const onAdd = await scanStock([record("e", "loc-b", { quantity: 0 })], {
      sourceLocationId: "loc-a",
    });

    await waitFor(() => expect(toastWarning).toHaveBeenCalledTimes(1));
    expect(onAdd).not.toHaveBeenCalled();
    expect(toastWarning.mock.calls[0][0]).toContain(
      "warehouse:scan.notAnywhere",
    );
  });

  it("asks for the source first and adds nothing while none is chosen", async () => {
    toastWarning.mockClear();
    const onAdd = await scanStock([record("elsewhere", "loc-b")], {});

    await waitFor(() => expect(toastWarning).toHaveBeenCalledTimes(1));
    expect(onAdd).not.toHaveBeenCalled();
    expect(toastWarning.mock.calls[0][0]).toContain(
      "warehouse:scan.chooseSource",
    );
  });
});
