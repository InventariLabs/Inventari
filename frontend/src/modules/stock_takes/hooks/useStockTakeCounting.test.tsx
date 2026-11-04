import React from "react";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useStockTakeCounting } from "./useStockTakeCounting";
import { queryKeys } from "@/hooks/queries/keys";
import { useFormGuardStore } from "@/store/formGuardStore";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockStockTake = {
  id: "st-1",
  name: "Monthly Check",
  status: "in_progress",
  location_id: "1",
  location_name: "Kitchen",
  items_count: 2,
  items: [
    {
      id: "sti-1",
      item_id: "item-1",
      name: "Test Item",
      system_quantity: 5,
      counted_quantity: 3,
      notes: "some note",
    },
  ],
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
  return { wrapper, queryClient };
};

/**
 * Render the hook and wait for the count it works on to arrive.
 *
 * The cases used to sleep 50 ms and trust the stock take had loaded by then.
 * On a loaded host it had not: `handleAddNewItem` found no location, returned
 * without sending anything, and the test then waited out a second for a POST
 * that was never going to come — red for the speed of the machine, not the
 * state of the hook.
 */
const renderLoaded = async () => {
  const rendered = renderHook(() => useStockTakeCounting("st-1"), {
    wrapper: createWrapper().wrapper,
  });
  await waitFor(() =>
    expect(rendered.result.current.stockTake?.location_id).toBeTruthy(),
  );
  return rendered;
};

