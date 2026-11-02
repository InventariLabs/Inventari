import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { CollectionAddRecipesModal } from "./CollectionAddRecipesModal";
import type {
  RecipeCollection,
  RecipeList,
} from "@/modules/recipes/types/core";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mocks = vi.hoisted(() => ({
  useRecipes: vi.fn(),
  useAddRecipeToCollection: vi.fn(),
}));

vi.mock("@/modules/recipes/hooks/useRecipes", () => ({
  useRecipes: mocks.useRecipes,
  useAddRecipeToCollection: mocks.useAddRecipeToCollection,
}));

const collection: RecipeCollection = {
  id: "c1",
  name: "Week",
  icon: null,
  parent_id: null,
  recipe_count: 0,
  children: [],
};

const recipe = (id: string, name: string): RecipeList => ({
  id,
  name,
  description: null,
  servings: 2,
  prep_time_minutes: null,
  image_url: null,
  tags: null,
  is_favorite: false,
  created_at: "2026-01-01T00:00:00Z",
  source_url: null,
  ingredients_total: 0,
  ingredients_linked: 0,
  ingredients_available: 0,
  ingredients_incomparable: 0,
  missing_names: [],
});

describe("CollectionAddRecipesModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.useRecipes.mockReturnValue({
      data: {
        items: [recipe("r1", "Pancakes"), recipe("r2", "Soup")],
        total: 2,
      },
      isError: false,
    });
    mocks.useAddRecipeToCollection.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({}),
    });
  });

  it("shows loading, not an empty result, while the list is pending", () => {
    mocks.useRecipes.mockReturnValue({
      data: undefined,
      isError: false,
      isPending: true,
    });
    render(
      <CollectionAddRecipesModal collection={collection} onClose={vi.fn()} />,
    );
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByText(/No recipes/)).not.toBeInTheDocument();
  });

  it("adds a recipe that already exists to the collection", async () => {
    const mutateAsync = vi.fn().mockResolvedValue({});
    mocks.useAddRecipeToCollection.mockReturnValue({ mutateAsync });

    render(
      <CollectionAddRecipesModal collection={collection} onClose={vi.fn()} />,
    );

    fireEvent.click(screen.getByTestId("collection-add-r1"));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        collectionId: "c1",
        recipeId: "r1",
      });
    });
    expect(toast.success).toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.getByTestId("collection-add-r1")).toBeDisabled();
    });
  });

  it("carries the collection name into the title", () => {
    render(
      <CollectionAddRecipesModal collection={collection} onClose={vi.fn()} />,
    );
    expect(
      screen.getByRole("dialog", { name: 'Add recipes to "Week"' }),
    ).toBeInTheDocument();
  });
});
