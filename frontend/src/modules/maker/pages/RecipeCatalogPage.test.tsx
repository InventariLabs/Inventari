import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { signInWith, signOut } from "@/test/auth";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router-dom";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import RecipeCatalogPage from "./RecipeCatalogPage";
import type { RecipeCatalogItem } from "@/modules/maker/types/maker";

const recipe: RecipeCatalogItem = {
  id: "recipe-1",
  output_template_id: "tpl-1",
  name: "Granola Bars",
  output_template_name: "Granola Bars 500g",
  batch_yield_qty: "1",
  is_default: false,
  ingredient_count: 3,
  unit_cost: "5.00",
  uncosted_ingredients: 0,
  estimated_uncosted_ingredients: 0,
  reference_price: "8.00",
  result: "3.00",
  reference_direction: "SAVINGS",
  stock_qty: null,
  last_produced_at: null,
};

interface CatalogResponse {
  items: RecipeCatalogItem[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

let catalogData: CatalogResponse = {
  items: [recipe],
  total: 1,
  limit: 50,
  offset: 0,
  has_more: false,
};

const catalogCalls: (string | undefined | number)[][] = [];

/** Query state the page renders through QueryResult. */
let catalogState: {
  isLoading: boolean;
  isError: boolean;
  /** A refetch that failed after a page had loaded keeps that page's data. */
  keepData?: boolean;
} = {
  isLoading: false,
  isError: false,
};
const refetch = vi.fn();

/** What the endpoint answers once a search term is in play. */
const searchData: CatalogResponse = {
  items: [],
  total: 0,
  limit: 50,
  offset: 0,
  has_more: false,
};

vi.mock("@/modules/maker/hooks/useRecipes", () => ({
  useMakerRecipeCatalog: (...args: (string | undefined | number)[]) => {
    catalogCalls.push(args);
    const searching = Boolean(args[0]);
    return {
      data:
        catalogState.isLoading ||
        (catalogState.isError && !catalogState.keepData)
          ? undefined
          : searching
            ? searchData
            : catalogData,
      isLoading: catalogState.isLoading,
      isError: catalogState.isError,
      error: null,
      refetch,
    };
  },
  useMakerRecipeAvailability: () => ({ data: undefined, isLoading: false }),
  useMakerSettings: () => ({ data: { reference_direction: "SAVINGS" } }),
}));

vi.mock("@/modules/maker/hooks/useProduction", () => ({
  useMakerMonthlyResult: () => ({
    data: [
      { month: "2026-06", result: "0.00", orders: 0 },
      { month: "2026-07", result: "40.50", orders: 3 },
    ],
    isLoading: false,
  }),
}));

interface ProductionSheetProps {
  open: boolean;
  onClose: () => void;
  onSuccess?: (orderId: string) => void;
  preselectedProduct?: {
    output_template_id: string;
    name: string;
    recipe_id?: string | null;
  };
}

const productionSheetCalls: ProductionSheetProps[] = [];
const recipeSheetCalls: { open: boolean; onClose: () => void }[] = [];

vi.mock("@/modules/maker/components/ProductionCreateSheet", () => ({
  ProductionCreateSheet: (props: ProductionSheetProps) => {
    productionSheetCalls.push(props);
    return null;
  },
}));

vi.mock("@/modules/maker/components/RecipeCreateSheet", () => ({
  RecipeCreateSheet: (props: { open: boolean; onClose: () => void }) => {
    recipeSheetCalls.push(props);
    return null;
  },
}));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/maker"]}>
          <RecipeCatalogPage />
        </MemoryRouter>
      </QueryClientProvider>
    </PageHeaderContext.Provider>,
  );
}

