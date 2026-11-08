/**
 * The deduction walks the same road the picking sheet walks — start, tick
 * every row the checklist can name off its recommended item, complete — and
 * it trusts the server's answer on every row: what the server refused stays
 * untaken, whatever the loop wished it had taken.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { ReactNode } from "react";
import { renderHook, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useStockDeduction } from "./useStockDeduction";
import { queryKeys } from "@/hooks/queries/keys";
import type {
  PickingItem,
  PickingScanResponse,
  PickingStartResponse,
} from "../types/core";

const mocks = vi.hoisted(() => ({
  startPicking: vi.fn(),
  scanPicking: vi.fn(),
  completePicking: vi.fn(),
}));

vi.mock("../api/recipes", () => ({
  recipesApi: {
    startPicking: mocks.startPicking,
    scanPicking: mocks.scanPicking,
    completePicking: mocks.completePicking,
  },
}));

function row(overrides: Partial<PickingItem>): PickingItem {
  return {
    ingredient_id: "ing-1",
    name: "Flour",
    quantity_to_pick: 500,
    uom_symbol: "g",
    recommended_item_id: "item-1",
    location: "Pantry",
    fefo_days_left: null,
    fefo_expiry_date: null,
    status: "pending",
    is_linked: true,
    ...overrides,
  };
}

function pickedResult(
  overrides: Partial<PickingScanResponse> = {},
): PickingScanResponse {
  return {
    status: "picked",
    ingredient_id: "ing-1",
    ingredient_name: "Flour",
    quantity_consumed: "500.000",
    uom_symbol: "g",
    item_remaining_quantity: "0.000",
    session_complete: false,
    opened_suggestion: null,
    candidates: null,
    fefo_mismatch_days_left: null,
    fefo_recommended_item_id: null,
    fefo_recommended_expiry_date: null,
    fefo_scanned_item_id: null,
    unit_mismatch: null,
    ...overrides,
  };
}

function startResponse(
  rows: PickingItem[],
  overrides: Partial<PickingStartResponse> = {},
): PickingStartResponse {
  return {
    picking_session_id: "sess-1",
    recipe_name: "Pancakes",
    servings: 4,
    resumed: false,
    items_to_pick: rows,
    ...overrides,
  };
}

beforeEach(() => {
  mocks.startPicking.mockReset();
  mocks.scanPicking.mockReset();
  mocks.completePicking.mockReset();
  mocks.startPicking.mockResolvedValue(startResponse([row({})]));
  mocks.scanPicking.mockResolvedValue(pickedResult());
  mocks.completePicking.mockResolvedValue({ status: "completed" });
});

/** The hook reads the shared query client, so it renders under a real one —
 *  the invalidation the walk has to leave behind is read off that client. */
function renderDeduction(recipeId = "r-1") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const rendered = renderHook(() => useStockDeduction(recipeId), { wrapper });
  return { ...rendered, client };
}

const stockSurfaces = (recipeId: string) => [
  queryKeys.items.all,
  queryKeys.stockMoves.all,
  queryKeys.stockQuants.all,
  queryKeys.stockLots.all,
  queryKeys.recipes.availability(recipeId, 4),
  queryKeys.recipes.available(),
];

/** The harness collects a query the moment nothing observes it (gcTime 0)
 *  and these have no component mounted; the per-key override keeps them
 *  alive across the awaited walk so the invalidation can be read back. */
const seedStockViews = (client: QueryClient, recipeId: string) => {
  for (const key of stockSurfaces(recipeId)) {
    client.setQueryDefaults(key, { gcTime: Infinity });
    client.setQueryData(key, {});
  }
};