describe("useStockTakeCounting", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/stock-takes/:id", () =>
        HttpResponse.json(mockStockTake),
      ),
    );
  });

  it("is disabled when id is undefined", () => {
    const { result } = renderHook(() => useStockTakeCounting(undefined), {
      wrapper: createWrapper().wrapper,
    });
    expect(result.current.isLoading).toBe(false);
    expect(result.current.stockTake).toBeUndefined();
  });

  it("returns initial state with defaults", () => {
    const { result } = renderHook(() => useStockTakeCounting("st-1"), {
      wrapper: createWrapper().wrapper,
    });
    expect(result.current.searchQuery).toBe("");
    expect(result.current.showDiscrepancies).toBe(false);
    expect(result.current.isAddingNewItem).toBe(false);
  });

  it("updates searchQuery via setSearchQuery", () => {
    const { result } = renderHook(() => useStockTakeCounting("st-1"), {
      wrapper: createWrapper().wrapper,
    });
    act(() => {
      result.current.setSearchQuery("milk");
    });
    expect(result.current.searchQuery).toBe("milk");
  });

  it("toggles showDiscrepancies via setShowDiscrepancies", () => {
    const { result } = renderHook(() => useStockTakeCounting("st-1"), {
      wrapper: createWrapper().wrapper,
    });
    act(() => {
      result.current.setShowDiscrepancies(true);
    });
    expect(result.current.showDiscrepancies).toBe(true);
  });

  it("keeps a counted quantity exactly as it was typed", () => {
    const { result } = renderHook(() => useStockTakeCounting("st-1"), {
      wrapper: createWrapper().wrapper,
    });
    act(() => {
      result.current.handleQuantityChange("item-1", "10.5");
    });
    expect(result.current.countedQuantities["item-1"]).toBe("10.5");
  });

  it("stops the step button at nothing rather than below it", () => {
    const { result } = renderHook(() => useStockTakeCounting("st-1"), {
      wrapper: createWrapper().wrapper,
    });
    act(() => {
      result.current.handleQuantityChange("item-1", "1");
    });
    act(() => {
      result.current.handleQuantityStep("item-1", -1);
    });
    act(() => {
      result.current.handleQuantityStep("item-1", -1);
    });
    expect(result.current.countedQuantities["item-1"]).toBe("0");
  });

  // 4.35 minus one step is 3.3499999999999996 in binary floating point, and
  // the box is what somebody reads back off the shelf before typing the next
  // row. The difference on the card was already rounded to the unit's scale;
  // the box the number is typed into was not.
  it("steps a decimal count without leaving a floating-point tail", () => {
    const { result } = renderHook(() => useStockTakeCounting("st-1"), {
      wrapper: createWrapper().wrapper,
    });
    act(() => {
      result.current.handleQuantityChange("item-1", "4.35");
    });
    act(() => {
      result.current.handleQuantityStep("item-1", -1);
    });
    expect(result.current.countedQuantities["item-1"]).toBe("3.35");
  });

  // A refused save puts the previous count back. It came off the wire as
  // "2.150" — the scale the column is stored in, not the one the box shows
  // everywhere else.
  it("puts a refused count back the way the box writes it", async () => {
    server.use(
      http.get("/api/v1/stock-takes/:id", () =>
        HttpResponse.json({
          ...mockStockTake,
          items: [{ ...mockStockTake.items[0], counted_quantity: "2.150" }],
        }),
      ),
      http.patch("/api/v1/stock-takes/:id/items/:itemId/count", () =>
        HttpResponse.json({ detail: "refused" }, { status: 409 }),
      ),
    );

    const { result } = await renderLoaded();

    act(() => {
      result.current.handleQuantityChange("item-1", "7");
    });
    act(() => {
      result.current.handleSaveItem("item-1");
    });

    await waitFor(() =>
      expect(result.current.countedQuantities["item-1"]).toBe("2.15"),
    );
  });

  // Nothing is not zero: a Save on an empty (or unreadable) box must not turn
  // "not counted" into "counted none".
  it.each(["", "1.34.13"])(
    "sends nothing when the box holds %j",
    async (text) => {
      const saved = vi.fn();
      server.use(
        http.patch("/api/v1/stock-takes/:id/items/:itemId/count", () => {
          saved();
          return HttpResponse.json({});
        }),
      );
      const { result } = await renderLoaded();

      act(() => {
        result.current.handleQuantityChange("item-1", text);
      });
      act(() => {
        result.current.handleSaveItem("item-1");
      });
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 50));
      });

      expect(saved).not.toHaveBeenCalled();
    },
  );

  it("handles API error gracefully", async () => {
    server.use(
      http.get("/api/v1/stock-takes/:id", () =>
        HttpResponse.json({ detail: "Not found" }, { status: 404 }),
      ),
    );
    const { result } = renderHook(() => useStockTakeCounting("bad-id"), {
      wrapper: createWrapper().wrapper,
    });
    // Hook should not throw — isLoading cycles and then isError is set
    expect(result.current).toBeDefined();
  });

  it("preserves user-edited quantity when stockTake query refetches", async () => {
    const { wrapper, queryClient } = createWrapper();
    const { result } = renderHook(() => useStockTakeCounting("st-1"), {
      wrapper,
    });
    // Seeding happens in an effect once the query resolves — waiting on a
    // fixed sleep instead of `waitFor` flakes under full-suite load.
    await waitFor(() => {
      expect(result.current.countedQuantities["item-1"]).toBe("3");
    });

    act(() => {
      result.current.handleQuantityChange("item-1", "99");
    });
    expect(result.current.countedQuantities["item-1"]).toBe("99");

    // Return payload that differs (fresh updated_at) so React Query
    // structural sharing yields a NEW stockTake reference, exactly like
    // a real refetch after a mutation.
    server.use(
      http.get("/api/v1/stock-takes/:id", () =>
        HttpResponse.json({
          ...mockStockTake,
          updated_at: new Date().toISOString(),
        }),
      ),
    );

    await act(async () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.stockTakes.detail("st-1"),
      });
    });
    // The refetched payload must not overwrite the user's edit.
    await waitFor(() => {
      expect(result.current.countedQuantities["item-1"]).toBe("99");
    });
  });

  it("counts progress only from listed items; surpluses get a separate counter", async () => {
    const { result } = renderHook(() => useStockTakeCounting("st-1"), {
      wrapper: createWrapper().wrapper,
    });

    // item-1 is listed (seeded counted: 3); item-2 is a surplus.
    await waitFor(() => {
      expect(result.current.countedQuantities["item-1"]).toBe("3");
    });
    act(() => {
      result.current.handleQuantityChange("item-2", "4");
    });

    expect(result.current.totalCount).toBe(2);
    expect(result.current.countedCount).toBe(1);
    expect(result.current.surplusCount).toBe(1);
  });

  it("derives location levels from stock take items", async () => {
    server.use(
      http.get("/api/v1/stock-takes/:id", () =>
        HttpResponse.json({
          ...mockStockTake,
          items: [
            {
              id: "sti-1",
              item_id: "item-1",
              name: "Test Item",
              system_quantity: 5,
              counted_quantity: 3,
              shelf_location: "A-1-01",
            },
            {
              id: "sti-2",
              item_id: "item-2",
              name: "Second Item",
              system_quantity: 2,
              counted_quantity: null,
              shelf_location: "A-2-02",
            },
          ],
        }),
      ),
    );
    const { result } = await renderLoaded();
    expect(result.current.locationLevels).toEqual(["A"]);
  });

  // products in the location but not in the stock take snapshot
  // are exposed for the outside-items bar.
  it("exposes products outside the stock take snapshot", async () => {
    server.use(
      http.get("/api/v1/locations/1/items", () =>
        HttpResponse.json(
          onePage([
            { id: "item-1", name: "Test Item", quantity: 5 },
            { id: "item-9", name: "New Arrival", quantity: 2 },
          ]),
        ),
      ),
    );
    const { result } = renderHook(() => useStockTakeCounting("st-1"), {
      wrapper: createWrapper().wrapper,
    });
    await waitFor(() => {
      expect(result.current.outsideItems.map((i) => i.id)).toEqual(["item-9"]);
    });
  });

  // Creating a product on the fly must POST /items in the
  // counted location and then register the surplus — not create a
  // phantom in-memory id.
  //
  // The record is opened holding nothing. Created with the counted quantity,
  // the goods were on the shelf before the count was closed (a cancelled
  // count left them there), the row's baseline read the same number as the
  // count, and the correction document closing the count had no line for
  // them. The count is what puts them on the shelf, once, when it closes.
  it("creates a product in the location and registers it as surplus", async () => {
    const itemPosts: Record<string, unknown>[] = [];
    const surplusPosts: Record<string, unknown>[] = [];
    server.use(
      http.post("/api/v1/items", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        itemPosts.push(body);
        return HttpResponse.json(
          { id: "item-new", name: body.name },
          { status: 201 },
        );
      }),
      http.post("/api/v1/stock-takes/:id/items", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        surplusPosts.push(body);
        return HttpResponse.json({ id: "sti-new" }, { status: 201 });
      }),
    );

    const { result } = await renderLoaded();

    act(() => {
      result.current.handleAddNewItem({
        name: "New Product",
        barcode: "BRC-1",
        quantity: 2,
        categoryId: "cat-1",
        uomId: "uom-1",
      });
    });

    await waitFor(() => {
      expect(itemPosts.length).toBe(1);
      expect(surplusPosts.length).toBe(1);
    });
    expect(itemPosts[0]).toMatchObject({
      name: "New Product",
      barcode: "BRC-1",
      quantity: 0,
      category_id: "cat-1",
      uom_id: "uom-1",
      location_id: "1",
    });
    expect(surplusPosts[0]).toMatchObject({
      item_id: "item-new",
      counted_quantity: 2,
    });
  });

  // contract guard (red until the save is routed to PATCH …/count):
  // a listed item must be saved through PATCH with StockTakeItem.id in the
  // path — the backend resolves that segment as StockTakeItem.id, NOT the
  // product id.
  it("saves a listed item via PATCH count with StockTakeItem.id in the path", async () => {
    const patches: { path: string; body: Record<string, unknown> }[] = [];
    server.use(
      http.patch(
        "/api/v1/stock-takes/:id/items/:itemId/count",
        async ({ request, params }) => {
          const body = (await request.json()) as Record<string, unknown>;
          patches.push({ path: params.itemId as string, body });
          return HttpResponse.json({
            id: params.itemId,
            counted_quantity: body.counted_quantity,
          });
        },
      ),
    );

    const { result } = await renderLoaded();

    act(() => {
      result.current.handleSaveItem("item-1");
    });

    await waitFor(() => expect(patches.length).toBe(1));
    expect(patches[0].path).toBe("sti-1");
    expect(patches[0].path).not.toBe("item-1");
    expect(patches[0].body.counted_quantity).toBe(3);
  });

  // contract (surplus): a product not on the stock take list must be
  // saved through POST …/items with the product (Item) id in the body.
  it("saves a surplus product via POST items with Item.id in the body", async () => {
    const posts: { body: Record<string, unknown> }[] = [];
    server.use(
      http.post("/api/v1/stock-takes/:id/items", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        posts.push({ body });
        return HttpResponse.json({ id: "sti-new", ...body }, { status: 201 });
      }),
    );

    const { result } = await renderLoaded();

    act(() => {
      result.current.handleQuantityChange("item-2", "4");
    });
    act(() => {
      result.current.handleSaveItem("item-2");
    });

    await waitFor(() => expect(posts.length).toBe(1));
    expect(posts[0].body.item_id).toBe("item-2");
    expect(posts[0].body.counted_quantity).toBe(4);
  });
  // A number typed into the box is one button press away from being a count,
  // and walking off the screen throws it away. Everything that summarises the
  // stock take therefore reads what the server holds.
  describe("a number typed but not saved", () => {
    const twoListedItems = {
      ...mockStockTake,
      items_count: 2,
      items: [
        {
          id: "sti-1",
          item_id: "item-1",
          name: "Test Item",
          system_quantity: 5,
          counted_quantity: 5,
        },
        {
          id: "sti-2",
          item_id: "item-2",
          name: "Second Item",
          system_quantity: 2,
          counted_quantity: null,
        },
      ],
    };

    beforeEach(() => {
      useFormGuardStore.getState().setDirtyForm(null);
      server.use(
        http.get("/api/v1/stock-takes/:id", () =>
          HttpResponse.json(twoListedItems),
        ),
      );
    });

    it("does not move the progress", async () => {
      const { result } = renderHook(() => useStockTakeCounting("st-1"), {
        wrapper: createWrapper().wrapper,
      });
      await waitFor(() => expect(result.current.countedCount).toBe(1));

      act(() => {
        result.current.handleQuantityChange("item-2", "20");
      });

      expect(result.current.countedQuantities["item-2"]).toBe("20");
      expect(result.current.countedCount).toBe(1);
      expect(result.current.progress).toBe(50);
    });

    it("is not counted as a discrepancy", async () => {
      const { result } = renderHook(() => useStockTakeCounting("st-1"), {
        wrapper: createWrapper().wrapper,
      });
      await waitFor(() => expect(result.current.countedCount).toBe(1));
      expect(result.current.discrepanciesCount).toBe(0);

      act(() => {
        result.current.handleQuantityChange("item-2", "20");
      });

      expect(result.current.discrepanciesCount).toBe(0);
      expect(result.current.hasDiscrepancy("item-2")).toBe(false);
      expect(result.current.getDiscrepancyType("item-2")).toBeNull();
    });

    it("is named on its own row and in the summary", async () => {
      const { result } = renderHook(() => useStockTakeCounting("st-1"), {
        wrapper: createWrapper().wrapper,
      });
      await waitFor(() => expect(result.current.countedCount).toBe(1));
      expect(result.current.unsavedCount).toBe(0);

      act(() => {
        result.current.handleQuantityChange("item-2", "20");
      });

      expect(result.current.unsavedCount).toBe(1);
      expect(result.current.isUnsaved("item-2")).toBe(true);
      expect(result.current.isUnsaved("item-1")).toBe(false);
    });

    it("holds the navigation gate until it is saved", async () => {
      const { result, unmount } = renderHook(
        () => useStockTakeCounting("st-1"),
        { wrapper: createWrapper().wrapper },
      );
      await waitFor(() => expect(result.current.countedCount).toBe(1));
      expect(useFormGuardStore.getState().dirtyForm).toBeNull();

      act(() => {
        result.current.handleQuantityChange("item-1", "7");
      });
      await waitFor(() =>
        expect(useFormGuardStore.getState().dirtyForm).not.toBeNull(),
      );

      // Typing the saved number back leaves nothing to lose.
      act(() => {
        result.current.handleQuantityChange("item-1", "5");
      });
      await waitFor(() =>
        expect(useFormGuardStore.getState().dirtyForm).toBeNull(),
      );

      act(() => {
        result.current.handleQuantityChange("item-1", "7");
      });
      await waitFor(() =>
        expect(useFormGuardStore.getState().dirtyForm).not.toBeNull(),
      );
      // Leaving the screen must not leave the gate closed behind it.
      unmount();
      expect(useFormGuardStore.getState().dirtyForm).toBeNull();
    });
  });
  // A stock take may carry a tolerance: a difference small enough that nobody
  // is expected to explain it. The rule lives next to the write, and the
  // screen reads the answer rather than working out its own — otherwise the
  // report and the counting screen disagree about the same count.
  describe("a stock take with a tolerance", () => {
    const withTolerance = (isDiscrepancy: number) => ({
      ...mockStockTake,
      tolerance_percent: 5,
      items_count: 1,
      items: [
        {
          id: "sti-1",
          item_id: "item-1",
          name: "Test Item",
          system_quantity: 100,
          counted_quantity: 103,
          is_discrepancy: isDiscrepancy,
        },
      ],
    });

    it("follows the server when a difference is inside the tolerance", async () => {
      server.use(
        http.get("/api/v1/stock-takes/:id", () =>
          HttpResponse.json(withTolerance(0)),
        ),
      );
      const { result } = renderHook(() => useStockTakeCounting("st-1"), {
        wrapper: createWrapper().wrapper,
      });
      await waitFor(() => expect(result.current.countedCount).toBe(1));

      // 103 against 100 is a difference; inside a 5% tolerance it is not a
      // discrepancy, and the screen must not invent one.
      expect(result.current.hasDiscrepancy("item-1")).toBe(false);
      expect(result.current.getDiscrepancyType("item-1")).toBeNull();
      expect(result.current.discrepanciesCount).toBe(0);
    });

    it("follows the server when the difference is outside it", async () => {
      server.use(
        http.get("/api/v1/stock-takes/:id", () =>
          HttpResponse.json(withTolerance(1)),
        ),
      );
      const { result } = renderHook(() => useStockTakeCounting("st-1"), {
        wrapper: createWrapper().wrapper,
      });
      await waitFor(() => expect(result.current.countedCount).toBe(1));

      expect(result.current.hasDiscrepancy("item-1")).toBe(true);
      expect(result.current.getDiscrepancyType("item-1")).toBe("surplus");
      expect(result.current.discrepanciesCount).toBe(1);
    });

    /** A unit found on another location of the count keeps its one row,
     * moved to where it was found, and the server flags it although the
     * number agrees. Read from the numbers alone it was no difference at
     * all, so the card hid the reason the tolerance then demanded and the
     * count could not be completed from this screen. Here it is what the
     * report calls it: goods nobody expected on this location. */
    it("calls a unit found away from its location a surplus here", async () => {
      server.use(
        http.get("/api/v1/stock-takes/:id", () =>
          HttpResponse.json({
            ...withTolerance(1),
            items: [
              {
                ...withTolerance(1).items[0],
                counted_quantity: 100,
                expected_location_id: "shelf-a",
              },
            ],
          }),
        ),
      );
      const { result } = renderHook(() => useStockTakeCounting("st-1"), {
        wrapper: createWrapper().wrapper,
      });
      await waitFor(() => expect(result.current.countedCount).toBe(1));

      expect(result.current.getDiscrepancyType("item-1")).toBe("surplus");
    });
  });
});