describe("RecipeCatalogPage produce + create wiring", () => {
  beforeEach(() => {
    signInWith(["maker:read", "maker:write", "maker:manage"]);
    productionSheetCalls.length = 0;
    recipeSheetCalls.length = 0;
    catalogCalls.length = 0;
    catalogState = { isLoading: false, isError: false };
    refetch.mockReset();
    catalogData = {
      items: [recipe],
      total: 1,
      limit: 50,
      offset: 0,
      has_more: false,
    };
  });

  it("prefills the production sheet when a card's Produce action is used", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Produce" }));

    const last = productionSheetCalls[productionSheetCalls.length - 1];
    expect(last.open).toBe(true);
    expect(last.preselectedProduct).toEqual({
      output_template_id: "tpl-1",
      name: "Granola Bars 500g",
      recipe_id: "recipe-1",
    });
  });

  it("opens the recipe create sheet from the empty-state CTA", () => {
    catalogData = {
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
      has_more: false,
    };
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "New BOM" }));

    const last = recipeSheetCalls[recipeSheetCalls.length - 1];
    expect(last.open).toBe(true);
  });

  it("shows the monthly production result on the module's start screen", async () => {
    renderPage();
    // The result card used to sit on the inventory overview, where it mixed
    // the month's margin into stock. Production's own start is its home.
    expect(
      await screen.findByText("Savings vs shop price by month"),
    ).toBeInTheDocument();
    expect(screen.getByText("July")).toBeInTheDocument();
  });
});

describe("RecipeCatalogPage pagination", () => {
  beforeEach(() => {
    catalogCalls.length = 0;
    catalogState = { isLoading: false, isError: false };
    refetch.mockReset();
    catalogData = {
      items: [recipe],
      total: 120,
      limit: 50,
      offset: 0,
      has_more: true,
    };
  });

  it("requests the next page with skip=limit when Next is clicked", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));

    const last = catalogCalls[catalogCalls.length - 1];
    // args: (search, sort, skip, limit)
    expect(last[2]).toBe(50);
    expect(last[3]).toBe(50);
  });

  it("stops paging when a refetch failed, even with the last page still cached", () => {
    // `total` came from data the failed request no longer vouches for: the
    // pager offered Next over an error screen.
    catalogState = { isLoading: false, isError: true, keepData: true };
    renderPage();

    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Next page" })).toBeNull();
  });

  it("resets skip to 0 when the search changes", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    fireEvent.change(screen.getByPlaceholderText("Search BOMs…"), {
      target: { value: "granola" },
    });

    const last = catalogCalls[catalogCalls.length - 1];
    expect(last[0]).toBe("granola");
    expect(last[2]).toBe(0);
  });
});

describe("RecipeCatalogPage states", () => {
  beforeEach(() => {
    catalogCalls.length = 0;
    catalogState = { isLoading: false, isError: false };
    refetch.mockReset();
    catalogData = {
      items: [recipe],
      total: 1,
      limit: 50,
      offset: 0,
      has_more: false,
    };
  });

  it("shows a spinner while the catalog loads", () => {
    catalogState = { isLoading: true, isError: false };
    const { container } = renderPage();
    expect(container.querySelector(".animate-spin")).toBeTruthy();
  });

  it("offers a retry when the catalog fails to load", () => {
    catalogState = { isLoading: false, isError: true };
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("offers nothing to narrow when the catalog is genuinely empty", () => {
    catalogData = {
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
      has_more: false,
    };
    renderPage();

    expect(screen.getByText("No BOMs yet")).toBeInTheDocument();
    expect(
      screen.queryByPlaceholderText("Search BOMs…"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Sort by")).not.toBeInTheDocument();
  });

  it("keeps the search when it is the search that emptied the list", () => {
    renderPage();
    fireEvent.change(screen.getByPlaceholderText("Search BOMs…"), {
      target: { value: "zzz" },
    });

    expect(screen.getByText("No BOM matches")).toBeInTheDocument();
    // The way out of a failed search has to stay on screen.
    expect(screen.getByPlaceholderText("Search BOMs…")).toBeInTheDocument();
    // Nothing to create from a failed search — the CTA belongs to the
    // genuinely empty catalog.
    expect(
      screen.queryByRole("button", { name: "New BOM" }),
    ).not.toBeInTheDocument();
  });
});

describe("RecipeCatalogPage sorting", () => {
  beforeEach(() => {
    catalogCalls.length = 0;
    catalogState = { isLoading: false, isError: false };
    catalogData = {
      items: [recipe],
      total: 1,
      limit: 50,
      offset: 0,
      has_more: false,
    };
  });

  it("sends the chosen ordering to the catalog query", () => {
    renderPage();
    expect(catalogCalls[catalogCalls.length - 1][1]).toBe("newest");

    fireEvent.click(screen.getByRole("button", { name: "Name" }));
    expect(catalogCalls[catalogCalls.length - 1][1]).toBe("name");
  });

  it("returns to the first page when the ordering changes", () => {
    catalogData = {
      items: [recipe],
      total: 120,
      limit: 50,
      offset: 0,
      has_more: true,
    };
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(catalogCalls[catalogCalls.length - 1][2]).toBe(50);

    fireEvent.click(screen.getByRole("button", { name: "Oldest" }));
    expect(catalogCalls[catalogCalls.length - 1][2]).toBe(0);
  });
});

describe("RecipeCatalogPage view toggle", () => {
  beforeEach(() => {
    localStorage.clear();
    // The row's Produce action is the account's, so the describe holds one.
    signInWith(["maker:read", "maker:write", "maker:manage"]);
    catalogState = { isLoading: false, isError: false };
    catalogData = {
      items: [recipe],
      total: 1,
      limit: 50,
      offset: 0,
      has_more: false,
    };
  });

  afterEach(() => {
    // The choice is stored, so a leaked "list" would decide the view of
    // every test that runs after this one.
    localStorage.clear();
    signOut();
  });

  it("opens on cards and switches to a table of rows", () => {
    renderPage();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "List view" }));

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Name" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Granola Bars" }),
    ).toBeInTheDocument();
  });

  it("remembers the chosen view for the next visit", () => {
    const first = renderPage();
    fireEvent.click(screen.getByRole("button", { name: "List view" }));
    first.unmount();

    renderPage();
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("produces from a row the same way a card does", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "List view" }));
    fireEvent.click(screen.getByRole("button", { name: "Produce" }));

    const last = productionSheetCalls[productionSheetCalls.length - 1];
    expect(last.open).toBe(true);
    expect(last.preselectedProduct).toEqual({
      output_template_id: "tpl-1",
      name: "Granola Bars 500g",
      recipe_id: "recipe-1",
    });
  });
});

