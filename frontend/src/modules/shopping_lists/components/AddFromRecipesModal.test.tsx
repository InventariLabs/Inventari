import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AddFromRecipesModal from "./AddFromRecipesModal";
import { toast } from "sonner";
import { shoppingListsApi } from "../api/shopping-lists";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

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

  it("names the other open list that already asks for the same goods", async () => {
    vi.mocked(shoppingListsApi.addFromRecipes).mockResolvedValue({
      added_count: 1,
      on_other_lists: [
        { name: "Eggs", list_id: "list-2", list_name: "Week 30" },
      ],
    });

    await selectAndSubmit();

    await waitFor(() => expect(toast.warning).toHaveBeenCalledTimes(1));
    const message = vi.mocked(toast.warning).mock.calls[0][0] as string;
    expect(message).toContain("Eggs");
    expect(message).toContain("Week 30");
  });

  it("says the goods are already listed when the press adds and raises nothing", async () => {
    // "Added 0 ingredients" read as "nothing was missing" or as a failure.
    vi.mocked(shoppingListsApi.addFromRecipes).mockResolvedValue({
      added_count: 0,
      raised_count: 0,
      already_listed_count: 2,
      on_other_lists: [],
    });

    await selectAndSubmit();

    await waitFor(() =>
      expect(toast.info).toHaveBeenCalledWith(
        "Already on this list: 2 ingredients",
      ),
    );
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("counts a raised line as written, not as already listed", async () => {
    vi.mocked(shoppingListsApi.addFromRecipes).mockResolvedValue({
      added_count: 0,
      raised_count: 1,
      already_listed_count: 1,
      on_other_lists: [],
    });

    await selectAndSubmit();

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Added 1 ingredient"),
    );
    expect(toast.info).not.toHaveBeenCalled();
  });

  it("stays quiet about overlap when nothing else holds the goods", async () => {
    vi.mocked(shoppingListsApi.addFromRecipes).mockResolvedValue({
      added_count: 1,
      on_other_lists: [],
    });

    await selectAndSubmit();

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(toast.warning).not.toHaveBeenCalled();
  });
});
