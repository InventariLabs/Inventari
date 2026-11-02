import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { QueryWrapper } from "@/test/queryWrapper";
import { usePickingSession } from "./usePickingSession";

/**
 * "Use opened" has to swap the pack, not close the overlay.
 *
 * The suggestion arrives after the sealed pack was already taken off the
 * shelf. The button asked the resolver for the opened pack, whose first line
 * returns unless the phase is a disambiguation or a FEFO mismatch, so no
 * request left and the overlay just closed. It now puts the sealed pick back
 * and picks the opened pack in its place.
 */

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const session = {
  picking_session_id: "session-abc",
  recipe_name: "Pancakes",
  servings: 2,
  items_to_pick: [
    {
      ingredient_id: "ing-1",
      name: "Flour",
      quantity_to_pick: 100,
      uom_symbol: "g",
      recommended_item_id: "item-sealed",
      location: "Shelf",
      fefo_days_left: null,
      fefo_expiry_date: null,
      status: "pending" as const,
    },
  ],
};

const sealedPicked = {
  status: "picked",
  ingredient_id: "ing-1",
  ingredient_name: "Flour",
  quantity_consumed: 100,
  uom_symbol: "g",
  session_complete: false,
  message: "picked",
  opened_suggestion: {
    opened_item_id: "item-opened",
    opened_quantity: 0.75,
    opened_uom: "pcs",
    opened_location: "Shelf",
    opened_expiry: null,
  },
};

const openedPicked = {
  status: "picked",
  ingredient_id: "ing-1",
  ingredient_name: "Flour",
  quantity_consumed: 100,
  uom_symbol: "g",
  session_complete: false,
  message: "picked",
};

const statusOfFirstItem = (state: unknown) =>
  (state as { items: { status: string }[] }).items[0].status;

describe("usePickingSession — Use opened swaps the pack", () => {
  const calls: string[] = [];
  const scanBodies: unknown[] = [];

  beforeEach(() => {
    vi.clearAllMocks();
    calls.length = 0;
    scanBodies.length = 0;
    server.use(
      http.post("/api/v1/recipes/:id/picking/start", () =>
        HttpResponse.json(session),
      ),
      http.post(
        "/api/v1/recipes/:id/picking/:sessionId/scan",
        async ({ request }) => {
          const body = await request.json();
          scanBodies.push(body);
          calls.push("scan");
          return HttpResponse.json(
            (body as { item_id: string }).item_id === "item-opened"
              ? openedPicked
              : sealedPicked,
          );
        },
      ),
      http.post("/api/v1/recipes/:id/picking/:sessionId/undo", () => {
        calls.push("undo");
        return HttpResponse.json({
          ingredient_id: "ing-1",
          restored_quantity: 100,
        });
      }),
    );
  });

  async function atTheSuggestion() {
    const utils = renderHook(() => usePickingSession("recipe-1"), {
      wrapper: QueryWrapper,
    });
    await act(async () => {
      await utils.result.current.startSession(2);
    });
    await act(async () => {
      await utils.result.current.scan({ item_id: "item-sealed" });
    });
    expect(utils.result.current.state.phase).toBe("opened_suggestion");
    return utils;
  }

  it("puts the sealed pick back and picks the opened pack", async () => {
    const { result } = await atTheSuggestion();

    await act(async () => {
      await result.current.resolveDisambiguation("item-opened");
    });

    expect(calls).toEqual(["scan", "undo", "scan"]);
    expect(scanBodies[1]).toEqual({ item_id: "item-opened" });
    expect(result.current.state.phase).toBe("active");
    expect(statusOfFirstItem(result.current.state)).toBe("picked");
  });

  it("keeps the sealed pick, and says why, when the undo is refused", async () => {
    const { result } = await atTheSuggestion();
    server.use(
      http.post("/api/v1/recipes/:id/picking/:sessionId/undo", () =>
        HttpResponse.json({ detail: "refused" }, { status: 400 }),
      ),
    );

    await act(async () => {
      await result.current.resolveDisambiguation("item-opened");
    });

    expect(calls).toEqual(["scan"]);
    expect(result.current.state.phase).toBe("opened_suggestion");
    expect(result.current.error).not.toBeNull();
  });
});