describe("RecipeCatalogPage — a read-only account", () => {
  beforeEach(() => {
    signInWith(["maker:read"]);
    productionSheetCalls.length = 0;
    recipeSheetCalls.length = 0;
    catalogState = { isLoading: false, isError: false };
    catalogData = {
      items: [recipe],
      total: 1,
      limit: 50,
      offset: 0,
      has_more: false,
    };
  });

  it("is offered neither Produce nor a formula edit, and opens no sheet", () => {
    renderPage();

    expect(screen.getByText("Granola Bars")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Produce" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("maker-recipe-card-add-ingredients"),
    ).not.toBeInTheDocument();
    // The sheet is mounted closed; what must not happen is it opening.
    expect(productionSheetCalls.every((call) => !call.open)).toBe(true);
  });

  it("keeps the same distance in the row view", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "List view" }));

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Produce" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("maker-recipe-row-add-ingredients"),
    ).not.toBeInTheDocument();
  });
});

describe("RecipeCatalogPage — arriving from a product with no formula", () => {
  const product = { product_template_id: "tpl-1", name: "Granola Bars 500g" };

  function renderArriving() {
    let seen: unknown = "unset";
    const Probe = () => {
      seen = useLocation().state;
      return null;
    };
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={qc}>
          <MemoryRouter
            initialEntries={[
              { pathname: "/maker", state: { createRecipeFor: product } },
            ]}
          >
            <Probe />
            <RecipeCatalogPage />
          </MemoryRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );
    return () => seen;
  }

  beforeEach(() => {
    recipeSheetCalls.length = 0;
    catalogState = { isLoading: false, isError: false };
  });

  it("opens the create sheet for a manager", () => {
    signInWith(["maker:read", "maker:write", "maker:manage"]);
    const state = renderArriving();

    expect(recipeSheetCalls.some((call) => call.open)).toBe(true);
    expect(state()).toBeNull();
  });

  it("opens nothing for an account that cannot manage formulas", () => {
    signInWith(["maker:read", "maker:write"]);
    const state = renderArriving();

    expect(recipeSheetCalls.every((call) => !call.open)).toBe(true);
    expect(state()).toBeNull();
  });
});
