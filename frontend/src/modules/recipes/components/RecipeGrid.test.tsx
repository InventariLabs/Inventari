import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { RecipeGrid } from "./RecipeGrid";
import en from "@/modules/recipes/i18n/en.json";
import common from "@/i18n/locales/en/common.json";
import type { TFunction } from "i18next";
import type {
  RecipeCollection,
  RecipeList,
} from "@/modules/recipes/types/core";

const t = ((key: string) => {
  const ns = key.startsWith("common:") ? common : en;
  const path = key.replace(/^(common|recipes):/, "").split(".");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let value: any = ns;
  for (const part of path) value = value?.[part];
  return typeof value === "string" ? value : key;
}) as unknown as TFunction;

const baseProps = {
  recipes: [] as RecipeList[],
  isLoading: false,
  isError: false,
  page: 0,
  pageSize: 50,
  total: 0,
  tab: "all",
  search: "",
  matchMap: new Map(),
  selectedTags: [] as string[],
  tagColorMap: new Map(),
  onRetry: vi.fn(),
  onToggleFavorite: vi.fn(),
  onEdit: vi.fn(),
  onDelete: vi.fn(),
  onDuplicate: vi.fn(),
  onTagClick: vi.fn(),
  onPageChange: vi.fn(),
  selectionMode: false,
  selectedIds: new Set<string>(),
  dragEnabled: false,
  onToggleSelect: vi.fn(),
  t,
};

