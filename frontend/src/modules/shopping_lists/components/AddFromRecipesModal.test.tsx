import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AddFromRecipesModal from "./AddFromRecipesModal";
import { shoppingListsApi } from "../api/shopping-lists";

vi.mock("../api/shopping-lists", () => ({
  shoppingListsApi: { addFromRecipes: vi.fn() },
}));

const recipesRead = vi.hoisted(() => ({ failed: false, refetch: vi.fn() }));
vi.mock("../hooks/useShoppingLists", () => ({
  useRecipeOptions: () => ({
    data: recipesRead.failed
      ? undefined
      : { items: [{ id: "recipe-1", name: "Pancakes", tags: [] }] },
    isLoading: false,
    isError: recipesRead.failed,
    refetch: recipesRead.refetch,
  }),
}));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({ isModuleEnabled: () => true }),
}));

/**
 * A failed add used to say "Request failed with status code 404" in a toast
 * that then vanished, so two identical failures read as one unregistered
 * click. The reason now comes from the response and stays on the sheet.
 */
describe("AddFromRecipesModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    recipesRead.failed = false;
  });

  it("offers a retry instead of saying there are no recipes when the list failed", async () => {
    recipesRead.failed = true;
    const user = userEvent.setup();
    render(
      <AddFromRecipesModal
        listId="list-1"
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText(/no recipes/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(recipesRead.refetch).toHaveBeenCalledTimes(1);
  });

  async function selectAndSubmit() {
    const user = userEvent.setup();
    render(
      <AddFromRecipesModal
        listId="list-1"
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );
    await user.click(screen.getByText("Pancakes"));
    await user.click(screen.getByRole("button", { name: /Add 1 recipe/i }));
  }

  it("keeps the server's reason on the sheet when the add fails", async () => {
    vi.mocked(shoppingListsApi.addFromRecipes).mockRejectedValue({
      isAxiosError: true,
      response: { data: { detail: "Recipe no longer exists" } },
    });

    await selectAndSubmit();

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Recipe no longer exists",
      );
    });
    // The sheet stays open, so the reader can see what they had selected.
    expect(screen.getByText("Pancakes")).toBeInTheDocument();
  });

  it("falls back to a translated sentence, never the HTTP library's own", async () => {
    vi.mocked(shoppingListsApi.addFromRecipes).mockRejectedValue(
      new Error("Request failed with status code 404"),
    );

    await selectAndSubmit();

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(screen.getByRole("alert")).not.toHaveTextContent(/status code/);
  });
});
