import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { ReactNode } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import ProductionListPage from "./ProductionListPage";
import type { ProductionOrder } from "@/modules/maker/types/maker";

import { signInWith } from "@/test/auth";
import { withLanguage } from "@/test/mocks/i18n";

const header: { actions: ReactNode } = { actions: null };

// The page asks whether this account may write before it renders the
// form at all; rendering it signed out tests the denial instead.
beforeEach(() => {
  signInWith(["maker:write"]);
});

const duplicateMutate = vi.fn();

const order: ProductionOrder = {
  id: "ord-1",
  organization_id: "org-1",
  output_template_id: "tpl-1",
  output_template_name: "Jar",
  recipe_id: null,
  number: null,
  planned_qty: "5",
  actual_qty: null,
  overproduced: false,
  scrap_qty: null,
  output_location_id: "loc-1",
  status: "DRAFT",
  total_cost: null,
  production_date: null,
  notes: null,
  created_by: null,
  completed_by: null,
  created_at: "2026-01-01T00:00:00Z",
  completed_at: null,
  cancel_reason: null,
  produced_item_id: null,
  produced_item_name: null,
  unit_cost_snapshot: null,
  reference_price_snapshot: null,
  result_per_unit: null,
  result_per_batch: null,
  lines: [],
};

let listData: {
  items: ProductionOrder[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
} = { items: [order], total: 1, limit: 50, offset: 0, has_more: false };

// The result's name follows the organization's setting; these screens read
// it through the settings hook, which needs the module and query providers.
vi.mock("@/modules/maker/hooks/useRecipes", () => ({
  useMakerSettings: () => ({ data: { reference_direction: "SAVINGS" } }),
}));

vi.mock("@/modules/maker/hooks/useProduction", () => ({
  useProductionOrders: () => ({
    data: listData,
    isLoading: false,
    error: null,
  }),
  useDuplicateProductionOrder: () => ({
    mutate: duplicateMutate,
    isPending: false,
  }),
}));

vi.mock("@/modules/maker/components/ProductionCreateSheet", () => ({
  ProductionCreateSheet: () => null,
}));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <PageHeaderContext.Provider
      value={{
        data: {},
        setHeader: (data: PageHeaderData) => {
          header.actions = data.actions ?? null;
        },
      }}
    >
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/maker"]}>
          <ProductionListPage />
        </MemoryRouter>
      </QueryClientProvider>
    </PageHeaderContext.Provider>,
  );
}

describe("ProductionListPage duplicate", () => {
  beforeEach(() => {
    listData = {
      items: [order],
      total: 1,
      limit: 50,
      offset: 0,
      has_more: false,
    };
  });

  it("renders a duplicate button per card and calls the mutation", () => {
    renderPage();
    const buttons = screen.getAllByTestId("maker-card-duplicate-button");
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]);
    expect(duplicateMutate).toHaveBeenCalledWith(
      "ord-1",
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });
});

describe("ProductionListPage tools over an empty list", () => {
  beforeEach(() => {
    listData = { items: [], total: 0, limit: 50, offset: 0, has_more: false };
  });

  it("drops search, tabs and filters when there is not one run", () => {
    renderPage();

    expect(
      screen.queryByPlaceholderText("Search by output product…"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Draft" }),
    ).not.toBeInTheDocument();
    // The empty state keeps its own way of putting something in the list.
    expect(screen.getByText("No production runs yet")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /new production/i }),
    ).toBeInTheDocument();
  });

  it("keeps the tools and says 'no match' once the reader has narrowed it", () => {
    listData = {
      items: [order],
      total: 1,
      limit: 50,
      offset: 0,
      has_more: false,
    };
    renderPage();

    fireEvent.change(screen.getByPlaceholderText("Search by output product…"), {
      target: { value: "zzz" },
    });

    expect(screen.getByText("No run matches")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("Search by output product…"),
    ).toBeInTheDocument();
    // Creating a run is not the answer to a search that found nothing.
    expect(
      screen.queryByRole("button", { name: /new production/i }),
    ).not.toBeInTheDocument();
  });
});

describe("ProductionListPage view toggle", () => {
  beforeEach(() => {
    localStorage.clear();
    listData = {
      items: [order],
      total: 1,
      limit: 50,
      offset: 0,
      has_more: false,
    };
  });

  afterEach(() => {
    // Stored preference — clear it, or it decides the view of later tests.
    localStorage.clear();
  });

  it("switches the run cards for a table of rows", () => {
    renderPage();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "List view" }));

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Product" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Jar" })).toBeVisible();
  });

  it("duplicates from a row the same way a card does", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "List view" }));

    fireEvent.click(screen.getByTestId("maker-row-duplicate-button"));

    expect(duplicateMutate).toHaveBeenCalledWith(
      "ord-1",
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });

  it("shows no table header over a list narrowed to nothing", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "List view" }));

    fireEvent.change(screen.getByPlaceholderText("Search by output product…"), {
      target: { value: "zzz" },
    });

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("No run matches")).toBeInTheDocument();
  });
});

