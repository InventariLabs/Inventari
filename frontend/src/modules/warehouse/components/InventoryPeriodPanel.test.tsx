import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { toast } from "sonner";
import { render, screen, within, fireEvent } from "@/test/utils";

import InventoryPeriodPanel from "./InventoryPeriodPanel";
import { signInWith, signOut } from "@/test/auth";

// This screen hides its actions from an account that cannot use them,
// so a spec about the actions has to say who is looking at them.
beforeEach(() => {
  signInWith(["warehouse:read", "warehouse:write", "warehouse:manage"]);
});

afterEach(() => {
  signOut();
});

const periods = vi.hoisted(() => ({ current: [] as unknown[] }));

const mutationFns = vi.hoisted(() => ({
  reopenMutate: vi.fn(),
}));

vi.mock("@/modules/warehouse/hooks/useInventoryPeriods", () => ({
  useInventoryPeriods: () => ({ data: periods.current, isLoading: false }),
  useClosePeriod: () => ({ mutate: vi.fn(), isPending: false }),
  useReopenPeriod: () => ({
    mutate: mutationFns.reopenMutate,
    isPending: false,
  }),
}));

beforeEach(() => {
  periods.current = [];
});

/** The tile for a month of the year the panel opens on. */
function tileFor(month: number): HTMLElement {
  const name = new Date(new Date().getFullYear(), month - 1).toLocaleString(
    "en",
    { month: "long" },
  );
  const label = screen.getByText(new RegExp(`^${name}$`, "i"));
  return label.closest("div.flex.items-start.justify-between") as HTMLElement;
}

