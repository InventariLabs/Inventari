import type { ReactNode } from "react";
import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { queryKeys } from "@/hooks/queries/keys";
import { usePickingSession } from "./usePickingSession";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

/**
 * The close is what writes a finished session into the recipe's cooking
 * history. The history used to be refreshed on the scan before it, so a panel
 * opened beforehand refetched while the session was still open and kept
 * reading "No completed cooking sessions yet" after the card said Completed.
 */

const start = {
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

const lastPick = {
  status: "picked",
  ingredient_id: "ing-1",
  ingredient_name: "Spaghetti",
  quantity_consumed: 200,
  uom_symbol: "g",
  session_complete: true,
  message: "picked",
};

const historyKey = JSON.stringify(queryKeys.recipes.history("recipe-1"));

/** Events in the order they happened: the close request and every history
 *  invalidation. */
async function openSession() {
  const events: string[] = [];
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const invalidate = client.invalidateQueries.bind(client);
  vi.spyOn(client, "invalidateQueries").mockImplementation((filters) => {
    if (JSON.stringify(filters?.queryKey) === historyKey) {
      events.push("history invalidated");
    }
    return invalidate(filters);
  });
  server.use(
    http.post("/api/v1/recipes/:id/picking/start", () =>
      HttpResponse.json(start),
    ),
    http.post("/api/v1/recipes/:id/picking/:sessionId/complete", () => {
      events.push("closed");
      return HttpResponse.json({ status: "completed" });
    }),
  );
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook(() => usePickingSession("recipe-1"), { wrapper });
  await act(async () => {
    await hook.result.current.startSession(2);
  });
  return { ...hook, events };
}

describe("usePickingSession — the history refreshes after the close", () => {
  beforeEach(() => vi.clearAllMocks());

  it("refreshes after the last scan closes the session", async () => {
    const { result, events } = await openSession();
    server.use(
      http.post("/api/v1/recipes/:id/picking/:sessionId/scan", () =>
        HttpResponse.json(lastPick),
      ),
    );

    await act(async () => {
      await result.current.scan({ item_id: "item-1" });
    });

    expect(result.current.state.phase).toBe("complete");
    expect(events.at(-1)).toBe("history invalidated");
    expect(events.indexOf("closed")).toBeLessThan(
      events.lastIndexOf("history invalidated"),
    );
  });

  it("refreshes after a disambiguation answer closes the session", async () => {
    const { result, events } = await openSession();
    server.use(
      http.post(
        "/api/v1/recipes/:id/picking/:sessionId/scan",
        () =>
          HttpResponse.json({
            ...lastPick,
            status: "disambiguation_required",
            session_complete: false,
            candidates: [],
          }),
        { once: true },
      ),
      http.post("/api/v1/recipes/:id/picking/:sessionId/scan", () =>
        HttpResponse.json(lastPick),
      ),
    );
    await act(async () => {
      await result.current.scan({ barcode: "123" });
    });
    expect(result.current.state.phase).toBe("disambiguation");

    await act(async () => {
      await result.current.resolveDisambiguation("item-1");
    });

    expect(result.current.state.phase).toBe("complete");
    expect(events.at(-1)).toBe("history invalidated");
    expect(events.indexOf("closed")).toBeLessThan(
      events.lastIndexOf("history invalidated"),
    );
  });

  it("refreshes after dismissing an opened-pack suggestion closes the session", async () => {
    const { result, events } = await openSession();
    server.use(
      http.post("/api/v1/recipes/:id/picking/:sessionId/scan", () =>
        HttpResponse.json({ ...lastPick, opened_suggestion: { item_id: "x" } }),
      ),
    );
    await act(async () => {
      await result.current.scan({ item_id: "item-1" });
    });
    expect(result.current.state.phase).toBe("opened_suggestion");
    events.length = 0;

    await act(async () => {
      await result.current.dismissOpenedSuggestion();
    });

    expect(result.current.state.phase).toBe("complete");
    expect(events).toEqual(["closed", "history invalidated"]);
  });
});
