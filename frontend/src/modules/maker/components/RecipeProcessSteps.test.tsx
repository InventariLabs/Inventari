import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { signInWith, signOut } from "@/test/auth";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { RecipeProcessSteps } from "./RecipeProcessSteps";
import type { MakerRecipe } from "@/modules/maker/types/maker";

const updateRecipe = vi.fn();

vi.mock("@/modules/maker/hooks/useRecipes", () => ({
  useUpdateMakerRecipe: () => ({
    mutateAsync: updateRecipe,
    isPending: false,
  }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const recipe = {
  id: "r-1",
  name: "Granola",
  process_steps: [
    { text: "Mix the oats", minutes: "10" },
    { text: "Bake for 20 minutes", minutes: "20" },
  ],
} as unknown as MakerRecipe;

function renderSteps(
  steps: MakerRecipe["process_steps"] = recipe.process_steps ?? [],
) {
  render(<RecipeProcessSteps recipe={{ ...recipe, process_steps: steps }} />);
  fireEvent.click(screen.getByTestId("maker-steps-edit"));
}

describe("RecipeProcessSteps in-place editing", () => {
  beforeEach(() => {
    updateRecipe.mockReset();
    updateRecipe.mockResolvedValue(undefined);
    // Steps are part of the formula — editing is the manager's.
    signInWith(["maker:read", "maker:write", "maker:manage"]);
  });

  afterEach(() => {
    signOut();
  });

  it("edits a step where it stands, keeping its position and time", async () => {
    renderSteps();
    fireEvent.change(screen.getByTestId("maker-steps-edit-1"), {
      target: { value: "Bake for 25 minutes" },
    });
    fireEvent.click(screen.getByTestId("maker-steps-save"));

    await waitFor(() => expect(updateRecipe).toHaveBeenCalled());
    expect(updateRecipe.mock.calls[0][0].data.process_steps).toEqual([
      { text: "Mix the oats", minutes: "10" },
      { text: "Bake for 25 minutes", minutes: "20" },
    ]);
  });

  it("saves the step typed in the add row, with its minutes, when Save is pressed", async () => {
    renderSteps();
    fireEvent.change(screen.getByTestId("maker-steps-input"), {
      target: { value: "Shape and bake at 160 C" },
    });
    fireEvent.change(screen.getByTestId("maker-steps-minutes-input"), {
      target: { value: "40" },
    });
    fireEvent.click(screen.getByTestId("maker-steps-save"));

    await waitFor(() => expect(updateRecipe).toHaveBeenCalled());
    expect(updateRecipe.mock.calls[0][0].data.process_steps).toEqual([
      { text: "Mix the oats", minutes: "10" },
      { text: "Bake for 20 minutes", minutes: "20" },
      { text: "Shape and bake at 160 C", minutes: "40" },
    ]);
  });

  it("asks before the X throws away a typed, unadded step", () => {
    renderSteps();
    fireEvent.change(screen.getByTestId("maker-steps-input"), {
      target: { value: "Cool on a rack" },
    });
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

    // The editor is still open, with the question on top of it.
    expect(screen.getByRole("alertdialog")).toBeTruthy();
    expect(screen.getByTestId("maker-steps-input")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /discard step/i }));
    expect(screen.queryByTestId("maker-steps-input")).toBeNull();
  });

  it("closes the editor without a question when the add row is empty", () => {
    renderSteps();
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.queryByTestId("maker-steps-input")).toBeNull();
  });

  it("keeps newlines inside a step", async () => {
    renderSteps();
    fireEvent.change(screen.getByTestId("maker-steps-edit-0"), {
      target: { value: "Mix the oats\nthen the honey" },
    });
    fireEvent.click(screen.getByTestId("maker-steps-save"));

    await waitFor(() => expect(updateRecipe).toHaveBeenCalled());
    expect(updateRecipe.mock.calls[0][0].data.process_steps[0]).toEqual({
      text: "Mix the oats\nthen the honey",
      minutes: "10",
    });
  });

  it("drops a step emptied out rather than saving a blank row", async () => {
    renderSteps();
    fireEvent.change(screen.getByTestId("maker-steps-edit-0"), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByTestId("maker-steps-save"));

    await waitFor(() => expect(updateRecipe).toHaveBeenCalled());
    expect(updateRecipe.mock.calls[0][0].data.process_steps).toEqual([
      { text: "Bake for 20 minutes", minutes: "20" },
    ]);
  });

  it("saves a step with no time as a step nobody timed", async () => {
    renderSteps([{ text: "Rest", minutes: null }]);
    fireEvent.click(screen.getByTestId("maker-steps-save"));

    await waitFor(() => expect(updateRecipe).toHaveBeenCalled());
    expect(updateRecipe.mock.calls[0][0].data.process_steps).toEqual([
      { text: "Rest", minutes: null },
    ]);
  });

  it("shows how long a step takes beside it", () => {
    render(<RecipeProcessSteps recipe={recipe} />);
    expect(screen.getByTestId("maker-step-minutes-0").textContent).toBe(
      "10 min",
    );
    expect(screen.getByTestId("maker-step-minutes-1").textContent).toBe(
      "20 min",
    );
  });
});