describe("ProductionListPage run card result", () => {
  beforeEach(() => {
    listData = {
      items: [
        {
          ...order,
          status: "COMPLETED",
          actual_qty: "5",
          result_per_unit: "2",
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
      has_more: false,
    };
  });

  it("writes the definition on the card, where a finger can read it", () => {
    // It was a hover title on the card, which no phone ever shows.
    renderPage();

    expect(
      screen.getByText("Shop price minus the cost to make it"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/^Savings vs shop price:/).closest("[title]"),
    ).toBeNull();
  });

  it("names a counted unit in the reader's word on the card", async () => {
    listData = {
      ...listData,
      items: [{ ...listData.items[0], output_uom_symbol: "pcs" }],
    };
    await withLanguage("pl", () => {
      renderPage();
      expect(screen.getByText(/za szt\.\)/)).toBeInTheDocument();
      expect(screen.queryByText(/za pcs/)).not.toBeInTheDocument();
    });
  });
});

describe("ProductionListPage run numbers", () => {
  beforeEach(() => {
    listData = {
      items: [{ ...order, number: "PR/2026/0007" }],
      total: 1,
      limit: 50,
      offset: 0,
      has_more: false,
    };
  });

  it("shows the run number beside the product name on a card", () => {
    renderPage();

    expect(screen.getByTestId("maker-order-number")).toHaveTextContent(
      "PR/2026/0007",
    );
  });

  it("finds a run by its number", () => {
    renderPage();

    fireEvent.change(screen.getByPlaceholderText("Search by output product…"), {
      target: { value: "PR/2026/0007" },
    });

    expect(screen.getByTestId("maker-order-number")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Search by output product…"), {
      target: { value: "PR/2026/9999" },
    });
    expect(screen.queryByTestId("maker-order-number")).not.toBeInTheDocument();
  });

  it("leaves a legacy run at the short UUID instead of inventing a number", () => {
    listData = {
      items: [order],
      total: 1,
      limit: 50,
      offset: 0,
      has_more: false,
    };
    renderPage();

    expect(screen.queryByTestId("maker-order-number")).not.toBeInTheDocument();
  });
});

describe("ProductionListPage — the card carries the shortage", () => {
  const shortOrder: ProductionOrder = {
    ...order,
    id: "ord-2",
    output_template_name: "Big Jar",
    shortage_count: 2,
  };

  afterEach(() => {
    localStorage.clear();
  });

  it("names the shortage the detail page would call a blocker", () => {
    listData = {
      items: [shortOrder],
      total: 1,
      limit: 50,
      offset: 0,
      has_more: false,
    };
    renderPage();

    expect(screen.getByTestId("maker-order-shortage")).toHaveTextContent(
      "Short of stock: 2 ingredients",
    );
  });

  it("says nothing when the order carries no shortage", () => {
    listData = {
      items: [order],
      total: 1,
      limit: 50,
      offset: 0,
      has_more: false,
    };
    renderPage();

    expect(
      screen.queryByTestId("maker-order-shortage"),
    ).not.toBeInTheDocument();
  });

  it("the table view names it too — the row a planner scans says as much as the card", () => {
    listData = {
      items: [shortOrder],
      total: 1,
      limit: 50,
      offset: 0,
      has_more: false,
    };
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "List view" }));

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByTestId("maker-order-shortage")).toHaveTextContent(
      "Short of stock: 2 ingredients",
    );
  });

  it("keeps the row quiet when there is nothing short", () => {
    listData = {
      items: [order],
      total: 1,
      limit: 50,
      offset: 0,
      has_more: false,
    };
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "List view" }));

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(
      screen.queryByTestId("maker-order-shortage"),
    ).not.toBeInTheDocument();
  });
});

describe("ProductionListPage — a read-only account", () => {
  beforeEach(() => {
    header.actions = null;
    signInWith(["maker:read"]);
    listData = {
      items: [order],
      total: 1,
      limit: 50,
      offset: 0,
      has_more: false,
    };
  });

  it("is offered no way to start a run, in the header or the empty state", async () => {
    const { unmount } = renderPage();
    expect(await screen.findByText("Jar")).toBeInTheDocument();
    // The header action the shell would render.
    expect(header.actions).toBeNull();
    unmount();

    listData = { items: [], total: 0, limit: 50, offset: 0, has_more: false };
    renderPage();
    expect(
      await screen.findByText("No production runs yet"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /new production/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/you can view this, not change it/i),
    ).toBeInTheDocument();
  });

  it("keeps Duplicate away from the rows", async () => {
    renderPage();
    await screen.findByText("Jar");

    expect(
      screen.queryByTestId("maker-card-duplicate-button"),
    ).not.toBeInTheDocument();
  });
});