describe("useStockDeduction", () => {
  it("starts a session, scans each pending row by its recommendation, completes", async () => {
    mocks.startPicking.mockResolvedValue(
      startResponse([
        row({ ingredient_id: "a", recommended_item_id: "item-a" }),
        row({ ingredient_id: "b", recommended_item_id: "item-b" }),
      ]),
    );
    const { result } = renderDeduction();

    let outcome!: Awaited<ReturnType<typeof result.current.deduct>>;
    await act(async () => {
      outcome = await result.current.deduct(4, "failed");
    });

    expect(mocks.startPicking).toHaveBeenCalledWith("r-1", 4);
    expect(mocks.scanPicking).toHaveBeenCalledWith("r-1", "sess-1", {
      item_id: "item-a",
    });
    expect(mocks.scanPicking).toHaveBeenCalledWith("r-1", "sess-1", {
      item_id: "item-b",
    });
    expect(mocks.completePicking).toHaveBeenCalledWith("r-1", "sess-1");
    expect(outcome).toMatchObject({
      kind: "done",
      outcome: { sessionId: "sess-1", taken: 2, notTaken: [] },
    });
  });

  it("leaves a refused row untaken and says which one and why", async () => {
    mocks.startPicking.mockResolvedValue(
      startResponse([
        row({
          ingredient_id: "a",
          name: "Flour",
          recommended_item_id: "item-a",
        }),
        row({
          ingredient_id: "b",
          name: "Milk",
          recommended_item_id: "item-b",
        }),
      ]),
    );
    mocks.scanPicking
      .mockResolvedValueOnce(pickedResult())
      .mockResolvedValueOnce(
        pickedResult({
          status: "unit_mismatch",
          ingredient_id: "b",
          ingredient_name: "Milk",
          quantity_consumed: null,
          unit_mismatch: {
            required_quantity: 0.5,
            required_uom: "l",
            available_quantity: 2,
            available_uom: "pcs",
          },
        }),
      );
    const { result } = renderDeduction();

    let outcome!: Awaited<ReturnType<typeof result.current.deduct>>;
    await act(async () => {
      outcome = await result.current.deduct(4, "failed");
    });

    expect(outcome.kind).toBe("done");
    if (outcome.kind !== "done") return;
    expect(outcome.outcome.taken).toBe(1);
    expect(outcome.outcome.notTaken).toEqual([
      {
        name: "Milk",
        reason: "unit_mismatch",
        detail: {
          required: "0.5",
          requiredUom: "l",
          available: "2",
          availableUom: "pcs",
        },
      },
    ]);
    // The refused row does not stop the road: the session still completes.
    expect(mocks.completePicking).toHaveBeenCalledWith("r-1", "sess-1");
  });

  it("never scans a row the shelf cannot name", async () => {
    mocks.startPicking.mockResolvedValue(
      startResponse([
        row({
          ingredient_id: "a",
          status: "missing",
          recommended_item_id: null,
        }),
        row({
          ingredient_id: "b",
          name: "Salt",
          status: "pending",
          recommended_item_id: "item-b",
        }),
        row({ ingredient_id: "c", status: "skipped", name: "Water" }),
      ]),
    );
    const { result } = renderDeduction();

    let outcome!: Awaited<ReturnType<typeof result.current.deduct>>;
    await act(async () => {
      outcome = await result.current.deduct(2, "failed");
    });

    expect(mocks.scanPicking).toHaveBeenCalledTimes(1);
    expect(mocks.scanPicking).toHaveBeenCalledWith("r-1", "sess-1", {
      item_id: "item-b",
    });
    if (outcome.kind !== "done") return;
    expect(outcome.outcome.taken).toBe(1);
    expect(outcome.outcome.notTaken).toEqual([
      { name: "Flour", reason: "nothing_on_shelf" },
    ]);
  });

  it("refuses to deduct under an older session opened for other servings", async () => {
    mocks.startPicking.mockResolvedValue(
      startResponse([row({})], { resumed: true, servings: 8 }),
    );
    const { result } = renderDeduction();

    let outcome!: Awaited<ReturnType<typeof result.current.deduct>>;
    await act(async () => {
      outcome = await result.current.deduct(4, "failed");
    });

    expect(outcome).toEqual({ kind: "blocked" });
    expect(mocks.scanPicking).not.toHaveBeenCalled();
    expect(mocks.completePicking).not.toHaveBeenCalled();
  });

  it("a retry walks on over the rows the first pass already took", async () => {
    mocks.startPicking.mockResolvedValue(
      startResponse(
        [
          row({ ingredient_id: "a", status: "picked" }),
          row({ ingredient_id: "b", recommended_item_id: "item-b" }),
        ],
        { resumed: true },
      ),
    );
    const { result } = renderDeduction();

    let outcome!: Awaited<ReturnType<typeof result.current.deduct>>;
    await act(async () => {
      outcome = await result.current.deduct(4, "failed");
    });

    // The picked row is not scanned again (that would read "already picked");
    // the resumed session's own servings let the retry proceed.
    expect(mocks.scanPicking).toHaveBeenCalledTimes(1);
    if (outcome.kind !== "done") return;
    expect(outcome.outcome.taken).toBe(2);
  });

  it("reports how far a mid-run failure got, with the session it broke on", async () => {
    mocks.startPicking.mockResolvedValue(
      startResponse([
        row({ ingredient_id: "a", recommended_item_id: "item-a" }),
        row({ ingredient_id: "b", recommended_item_id: "item-b" }),
      ]),
    );
    mocks.scanPicking
      .mockResolvedValueOnce(pickedResult())
      .mockRejectedValueOnce(new Error("network gone"));
    const { result } = renderDeduction();

    let outcome!: Awaited<ReturnType<typeof result.current.deduct>>;
    await act(async () => {
      outcome = await result.current.deduct(4, "the road broke");
    });

    // A transport failure is not an API refusal — the reader gets the screen's
    // own sentence, not the raw error text (extractApiError's contract).
    expect(outcome).toEqual({
      kind: "failed",
      message: "the road broke",
      sessionId: "sess-1",
      taken: 1,
      total: 2,
    });
    expect(mocks.completePicking).not.toHaveBeenCalled();
  });

  it("completing the session counts as taken across the whole checklist", async () => {
    mocks.startPicking.mockResolvedValue(
      startResponse([
        row({ ingredient_id: "a" }),
        row({ ingredient_id: "b" }),
        row({ ingredient_id: "c" }),
        row({ ingredient_id: "w", status: "skipped", name: "Water" }),
      ]),
    );
    const { result } = renderDeduction();

    let outcome!: Awaited<ReturnType<typeof result.current.deduct>>;
    await act(async () => {
      outcome = await result.current.deduct(4, "failed");
    });

    if (outcome.kind !== "done") return;
    // The skipped row (a zero-quantity ingredient) belongs to no dinner.
    expect(outcome.outcome.taken).toBe(3);
  });
});

