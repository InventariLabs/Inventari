import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@/test/utils";
import RecipeEditForm from "./RecipeEditForm";
import type { RecipeList } from "@/modules/recipes/types/core";

const mocks = vi.hoisted(() => ({ useRecipe: vi.fn() }));
vi.mock("@/modules/recipes/hooks/useRecipes", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useRecipe: mocks.useRecipe,
}));

const row = { id: "r-1", name: "Pancakes" } as RecipeList;
const props = { recipe: row, onSubmit: vi.fn(), onCancel: vi.fn() };

describe("RecipeEditForm", () => {
  beforeEach(() => {
    props.onCancel.mockReset();
  });

  it("answers the click with a sheet while the recipe is still loading", () => {
    // Cold cache or a slow link: the form used to return nothing until the
    // detail landed, so the Edit button looked dead.
    mocks.useRecipe.mockReturnValue({ data: undefined, isError: false });

    render(<RecipeEditForm {...props} />);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Edit Recipe")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("lets the reader close the sheet while it waits", async () => {
    mocks.useRecipe.mockReturnValue({ data: undefined, isError: false });

    render(<RecipeEditForm {...props} />);
    screen.getByRole("button", { name: "Close" }).click();

    expect(props.onCancel).toHaveBeenCalledTimes(1);
  });

  it("shows the form once the recipe arrives", () => {
    mocks.useRecipe.mockReturnValue({
      data: { id: "r-1", name: "Pancakes", ingredients: [] },
      isError: false,
    });

    render(<RecipeEditForm {...props} />);

    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByDisplayValue("Pancakes")).toBeInTheDocument();
  });

  it("renders nothing for a recipe that failed to load", () => {
    // The effect has already toasted and asked to close.
    mocks.useRecipe.mockReturnValue({
      data: undefined,
      isError: true,
      error: new Error("nope"),
    });

    const { container } = render(<RecipeEditForm {...props} />);

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(container).toBeEmptyDOMElement();
    expect(props.onCancel).toHaveBeenCalled();
  });
});