describe("InventoryPeriodPanel", () => {
  it("offers no padlock on a month that has not happened yet", () => {
    const currentMonth = new Date().getMonth() + 1;
    if (currentMonth === 12) return; // December has no future month in its own year

    render(<InventoryPeriodPanel />);

    const future = tileFor(currentMonth + 1);
    expect(within(future).queryByRole("button")).toBeNull();
    expect(within(future).getByText("Not started yet")).toBeInTheDocument();
  });

  // Measured at 390px: two columns of tiles leave 133px, and "Październik"
  // (71px) plus "Jeszcze się nie zaczął" do not share that line. The name
  // overflowed its own column and was painted over the status — two texts on
  // top of each other, on the screen that closes a month for good. jsdom has
  // no layout, so what is pinned is where the status lives: in the name's
  // column, under it, rather than in the slot the action shares.
  it("puts the status of a future month in the name's column, not beside it", () => {
    const currentMonth = new Date().getMonth() + 1;
    if (currentMonth === 12) return;

    render(<InventoryPeriodPanel />);

    const future = tileFor(currentMonth + 1);
    const status = within(future).getByText("Not started yet");
    const name = within(future).getByText(
      new RegExp(
        `^${new Date(new Date().getFullYear(), currentMonth).toLocaleString(
          "en",
          { month: "long" },
        )}$`,
        "i",
      ),
    );

    expect(name.closest("div.min-w-0")).toContainElement(status);
  });

  // Measured at 320px: two columns leave a 101px tile, the padlock takes 40
  // of them, and the name — one word, nothing to break on — was drawn across
  // the button. jsdom has no layout, so what is pinned is the rule that keeps
  // the pair apart: one column until 480px.
  it("gives a month a column of its own on the narrowest phones", () => {
    render(<InventoryPeriodPanel />);

    const grid = tileFor(1).parentElement as HTMLElement;

    expect(grid.className).toContain("grid-cols-1");
    expect(grid.className).toContain("min-[480px]:grid-cols-2");
  });

  it("keeps the padlock on a month that is over", () => {
    const currentMonth = new Date().getMonth() + 1;
    if (currentMonth === 1) return; // January has no past month in its own year

    render(<InventoryPeriodPanel />);

    const past = tileFor(currentMonth - 1);
    expect(within(past).getByRole("button")).toBeInTheDocument();
  });

  it("marks which month is the current one", () => {
    render(<InventoryPeriodPanel />);

    const current = tileFor(new Date().getMonth() + 1);
    expect(within(current).getByText("Current")).toBeInTheDocument();
  });

  it("names an open month that is over instead of leaving it blank", () => {
    // Every other state of a month had a word — Closed, Reopened, Current,
    // Not started yet — and the one that takes documents again showed the
    // name and nothing else, the picture a reader takes for "nothing here".
    const currentMonth = new Date().getMonth() + 1;
    if (currentMonth === 1) return; // January has no past month in its own year

    render(<InventoryPeriodPanel />);

    const past = tileFor(currentMonth - 1);
    expect(within(past).getByText("Open")).toBeInTheDocument();
  });

  it("tells a month that was unlocked apart from one nobody touched", () => {
    // Both used to be an empty cell, while the API had been sending
    // `reopened_at`, `reopened_by` and the note all along.
    const month = new Date().getMonth() + 1 === 1 ? 2 : 1;
    periods.current = [
      {
        id: "p-1",
        year: new Date().getFullYear(),
        month,
        // Reopening keeps `closed_at` — the evidence of the closure — so the
        // state is its own field. The screen used to read that column and
        // nothing else, which is why the row went blank.
        is_closed: false,
        closed_at: "2026-04-01T09:00:00Z",
        closed_by: "QA Many Admin",
        reopened_at: "2026-04-08T14:30:00Z",
        reopened_by: "QA Many Admin",
        notes: "Correction to the March count",
      },
    ];

    render(<InventoryPeriodPanel />);

    const tile = tileFor(month);
    expect(within(tile).getByText("Reopened")).toBeInTheDocument();
    expect(within(tile).getByText(/QA Many Admin/)).toBeInTheDocument();
    expect(
      within(tile).getByText("Correction to the March count"),
    ).toBeInTheDocument();
  });

  it("hands the server sentence to the toast, in the language it arrived", () => {
    // The refusal is the server's own sentence — translated by the backend
    // catalog and carried in `detail.message`. The panel passes it through
    // `extractApiError` instead of hiding it behind the generic fallback, so
    // a Polish reader reads Polish.
    //
    // Scope, stated plainly: this is a control of the panel's own
    // pass-through, not of the backend translation. The envelope is built by
    // hand here, so reversing the backend service migration leaves this test
    // green (measured); the backend sentence's own coverage lives in the
    // documents integration tests.
    //
    // The screen reaches this refusal through stale client state — this
    // operator's browser still offers the padlock after another operator
    // has closed the period — which is exactly the path the translated
    // sentence exists for.
    const toastError = vi.spyOn(toast, "error").mockImplementation(() => "");
    const month = new Date().getMonth() + 1 === 1 ? 2 : 1;
    periods.current = [
      {
        id: "p-9",
        year: new Date().getFullYear(),
        month,
        is_closed: true,
        closed_at: "2026-04-01T09:00:00Z",
        closed_by: "QA Admin",
        reopened_at: null,
        reopened_by: null,
        notes: null,
      },
    ];

    render(<InventoryPeriodPanel />);

    const tile = tileFor(month);
    fireEvent.click(within(tile).getByRole("button"));

    // The padlock opens the shared confirm dialog; confirming is what fires
    // the mutation whose failure the toast will carry.
    const dialogButtons = screen.getAllByRole("button");
    fireEvent.click(dialogButtons[dialogButtons.length - 1] as HTMLElement);

    expect(mutationFns.reopenMutate).toHaveBeenCalled();
    const handlers = mutationFns.reopenMutate.mock.calls[0][1];
    handlers.onError({
      isAxiosError: true,
      response: {
        status: 409,
        data: {
          detail: {
            code: "PERIOD_CLOSED",
            message: "Okres 2026-09 nie jest zamknięty.",
            lang: "pl",
          },
        },
      },
    });

    expect(toastError).toHaveBeenCalledWith(
      "Okres 2026-09 nie jest zamknięty.",
    );
    toastError.mockRestore();
  });

  it("names both padlocks and the year", () => {
    // Eight buttons announced as "button", the icon the only thing saying
    // whether the click locks the month or unlocks it.
    const month = new Date().getMonth() + 1 === 1 ? 2 : 1;
    periods.current = [
      {
        id: "p-1",
        year: new Date().getFullYear(),
        month,
        is_closed: true,
        closed_at: "2026-04-01T09:00:00Z",
        closed_by: "QA Many Admin",
        reopened_at: null,
        reopened_by: null,
        notes: null,
      },
    ];

    render(<InventoryPeriodPanel />);

    expect(screen.getByRole("button", { name: /^Reopen/ })).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: /^Close/ }).length,
    ).toBeGreaterThan(0);
    expect(screen.getByLabelText("Year")).toBeInTheDocument();
  });
});
