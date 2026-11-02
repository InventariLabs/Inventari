import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FinishedScreen } from "./FinishedScreen";
import { queryKeys } from "@/hooks/queries/keys";
import type {
  PickingItem,
  PickingScanResponse,
  PickingStartResponse,
} from "../types/core";

const mocks = vi.hoisted(() => ({
  patchMutateAsync: vi.fn().mockResolvedValue({}),
  startPicking: vi.fn(),
  scanPicking: vi.fn(),
  completePicking: vi.fn(),
  cancelPicking: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/modules/recipes/hooks/useRecipes", () => ({
  useRecipeHistory: () => ({ data: [] }),
  usePatchCookingHistory: () => ({
    mutateAsync: mocks.patchMutateAsync,
    isPending: false,
  }),
}));

vi.mock("../api/recipes", () => ({
  recipesApi: {
    startPicking: mocks.startPicking,
    scanPicking: mocks.scanPicking,
    completePicking: mocks.completePicking,
    cancelPicking: mocks.cancelPicking,
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
    quantity_consumed: 500,
    uom_symbol: "g",
    item_remaining_quantity: 0,
    session_complete: true,
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

beforeEach(() => {
  mocks.patchMutateAsync.mockClear();
  mocks.startPicking.mockReset();
  mocks.scanPicking.mockReset();
  mocks.completePicking.mockReset();
  mocks.cancelPicking.mockClear();
});

function renderScreen(
  onClose = vi.fn(),
  ensureEntry: () => Promise<string> = () => Promise.resolve("own-session"),
  extra: {
    canDeduct?: boolean;
    servings?: number;
    onDeducted?: (id: string) => void;
  } = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const rendered = render(
    <QueryClientProvider client={client}>
      <FinishedScreen
        recipeId="r-1"
        recipeName="Jam"
        ensureEntry={ensureEntry}
        onClose={onClose}
        {...extra}
      />
    </QueryClientProvider>,
  );
  return { ...rendered, client };
}

/**
 * Resolves in the microtask the deduction's result reaches the DOM — the
 * frame before React's passive effects have run. RTL's own `waitFor` turns
 * the act environment off while it waits, because the updates it watches land
 * outside act by design; the same is done here, and for the same reason.
 */
async function theFrameTheResultLands() {
  const previous = (globalThis as Record<string, unknown>)
    .IS_REACT_ACT_ENVIRONMENT;
  (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = false;
  try {
    await new Promise<void>((resolve) => {
      const observer = new MutationObserver(() => {
        if (screen.queryByTestId("deduct-result")) {
          observer.disconnect();
          resolve();
        }
      });
      observer.observe(document.body, { childList: true, subtree: true });
    });
  } finally {
    (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = previous;
  }
}

describe("FinishedScreen", () => {
  /**
   * `max-w-md` in `className` lands on the inner `<textarea>` while the
   * wrapper keeps the full row, so the column's `items-center` has nothing to
   * centre and the note settles against the left edge — the icon, the title
   * and the stars are centred, the note is not. The width belongs to the box.
   */
  it("constrains the note's box, not the control inside it", () => {
    renderScreen();

    const textarea = screen.getByRole("textbox");
    expect(textarea).not.toHaveClass("max-w-md");
    expect(textarea.parentElement).toHaveClass("max-w-md");
  });

  it("sits in the column that centres it", () => {
    renderScreen();

    // The wrapper is what `items-center` acts on, so the constraint has to be
    // there for the note to line up with the icon, the title and the stars.
    const wrapper = screen.getByRole("textbox").parentElement;
    expect(wrapper?.parentElement).toHaveClass("items-center");
  });

  /**
   * It covers the whole viewport, so it is a screen standing in front of the
   * application — and until it said so, the keyboard walked the page beneath
   * it and Escape did nothing.
   */
  it("is a named dialog", () => {
    renderScreen();

    expect(screen.getByRole("dialog", { name: "Bon appétit!" })).toBeVisible();
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderScreen(onClose);

    await user.keyboard("{Escape}");

    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});

describe("FinishedScreen — the rating lands on its own cooking", () => {
  it("writes onto the entry this cooking opened, not whatever closed last", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderScreen(onClose, () => Promise.resolve("own-session"));

    await user.click(screen.getByRole("button", { name: /rate 4 star/i }));
    await user.type(screen.getByRole("textbox"), "Came out thin");
    await user.click(screen.getByRole("button", { name: /save & close/i }));

    expect(mocks.patchMutateAsync).toHaveBeenCalledWith({
      sessionId: "own-session",
      data: { notes: "Came out thin", rating: 4 },
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  /**
   * The rating is typed in the seconds after the cook ends, so the request
   * that opens the entry is usually still in flight when save is pressed.
   * Reading a session id that had not arrived yet is how a written note was
   * dropped without a word.
   */
  it("waits for a slow entry instead of dropping the note", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    let resolveEntry: (id: string) => void = () => {};
    const pending = new Promise<string>((resolve) => {
      resolveEntry = resolve;
    });
    renderScreen(onClose, () => pending);

    await user.click(screen.getByRole("button", { name: /rate 5 star/i }));
    await user.type(screen.getByRole("textbox"), "Perfect");
    await user.click(screen.getByRole("button", { name: /save & close/i }));

    expect(mocks.patchMutateAsync).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();

    resolveEntry("late-session");
    await waitFor(() =>
      expect(mocks.patchMutateAsync).toHaveBeenCalledWith({
        sessionId: "late-session",
        data: { notes: "Perfect", rating: 5 },
      }),
    );
  });

  it("keeps the note on screen and says so when the entry cannot be recorded", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderScreen(onClose, () => Promise.reject(new Error("404")));

    await user.click(screen.getByRole("button", { name: /rate 4 star/i }));
    await user.type(screen.getByRole("textbox"), "Too much salt");
    await user.click(screen.getByRole("button", { name: /save & close/i }));

    expect(mocks.patchMutateAsync).not.toHaveBeenCalled();
    // Closing here is what made a note disappear in silence.
    await waitFor(() => expect(onClose).not.toHaveBeenCalled());
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.getByRole("textbox")).toHaveValue("Too much salt");
  });

  /**
   * The entry used to be asked the moment "Done" was pressed, before the
   * finished screen had its say — but only that screen knows whether the
   * reader confirmed the deduction, and the answer decides which run the
   * entry names. So every way out records the dinner first: with nothing
   * written, the record is still asked for, and the screen still closes.
   */
  it("records the dinner even when nothing was written", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const ensureEntry = vi.fn(() => Promise.resolve("own-session"));
    renderScreen(onClose, ensureEntry);

    await user.click(screen.getByRole("button", { name: /save & close/i }));

    expect(ensureEntry).toHaveBeenCalledTimes(1);
    expect(mocks.patchMutateAsync).not.toHaveBeenCalled();
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});

describe("FinishedScreen — the shelf learns about the dinner", () => {
  it("asks only when the cook may take the ingredients itself", () => {
    const first = renderScreen(vi.fn(), undefined, {
      canDeduct: true,
      servings: 4,
    });
    expect(screen.getByTestId("deduct-section")).toBeVisible();
    first.unmount();

    renderScreen(vi.fn(), undefined, {});

    expect(screen.queryByTestId("deduct-section")).not.toBeInTheDocument();
  });

  it("a decline takes nothing and still records the dinner", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const ensureEntry = vi.fn(() => Promise.resolve("own-session"));
    renderScreen(onClose, ensureEntry, { canDeduct: true, servings: 4 });

    await user.click(screen.getByTestId("deduct-decline"));

    // Refusing moves nothing: no session is ever opened for it.
    expect(mocks.startPicking).not.toHaveBeenCalled();
    expect(screen.queryByTestId("deduct-section")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /skip/i }));

    expect(ensureEntry).toHaveBeenCalledTimes(1);
    expect(mocks.completePicking).not.toHaveBeenCalled();
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("confirming walks the picking road and hands the run to the dinner's entry", async () => {
    const user = userEvent.setup();
    const onDeducted = vi.fn();
    const ensureEntry = vi.fn(() => Promise.resolve("own-session"));
    mocks.startPicking.mockResolvedValue({
      picking_session_id: "sess-9",
      recipe_name: "Jam",
      servings: 4,
      items_to_pick: [
        row({ ingredient_id: "a", recommended_item_id: "item-a" }),
        row({ ingredient_id: "b", recommended_item_id: "item-b" }),
      ],
    } as PickingStartResponse);
    mocks.scanPicking.mockResolvedValue(pickedResult());
    mocks.completePicking.mockResolvedValue({ status: "completed" });
    renderScreen(vi.fn(), ensureEntry, {
      canDeduct: true,
      servings: 4,
      onDeducted,
    });

    await user.click(screen.getByTestId("deduct-confirm"));

    expect(await screen.findByTestId("deduct-result")).toBeVisible();
    expect(screen.getByText("2 ingredients taken")).toBeVisible();
    // The dinner's entry names the run the deduction opened — that linkage
    // is what turns the history line from "nothing picked" into "picked".
    expect(onDeducted).toHaveBeenCalledWith("sess-9");

    await user.click(screen.getByRole("button", { name: /save & close/i }));
    await waitFor(() => expect(ensureEntry).toHaveBeenCalled());
  });

  /**
   * The exit guard used to be mirrored from the hook's `running` in an effect,
   * which reports one render late on both ends. On the way in, a fast click
   * slipped past a guard that had not been raised yet; on the way out, a click
   * in the frame the result landed met a flag the next effect pass had not
   * cleared — the screen ignored it and the dinner was never recorded. The
   * frame is milliseconds wide, too narrow for a hand but not for the suite's
   * own timing: this is the click that turned a 773-file full run red.
   */
  it("records the dinner when the reader leaves the frame the result lands", async () => {
    mocks.startPicking.mockResolvedValue({
      picking_session_id: "sess-9",
      recipe_name: "Jam",
      servings: 4,
      items_to_pick: [
        row({ ingredient_id: "a", recommended_item_id: "item-a" }),
      ],
    } as PickingStartResponse);
    mocks.scanPicking.mockResolvedValue(pickedResult());
    mocks.completePicking.mockResolvedValue({ status: "completed" });
    const onClose = vi.fn();
    const ensureEntry = vi.fn(() => Promise.resolve("sess-9"));
    renderScreen(onClose, ensureEntry, { canDeduct: true, servings: 4 });

    fireEvent.click(screen.getByTestId("deduct-confirm"));
    await theFrameTheResultLands();
    fireEvent.click(screen.getByRole("button", { name: /skip/i }));

    await waitFor(() => expect(ensureEntry).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("a refused row is spelled out by name, never marked taken", async () => {
    const user = userEvent.setup();
    const onDeducted = vi.fn();
    mocks.startPicking.mockResolvedValue({
      picking_session_id: "sess-9",
      recipe_name: "Jam",
      servings: 4,
      items_to_pick: [
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
      ],
    } as PickingStartResponse);
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
    mocks.completePicking.mockResolvedValue({ status: "completed" });
    renderScreen(vi.fn(), undefined, {
      canDeduct: true,
      servings: 4,
      onDeducted,
    });

    await user.click(screen.getByTestId("deduct-confirm"));

    await screen.findByTestId("deduct-result");
    expect(screen.getByText("1 ingredient taken")).toBeVisible();
    expect(
      screen.getByText(
        "Milk — units do not match (the recipe asks for 0.5 l, the shelf holds 2 pcs)",
      ),
    ).toBeVisible();
    // The session still completes — one dinner, partly off the shelf — and
    // the entry still names it.
    expect(mocks.completePicking).toHaveBeenCalledWith("r-1", "sess-9");
    expect(onDeducted).toHaveBeenCalledWith("sess-9");
  });

  it("an older open session blocks the walk instead of deducting it", async () => {
    const user = userEvent.setup();
    const onDeducted = vi.fn();
    mocks.startPicking.mockResolvedValue({
      picking_session_id: "sess-old",
      recipe_name: "Jam",
      servings: 8,
      resumed: true,
      items_to_pick: [row({})],
    } as PickingStartResponse);
    renderScreen(vi.fn(), undefined, {
      canDeduct: true,
      servings: 4,
      onDeducted,
    });

    await user.click(screen.getByTestId("deduct-confirm"));

    expect(await screen.findByTestId("deduct-blocked")).toBeVisible();
    expect(mocks.scanPicking).not.toHaveBeenCalled();
    expect(mocks.completePicking).not.toHaveBeenCalled();
    expect(onDeducted).not.toHaveBeenCalled();
  });

  it("a broken walk offers the rest again; closing hands what was taken back", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onDeducted = vi.fn();
    const ensureEntry = vi.fn(() => Promise.resolve("own-session"));
    mocks.startPicking.mockResolvedValue({
      picking_session_id: "sess-9",
      recipe_name: "Jam",
      servings: 4,
      items_to_pick: [
        row({ ingredient_id: "a", recommended_item_id: "item-a" }),
        row({ ingredient_id: "b", recommended_item_id: "item-b" }),
      ],
    } as PickingStartResponse);
    mocks.scanPicking
      .mockResolvedValueOnce(pickedResult())
      .mockRejectedValueOnce(new Error("boom"));
    const { client } = renderScreen(onClose, ensureEntry, {
      canDeduct: true,
      servings: 4,
      onDeducted,
    });
    const invalidate = vi.spyOn(client, "invalidateQueries");

    await user.click(screen.getByTestId("deduct-confirm"));

    const failure = await screen.findByTestId("deduct-failure");
    expect(failure).toBeVisible();
    expect(screen.getByText(/Taken 1 of 2\./)).toBeVisible();

    // Closing after the break keeps the promise the failure made: the open
    // session is cancelled, which puts the taken amount back on the shelf,
    // and the dinner is recorded without naming the broken run.
    await user.click(screen.getByRole("button", { name: /skip/i }));
    expect(mocks.cancelPicking).toHaveBeenCalledWith("r-1", "sess-9");
    expect(mocks.completePicking).not.toHaveBeenCalled();
    expect(onDeducted).not.toHaveBeenCalled();
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(ensureEntry).toHaveBeenCalled();
    // The cancel put the stock back — the views showing it have to move.
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: queryKeys.stockQuants.all,
    });
  });

  it("a retry walks on over the rows the first pass took", async () => {
    const user = userEvent.setup();
    const onDeducted = vi.fn();
    mocks.startPicking
      // first pass: fresh session
      .mockResolvedValueOnce({
        picking_session_id: "sess-9",
        recipe_name: "Jam",
        servings: 4,
        items_to_pick: [
          row({ ingredient_id: "a", recommended_item_id: "item-a" }),
          row({ ingredient_id: "b", recommended_item_id: "item-b" }),
        ],
      } as PickingStartResponse)
      // retry: the same session comes back, first row already picked
      .mockResolvedValueOnce({
        picking_session_id: "sess-9",
        recipe_name: "Jam",
        servings: 4,
        resumed: true,
        items_to_pick: [
          row({
            ingredient_id: "a",
            status: "picked",
            recommended_item_id: "item-a",
          }),
          row({ ingredient_id: "b", recommended_item_id: "item-b" }),
        ],
      } as PickingStartResponse);
    mocks.scanPicking
      .mockResolvedValueOnce(pickedResult())
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(pickedResult());
    mocks.completePicking.mockResolvedValue({ status: "completed" });
    renderScreen(vi.fn(), undefined, {
      canDeduct: true,
      servings: 4,
      onDeducted,
    });

    await user.click(screen.getByTestId("deduct-confirm"));
    await screen.findByTestId("deduct-failure");

    await user.click(screen.getByTestId("deduct-retry"));

    // The picked row is not scanned again (the server would refuse it as
    // already picked) — only the row that never got answered is.
    expect(await screen.findByTestId("deduct-result")).toBeVisible();
    expect(screen.getByText("2 ingredients taken")).toBeVisible();
    expect(mocks.completePicking).toHaveBeenCalledWith("r-1", "sess-9");
    expect(onDeducted).toHaveBeenCalledWith("sess-9");
  });
});
