/**
 * The thread between picking and cooking is pulled once.
 *
 * Picking the ingredients and then cooking them is one dinner, so the cook
 * names the run the picking opened. But the name stayed in the flow after it
 * was used: cooking the same recipe a second time from the same card handed
 * over the same run again, and the second rating overwrote the first
 * evening's — one entry where there were two meals.
 *
 * Consumed once, then. And only when it really was consumed: a cook closed
 * without recording anything has not used the thread, and the dinner it was
 * picked for is still waiting to be cooked.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { useState } from "react";
import { RecipeCookingFlow } from "./RecipeCookingFlow";

const seen = vi.hoisted(() => ({ sessionIds: [] as (string | undefined)[] }));

vi.mock("./PickingView", () => ({
  default: ({
    onClose,
  }: {
    onClose: (completed?: boolean, sessionId?: string) => void;
  }) => (
    <button onClick={() => onClose(true, "picked-1")}>finish picking</button>
  ),
}));

vi.mock("./CookingMode", () => ({
  default: ({
    pickingSessionId,
    onSessionConsumed,
    onClose,
  }: {
    pickingSessionId?: string;
    onSessionConsumed?: () => void;
    onClose: () => void;
  }) => {
    seen.sessionIds.push(pickingSessionId);
    return (
      <div>
        <button
          onClick={() => {
            onSessionConsumed?.();
            onClose();
          }}
        >
          record and close
        </button>
        <button onClick={onClose}>abandon</button>
      </div>
    );
  },
}));

/** Mirrors what the recipe page does with the two screens. */
function Harness() {
  const [picking, setPicking] = useState(true);
  const [cooking, setCooking] = useState(false);

  return (
    <>
      <button onClick={() => setCooking(true)}>cook</button>
      <RecipeCookingFlow
        recipeId="r1"
        recipeName="Pancakes"
        instructions={"1. Mix\n2. Fry"}
        activeServings={3}
        baseServings={2}
        picking={picking}
        cooking={cooking}
        onPickingClose={() => {
          setPicking(false);
        }}
        onCookingClose={() => {
          setCooking(false);
        }}
      />
    </>
  );
}

function pickThenCook() {
  fireEvent.click(screen.getByRole("button", { name: "finish picking" }));
  fireEvent.click(screen.getByRole("button", { name: "cook" }));
}

beforeEach(() => {
  seen.sessionIds = [];
});

describe("RecipeCookingFlow — the thread is pulled once", () => {
  it("hands the picked run to the cook that follows it", () => {
    render(<Harness />);

    pickThenCook();

    expect(seen.sessionIds[seen.sessionIds.length - 1]).toBe("picked-1");
  });

  it("does not hand the same run to a second cook", () => {
    render(<Harness />);
    pickThenCook();

    fireEvent.click(screen.getByRole("button", { name: "record and close" }));
    fireEvent.click(screen.getByRole("button", { name: "cook" }));

    // The first dinner owns that run now; this one opens its own entry.
    expect(seen.sessionIds[seen.sessionIds.length - 1]).toBeUndefined();
  });

  it("keeps the run when the cook was closed without recording anything", () => {
    render(<Harness />);
    pickThenCook();

    fireEvent.click(screen.getByRole("button", { name: "abandon" }));
    fireEvent.click(screen.getByRole("button", { name: "cook" }));

    // Nothing was written, so the picked dinner is still uncooked — dropping
    // the thread here would record it twice.
    expect(seen.sessionIds[seen.sessionIds.length - 1]).toBe("picked-1");
  });
});
