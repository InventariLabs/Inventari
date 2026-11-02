import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { QueryWrapper } from "@/test/queryWrapper";
import { usePickingSession } from "./usePickingSession";

/**
 * A refused scan took nothing off the shelf, and the checklist has to say so.
 *
 * The scan handler ended in a branch that wrote `status: "picked"` whatever
 * the answer said, so `unit_mismatch`, `not_in_recipe` and `already_picked` —
 * every refusal the backend has — ticked the ingredient off and moved the
 * counter. The toast telling the truth lasted a few seconds; the tick stayed,
 * the session could be completed on it, and nothing had left the shelf.
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
      name: "White sugar",
      quantity_to_pick: 100,
      uom_symbol: "g",
      recommended_item_id: "item-1",
      location: "Worktop",
      fefo_days_left: null,
      fefo_expiry_date: null,
      status: "pending" as const,
    },
  ],
};

const unitMismatch = {
  status: "unit_mismatch",
  ingredient_id: "ing-1",
  ingredient_name: "White sugar",
  quantity_consumed: null,
  session_complete: false,
  message: "Cannot compare units for White sugar",
  unit_mismatch: {
    required_quantity: 100,
    required_uom: "g",
    available_quantity: 3,
    available_uom: null,
  },
};

const picked = {
  status: "picked",
  ingredient_id: "ing-1",
  ingredient_name: "White sugar",
  quantity_consumed: 100,
  uom_symbol: "g",
  session_complete: false,
  message: "picked",
};

const scanAnswers = (...answers: Record<string, unknown>[]) => {
  let call = 0;
  server.use(
    http.post("/api/v1/recipes/:id/picking/:sessionId/scan", () => {
      const answer = answers[Math.min(call, answers.length - 1)];
      call += 1;
      return HttpResponse.json(answer);
    }),
  );
};

const statusOfFirstItem = (state: unknown) =>
  (state as { items: { status: string }[] }).items[0].status;

describe("usePickingSession — a refused scan is not a pick", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.post("/api/v1/recipes/:id/picking/start", () =>
        HttpResponse.json(session),
      ),
    );
  });

  it.each([
    ["unit_mismatch", unitMismatch],
    [
      "not_in_recipe",
      { status: "not_in_recipe", ingredient_id: "ing-1", message: "no" },
    ],
    [
      "already_picked",
      { status: "already_picked", ingredient_id: "ing-1", message: "no" },
    ],
  ])("leaves the row alone when the answer is %s", async (status, answer) => {
    scanAnswers(answer);
    const { result } = renderHook(() => usePickingSession("recipe-1"), {
      wrapper: QueryWrapper,
    });

    await act(async () => {
      await result.current.startSession(2);
    });
    await act(async () => {
      await result.current.scan({ item_id: "item-1" });
    });

    expect(result.current.state.phase).toBe("active");
    expect(statusOfFirstItem(result.current.state)).toBe("pending");
    expect(result.current.refusals["ing-1"]).toBe(status);
  });

  it("records the refusal for as long as the checklist is open", async () => {
    // The toast is gone in seconds; this is what the row reads from.
    scanAnswers(unitMismatch);
    const { result } = renderHook(() => usePickingSession("recipe-1"), {
      wrapper: QueryWrapper,
    });

    await act(async () => {
      await result.current.startSession(2);
    });
    await act(async () => {
      await result.current.scan({ item_id: "item-1" });
    });
    await act(async () => {
      await result.current.scan({ item_id: "item-1" });
    });

    expect(result.current.refusals["ing-1"]).toBe("unit_mismatch");
  });

  it("drops the refusal once the same ingredient is picked", async () => {
    scanAnswers(unitMismatch, picked);
    const { result } = renderHook(() => usePickingSession("recipe-1"), {
      wrapper: QueryWrapper,
    });

    await act(async () => {
      await result.current.startSession(2);
    });
    await act(async () => {
      await result.current.scan({ item_id: "item-1" });
    });
    expect(result.current.refusals["ing-1"]).toBe("unit_mismatch");

    await act(async () => {
      await result.current.scan({ item_id: "item-2" });
    });

    expect(result.current.refusals["ing-1"]).toBeUndefined();
    expect(statusOfFirstItem(result.current.state)).toBe("picked");
  });

  it("still ticks the row off when the answer is a pick", async () => {
    scanAnswers(picked);
    const { result } = renderHook(() => usePickingSession("recipe-1"), {
      wrapper: QueryWrapper,
    });

    await act(async () => {
      await result.current.startSession(2);
    });
    await act(async () => {
      await result.current.scan({ item_id: "item-1" });
    });

    expect(statusOfFirstItem(result.current.state)).toBe("picked");
    expect(result.current.refusals).toEqual({});
  });

  it("does not close the session on a refusal that claims completion", async () => {
    // `session_complete` used to be read before the status, so a refusal
    // carrying it would have ended the session with nothing taken.
    let completeCalls = 0;
    scanAnswers({ ...unitMismatch, session_complete: true });
    server.use(
      http.post("/api/v1/recipes/:id/picking/:sessionId/complete", () => {
        completeCalls += 1;
        return HttpResponse.json({ status: "completed" });
      }),
    );
    const { result } = renderHook(() => usePickingSession("recipe-1"), {
      wrapper: QueryWrapper,
    });

    await act(async () => {
      await result.current.startSession(2);
    });
    await act(async () => {
      await result.current.scan({ item_id: "item-1" });
    });

    expect(completeCalls).toBe(0);
    expect(result.current.state.phase).toBe("active");
  });
});
