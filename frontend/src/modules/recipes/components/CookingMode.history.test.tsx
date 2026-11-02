/**
 * One dinner is one entry in the cooking history.
 *
 * Picking the ingredients and then cooking them step by step is a single
 * meal. Recording the cook as a second entry left the picked run unrated
 * and hung the note on an entry reading "no items picked" — the shape the
 * task set out to remove, reintroduced from the other side. So the cook
 * that follows a picking run names it, and the server closes that run
 * instead of opening another beside it.
 *
 * The entry is asked when the finished screen resolves, no longer the
 * moment "Done" is pressed: that screen asks whether the ingredients come
 * off the shelf, and the answer decides which run the entry names.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import CookingMode from "./CookingMode";
import { QueryWrapper } from "@/test/queryWrapper";
import type { RecipeIngredient } from "../types/core";

const mocks = vi.hoisted(() => ({
  createMutateAsync: vi.fn().mockResolvedValue({ session_id: "entry-1" }),
  patchMutateAsync: vi.fn().mockResolvedValue({}),
  startPicking: vi.fn(),
  scanPicking: vi.fn(),
  completePicking: vi.fn(),
  cancelPicking: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/modules/recipes/hooks/useRecipes", () => ({
  useCreateCookingHistory: () => ({
    mutateAsync: mocks.createMutateAsync,
    isPending: false,
  }),
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

function renderMode(props: {
  servings?: number;
  pickingSessionId?: string;
  onSessionConsumed?: () => void;
  ingredients?: RecipeIngredient[];
}) {
  return render(
    <QueryWrapper>
      <CookingMode
        recipeId="r1"
        recipeName="Pancakes"
        instructions={"1. Mix\n2. Fry"}
        {...props}
        onClose={vi.fn()}
      />
    </QueryWrapper>,
  );
}

function finish() {
  // "Done" stands in place of "Next" on the last step, so the walk to the
  // end of the recipe is part of finishing it. The finished screen then
  // resolves through "Skip" — with no ingredients passed there is nothing
  // to take off the shelf, so it asks nothing and records the dinner.
  fireEvent.click(screen.getByRole("button", { name: /next/i }));
  fireEvent.click(screen.getByRole("button", { name: /done/i }));
  fireEvent.click(screen.getByRole("button", { name: /^skip/i }));
}

beforeEach(() => {
  mocks.createMutateAsync.mockClear();
  mocks.patchMutateAsync.mockClear();
  mocks.startPicking.mockReset();
  mocks.scanPicking.mockReset();
  mocks.completePicking.mockReset();
});

describe("CookingMode — the cook that follows a picking run", () => {
  it("continues that run instead of opening a second entry", async () => {
    renderMode({ servings: 4, pickingSessionId: "picked-session" });

    finish();

    await waitFor(() =>
      expect(mocks.createMutateAsync).toHaveBeenCalledWith({
        servings: 4,
        sessionId: "picked-session",
      }),
    );
  });

  it("opens its own entry when no picking preceded it", async () => {
    renderMode({ servings: 2 });

    finish();

    await waitFor(() =>
      expect(mocks.createMutateAsync).toHaveBeenCalledWith({
        servings: 2,
        sessionId: undefined,
      }),
    );
  });

  it("reports the run as consumed once the entry is recorded", async () => {
    // The flow hands the picked run to one cook only. It learns the run was
    // used from here, because only this screen knows the entry was written.
    const consumed = vi.fn();
    renderMode({
      pickingSessionId: "picked-session",
      onSessionConsumed: consumed,
    });

    finish();

    await waitFor(() => expect(consumed).toHaveBeenCalledTimes(1));
  });

  it("reports nothing when no picking preceded it", async () => {
    const consumed = vi.fn();
    renderMode({ servings: 2, onSessionConsumed: consumed });

    finish();

    await waitFor(() => expect(mocks.createMutateAsync).toHaveBeenCalled());
    expect(consumed).not.toHaveBeenCalled();
  });

  it("keeps the run unconsumed when the entry could not be recorded", async () => {
    // A failed request wrote nothing, so the dinner is still uncooked and the
    // save button asks again — naming the same run. Dropping the thread on a
    // failure would record that dinner twice.
    const consumed = vi.fn();
    mocks.createMutateAsync.mockRejectedValueOnce(new Error("offline"));
    renderMode({
      pickingSessionId: "picked-session",
      onSessionConsumed: consumed,
    });

    finish();

    await waitFor(() => expect(mocks.createMutateAsync).toHaveBeenCalled());
    expect(consumed).not.toHaveBeenCalled();
    // The screen says the record failed instead of closing over it.
    expect(await screen.findByRole("alert")).toBeVisible();
  });

  it("records the servings this run cooks, not the recipe's own", async () => {
    // The page scales a recipe on screen; the entry that says "I cooked
    // this" has to carry the number that was cooked.
    renderMode({ servings: 6 });

    finish();

    await waitFor(() =>
      expect(mocks.createMutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({ servings: 6 }),
      ),
    );
  });

  it("a confirmed deduction names the dinner's entry", async () => {
    // A cook with ingredients asks about the shelf. Confirming opens a
    // picking run of its own — and the entry the cook records must name
    // THAT run, so the history reads "picked 3/3" instead of opening a
    // second, "nothing picked" entry beside it.
    mocks.startPicking.mockResolvedValue({
      picking_session_id: "deducted-session",
      recipe_name: "Pancakes",
      servings: 2,
      items_to_pick: [
        {
          ingredient_id: "i1",
          name: "Flour",
          quantity_to_pick: 500,
          uom_symbol: "g",
          recommended_item_id: "item-1",
          location: null,
          fefo_days_left: null,
          fefo_expiry_date: null,
          status: "pending",
          is_linked: true,
        },
      ],
    });
    mocks.scanPicking.mockResolvedValue({
      status: "picked",
      ingredient_id: "i1",
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
    });
    mocks.completePicking.mockResolvedValue({ status: "completed" });

    renderMode({
      servings: 2,
      ingredients: [
        {
          id: "i1",
          recipe_id: "r1",
          name: "Flour",
          template_id: null,
          ingredient_group_name: null,
          quantity: "500",
          uom_id: null,
          uom_symbol: "g",
          is_optional: false,
          is_spice: false,
          picking_skip: null,
          sort_order: 0,
          calories_kcal_per_100g: null,
          display_text: null,
          original_quantity: null,
          original_unit_text: null,
          price: null,
          price_uom_id: null,
          price_currency: null,
          allergens: [],
        },
      ],
    });

    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    fireEvent.click(screen.getByRole("button", { name: /done/i }));
    fireEvent.click(screen.getByTestId("deduct-confirm"));
    await screen.findByTestId("deduct-result");
    fireEvent.click(screen.getByRole("button", { name: /^skip/i }));

    await waitFor(() =>
      expect(mocks.createMutateAsync).toHaveBeenCalledWith({
        servings: 2,
        sessionId: "deducted-session",
      }),
    );
    expect(mocks.completePicking).toHaveBeenCalledWith(
      "r1",
      "deducted-session",
    );
  });
});