const recipe = (id: string): RecipeList => ({
  id,
  name: `Recipe ${id}`,
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

describe("RecipeGrid — pagination and empty states", () => {
  it("hides pagination when there is only one page", () => {
    render(
      <MemoryRouter>
        <RecipeGrid {...baseProps} recipes={[recipe("r1"), recipe("r2")]} />
      </MemoryRouter>,
    );
    // Page number indicator is only rendered by the pagination row
    expect(screen.queryByText("1")).not.toBeInTheDocument();
  });

  it("shows favorites empty state instead of the generic one", () => {
    render(
      <MemoryRouter>
        <RecipeGrid {...baseProps} tab="favorites" />
      </MemoryRouter>,
    );
    expect(screen.getByText("No favorites yet")).toBeInTheDocument();
    expect(
      screen.getByText("Star a recipe to keep it here"),
    ).toBeInTheDocument();
  });

  it("offers a Go to inventory link in the I-can-cook empty state", () => {
    render(
      <MemoryRouter>
        <RecipeGrid {...baseProps} tab="available" />
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: /go to inventory/i });
    expect(link).toHaveAttribute("href", "/inventory/items");
  });

  it("names the pagination arrows for screen readers", () => {
    render(
      <MemoryRouter>
        <RecipeGrid
          {...baseProps}
          recipes={Array.from({ length: 60 }, (_, i) => recipe(`r${i}`))}
          total={60}
        />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("button", { name: "Previous page" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Next page" }),
    ).toBeInTheDocument();
  });

  it("disables Next on the real last page", () => {
    render(
      <MemoryRouter>
        <RecipeGrid
          {...baseProps}
          recipes={Array.from({ length: 10 }, (_, i) => recipe(`r${i}`))}
          page={1}
          total={60}
        />
      </MemoryRouter>,
    );
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });
});

describe("RecipeGrid — 'I can cook' empty state", () => {
  it("points to ingredient linking when nothing is linked", () => {
    const onGoToAllRecipes = vi.fn();
    render(
      <MemoryRouter>
        <RecipeGrid
          {...baseProps}
          tab="available"
          hasLinkedIngredients={false}
          onGoToAllRecipes={onGoToAllRecipes}
        />
      </MemoryRouter>,
    );
    expect(
      screen.getByText("Ingredients are not linked to stock"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Go to inventory")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Open recipes to link ingredients"));
    expect(onGoToAllRecipes).toHaveBeenCalled();
  });

  it("keeps the inventory pointer when ingredients are linked but stock is missing", () => {
    render(
      <MemoryRouter>
        <RecipeGrid {...baseProps} tab="available" hasLinkedIngredients />
      </MemoryRouter>,
    );
    expect(screen.getByText("Go to inventory")).toBeInTheDocument();
    expect(
      screen.queryByText("Ingredients are not linked to stock"),
    ).not.toBeInTheDocument();
  });
});

describe("RecipeGrid — 'No recipes yet' CTA", () => {
  it("offers creating a recipe from the empty list", () => {
    const onCreateRecipe = vi.fn();
    render(
      <MemoryRouter>
        <RecipeGrid {...baseProps} onCreateRecipe={onCreateRecipe} />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "New recipe" }));
    expect(onCreateRecipe).toHaveBeenCalled();
  });

  it("does not tell a read-only reader to create the first recipe", () => {
    // The sentence is an instruction whose button is gated on write access;
    // a viewer got the instruction and no tool.
    render(
      <MemoryRouter>
        <RecipeGrid {...baseProps} canWrite={false} onCreateRecipe={vi.fn()} />
      </MemoryRouter>,
    );
    expect(screen.getByText("No recipes yet")).toBeInTheDocument();
    expect(
      screen.getByText("No recipes have been added yet."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Create your first recipe to get started"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "New recipe" }),
    ).not.toBeInTheDocument();
  });

  it("does not offer creating when the list is empty due to a search", () => {
    render(
      <MemoryRouter>
        <RecipeGrid {...baseProps} search="xyz" onCreateRecipe={vi.fn()} />
      </MemoryRouter>,
    );
    expect(
      screen.queryByRole("button", { name: "New recipe" }),
    ).not.toBeInTheDocument();
    // The description used to fall through to "Create your first recipe to
    // get started" under a title that said the search matched nothing.
    expect(
      screen.getByText("Try a different search term, or clear the search."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Create your first recipe to get started"),
    ).not.toBeInTheDocument();
  });

  it("names the tag filter when no recipe carries it", () => {
    render(
      <MemoryRouter>
        <RecipeGrid
          {...baseProps}
          selectedTags={["obiad"]}
          onCreateRecipe={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(
      screen.getByText("No recipes with the selected tags"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "New recipe" }),
    ).not.toBeInTheDocument();
  });

  it("offers adding an existing recipe in an empty collection", () => {
    const onAddExistingRecipes = vi.fn();
    const collection: RecipeCollection = {
      id: "c1",
      name: "Week",
      icon: null,
      parent_id: null,
      recipe_count: 0,
      children: [],
    };
    render(
      <MemoryRouter>
        <RecipeGrid
          {...baseProps}
          activeCollection={collection}
          onAddExistingRecipes={onAddExistingRecipes}
          onCreateRecipe={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("This collection is empty")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "New recipe" }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Add existing recipes" }),
    );
    expect(onAddExistingRecipes).toHaveBeenCalled();
  });

  it("does not invite a read-only reader to add recipes to an empty collection", () => {
    const collection: RecipeCollection = {
      id: "c1",
      name: "Week",
      icon: null,
      parent_id: null,
      recipe_count: 0,
      children: [],
    };
    render(
      <MemoryRouter>
        <RecipeGrid
          {...baseProps}
          canWrite={false}
          activeCollection={collection}
          onAddExistingRecipes={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("This collection is empty")).toBeInTheDocument();
    expect(
      screen.queryByText("Add an existing recipe to this collection."),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("No recipes have been added to this collection yet."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Add existing recipes" }),
    ).not.toBeInTheDocument();
  });
});

describe("RecipeGrid — which emptiness wins inside a collection", () => {
  const collection: RecipeCollection = {
    id: "c1",
    name: "Week",
    icon: null,
    parent_id: null,
    recipe_count: 0,
    children: [],
  };

  it("reads a search inside an open collection as the search's emptiness", () => {
    render(
      <MemoryRouter>
        <RecipeGrid
          {...baseProps}
          search="chleb"
          activeCollection={collection}
        />
      </MemoryRouter>,
    );
    expect(
      screen.getByText("No recipes match your search"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("This collection is empty"),
    ).not.toBeInTheDocument();
  });

  it("reads a tag filter inside an open collection as the tag emptiness", () => {
    render(
      <MemoryRouter>
        <RecipeGrid
          {...baseProps}
          selectedTags={["obiad"]}
          activeCollection={collection}
        />
      </MemoryRouter>,
    );
    expect(
      screen.getByText("No recipes with the selected tags"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("This collection is empty"),
    ).not.toBeInTheDocument();
  });

  it("speaks for the collection only when nothing else narrows the list", () => {
    render(
      <MemoryRouter>
        <RecipeGrid {...baseProps} activeCollection={collection} />
      </MemoryRouter>,
    );
    expect(screen.getByText("This collection is empty")).toBeInTheDocument();
    expect(
      screen.queryByText("No recipes match your search"),
    ).not.toBeInTheDocument();
  });
});
