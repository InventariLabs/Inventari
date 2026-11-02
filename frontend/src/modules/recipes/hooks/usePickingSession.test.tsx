import type { ReactNode } from "react";
import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { usePickingSession } from "./usePickingSession";
import { queryKeys } from "@/hooks/queries/keys";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

/** The hook reads the shared query client, so it renders under a real one —
 *  the invalidation the sheet has to leave behind is read off that client,
 *  not off a spy. */
function renderPicking(recipeId = "recipe-1") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const rendered = renderHook(() => usePickingSession(recipeId), { wrapper });
  return { ...rendered, client };
}

const mockPickingStartResponse = {
  picking_session_id: "session-abc",
  recipe_name: "Pasta",
  servings: 2,
  items_to_pick: [
    {
      ingredient_id: "ing-1",
      name: "Spaghetti",
      quantity_to_pick: 200,
      uom_symbol: "g",
      recommended_item_id: null,
      location: "Pantry",
      fefo_days_left: null,
      fefo_expiry_date: null,
      status: "pending" as const,
    },
  ],
};

describe("usePickingSession", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.post("/api/v1/recipes/:id/picking/start", () =>
        HttpResponse.json(mockPickingStartResponse),
      ),
    );
  });

  it("starts in idle phase", () => {
    const { result } = renderPicking();
    expect(result.current.state.phase).toBe("idle");
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("transitions to active phase after startSession", async () => {
    const { result } = renderPicking();

    await act(async () => {
      await result.current.startSession(2);
    });

    expect(result.current.state.phase).toBe("active");
    expect(result.current.isLoading).toBe(false);
    if (result.current.state.phase === "active") {
      expect(result.current.state.items).toHaveLength(1);
      expect(result.current.state.session.picking_session_id).toBe(
        "session-abc",
      );
    }
  });

  it("sets error when startSession fails", async () => {
    server.use(
      http.post("/api/v1/recipes/:id/picking/start", () =>
        HttpResponse.json({ detail: "Recipe not found" }, { status: 404 }),
      ),
    );
    const { result } = renderPicking("bad-recipe");

    await act(async () => {
      await result.current.startSession(1);
    });

    expect(result.current.error).not.toBeNull();
    expect(result.current.state.phase).toBe("idle");
  });

  it("resets to idle phase via reset()", async () => {
    const { result } = renderPicking();

    await act(async () => {
      await result.current.startSession(2);
    });
    expect(result.current.state.phase).toBe("active");

    act(() => {
      result.current.reset();
    });
    expect(result.current.state.phase).toBe("idle");
    expect(result.current.error).toBeNull();
  });

  it("cancels session and transitions to cancelled phase", async () => {
    server.use(
      http.delete(
        "/api/v1/recipes/:id/picking/:sessionId",
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
    const { result } = renderPicking();

    await act(async () => {
      await result.current.startSession(2);
    });
    await act(async () => {
      await result.current.cancelSession();
    });

    expect(result.current.state.phase).toBe("cancelled");
  });

  it("ends the session in the database when the last ingredient is picked", async () => {
    // The sheet used to go straight to "complete" and show "Completed ✓" on
    // the card, while the session stayed `active` in the database. Nothing
    // could close it afterwards, and the next "Take from stock" cancelled it
    // and put every ingredient back on the shelf — a meal that had been
    // cooked, un-cooked, silently.
    let completeCalls = 0;
    server.use(
      http.post("/api/v1/recipes/:id/picking/:sessionId/scan", () =>
        HttpResponse.json({
          status: "picked",
          ingredient_id: "ing-1",
          ingredient_name: "Spaghetti",
          quantity_consumed: 200,
          uom_symbol: "g",
          session_complete: true,
          message: "picked",
        }),
      ),
      http.post("/api/v1/recipes/:id/picking/:sessionId/complete", () => {
        completeCalls += 1;
        return HttpResponse.json({
          status: "completed",
          session_id: "session-abc",
        });
      }),
    );
    const { result, client } = renderPicking();
    client.setQueryDefaults(queryKeys.stockQuants.all, { gcTime: Infinity });
    client.setQueryData(queryKeys.stockQuants.all, {});

    await act(async () => {
      await result.current.startSession(2);
    });
    await act(async () => {
      await result.current.scan({ item_id: "item-1" });
    });

    expect(completeCalls).toBe(1);
    expect(result.current.state.phase).toBe("complete");
    // The auto-finish rode on a pick that moved stock, so the views behind
    // the sheet refresh without waiting for the manual close.
    expect(client.getQueryState(queryKeys.stockQuants.all)?.isInvalidated).toBe(
      true,
    );
  });

  it("says when the session it opened was already in progress", async () => {
    server.use(
      http.post("/api/v1/recipes/:id/picking/start", () =>
        HttpResponse.json({ ...mockPickingStartResponse, resumed: true }),
      ),
    );
    const { result } = renderPicking();

    const session = await act(async () => result.current.startSession(2));

    expect(session?.resumed).toBe(true);
    expect(result.current.state.phase).toBe("active");
  });
});

/**
 * The sheet takes stock off the shelf, and the screens behind it — an item
 * list, an item card, the movement ledger, the quants, the lots, the
 * recipe's own availability — used to keep the shelf from before the scan
 * for the whole five-minute staleTime, with no refetch on focus. The sheet
 * reached for the API directly and invalidated nothing.
 */
describe("usePickingSession — the stock views behind the sheet", () => {
  beforeEach(() => {
    server.use(
      http.post("/api/v1/recipes/:id/picking/start", () =>
        HttpResponse.json(mockPickingStartResponse),
      ),
    );
  });

  const stockSurfaces = (recipeId: string) => [
    queryKeys.items.all,
    queryKeys.stockMoves.all,
    queryKeys.stockQuants.all,
    queryKeys.stockLots.all,
    queryKeys.recipes.availability(recipeId, 2),
    queryKeys.recipes.available(),
  ];

  const seedOpenStockViews = (client: QueryClient, recipeId: string) => {
    for (const key of stockSurfaces(recipeId)) {
      // The harness collects a query the moment nothing observes it
      // (gcTime 0) and these have no component mounted; the per-key
      // override keeps them alive across the awaited calls so the
      // invalidation they carry can be read back.
      client.setQueryDefaults(key, { gcTime: Infinity });
      client.setQueryData(key, {});
    }
  };

  const expectEveryStockViewInvalidated = (
    client: QueryClient,
    recipeId: string,
  ) => {
    for (const key of stockSurfaces(recipeId)) {
      expect(client.getQueryState(key)?.isInvalidated).toBe(true);
    }
  };

  it("invalidates them when a scan takes something off the shelf", async () => {
    server.use(
      http.post("/api/v1/recipes/:id/picking/:sessionId/scan", () =>
        HttpResponse.json({
          status: "picked",
          ingredient_id: "ing-1",
          ingredient_name: "Spaghetti",
          quantity_consumed: 200,
          uom_symbol: "g",
          session_complete: false,
          message: "picked",
        }),
      ),
    );
    const { result, client } = renderPicking();
    seedOpenStockViews(client, "recipe-1");

    await act(async () => {
      await result.current.startSession(2);
    });
    await act(async () => {
      await result.current.scan({ item_id: "item-1" });
    });

    expectEveryStockViewInvalidated(client, "recipe-1");
  });

  it("invalidates them when an undo puts the stock back", async () => {
    server.use(
      http.post("/api/v1/recipes/:id/picking/:sessionId/undo", () =>
        HttpResponse.json({
          status: "undone",
          ingredient_id: "ing-1",
          ingredient_name: "Spaghetti",
          quantity_restored: 200,
          uom_symbol: "g",
          message: "undone",
        }),
      ),
    );
    const { result, client } = renderPicking();
    seedOpenStockViews(client, "recipe-1");

    await act(async () => {
      await result.current.startSession(2);
    });
    await act(async () => {
      await result.current.undoPick("ing-1");
    });

    expectEveryStockViewInvalidated(client, "recipe-1");
  });

  it("invalidates them when a cancel puts every pick back", async () => {
    server.use(
      http.delete(
        "/api/v1/recipes/:id/picking/:sessionId",
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
    const { result, client } = renderPicking();
    seedOpenStockViews(client, "recipe-1");

    await act(async () => {
      await result.current.startSession(2);
    });
    await act(async () => {
      await result.current.cancelSession();
    });

    expectEveryStockViewInvalidated(client, "recipe-1");
  });

  it("leaves them alone when the scan was refused", async () => {
    server.use(
      http.post("/api/v1/recipes/:id/picking/:sessionId/scan", () =>
        HttpResponse.json({
          status: "unit_mismatch",
          ingredient_id: "ing-1",
          ingredient_name: "Spaghetti",
          quantity_consumed: null,
          session_complete: false,
          message: "no",
          unit_mismatch: {
            required_quantity: 200,
            required_uom: "g",
            available_quantity: 2,
            available_uom: "pcs",
          },
        }),
      ),
    );
    const { result, client } = renderPicking();
    seedOpenStockViews(client, "recipe-1");

    await act(async () => {
      await result.current.startSession(2);
    });
    await act(async () => {
      await result.current.scan({ item_id: "item-1" });
    });

    for (const key of stockSurfaces("recipe-1")) {
      expect(client.getQueryState(key)?.isInvalidated).toBe(false);
    }
  });
});