/**
 * The walk is a picking session without a sheet, and the shelves behind it
 * need the same news: an item list opened before the deduction sat under a
 * five-minute staleTime with no refetch on focus, so it showed the stock
 * from before the meal for as long as the reader stayed on it.
 */
describe("useStockDeduction — the stock views the walk moved", () => {
  it("invalidates them when the walk took something off the shelf", async () => {
    const { result, client } = renderDeduction();
    seedStockViews(client, "r-1");

    await act(async () => {
      await result.current.deduct(4, "failed");
    });

    for (const key of stockSurfaces("r-1")) {
      expect(client.getQueryState(key)?.isInvalidated).toBe(true);
    }
  });

  it("invalidates them when a mid-run failure had already taken something", async () => {
    // The screen says what was taken stays taken — that has to be true of
    // the item list too, not only of the server.
    mocks.startPicking.mockResolvedValue(
      startResponse([
        row({ ingredient_id: "a", recommended_item_id: "item-a" }),
        row({ ingredient_id: "b", recommended_item_id: "item-b" }),
      ]),
    );
    mocks.scanPicking
      .mockResolvedValueOnce(pickedResult())
      .mockRejectedValueOnce(new Error("network gone"));
    const { result, client } = renderDeduction();
    seedStockViews(client, "r-1");

    await act(async () => {
      await result.current.deduct(4, "the road broke");
    });

    for (const key of stockSurfaces("r-1")) {
      expect(client.getQueryState(key)?.isInvalidated).toBe(true);
    }
  });

  it("leaves them alone when the walk never touched the shelf", async () => {
    // A session opened for other servings is somebody else's half-finished
    // checklist: this walk refuses to touch it, so no stock view moves.
    mocks.startPicking.mockResolvedValue(
      startResponse([row({})], { resumed: true, servings: 8 }),
    );
    const { result, client } = renderDeduction();
    seedStockViews(client, "r-1");

    await act(async () => {
      await result.current.deduct(4, "failed");
    });

    for (const key of stockSurfaces("r-1")) {
      expect(client.getQueryState(key)?.isInvalidated).toBe(false);
    }
  });
});
