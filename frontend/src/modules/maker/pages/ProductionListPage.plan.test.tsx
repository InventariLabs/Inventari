import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import { signInWith } from "@/test/auth";
import ProductionListPage from "./ProductionListPage";

vi.mock("@/modules/maker/hooks/useRecipes", () => ({
  useMakerSettings: () => ({ data: { reference_direction: "SAVINGS" } }),
}));

vi.mock("@/modules/maker/hooks/useProduction", () => ({
  useProductionOrders: () => ({
    data: { items: [], total: 0, limit: 50, offset: 0, has_more: false },
    isLoading: false,
    error: null,
  }),
  useDuplicateProductionOrder: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/modules/maker/api/products", () => ({
  makerProductsApi: {
    get: vi.fn(async (id: string) => ({
      product_template_id: id,
      name: "Bread",
    })),
  },
}));

// The sheet shows what it was handed, which is all this page decides.
vi.mock("@/modules/maker/components/ProductionCreateSheet", () => ({
  ProductionCreateSheet: ({
    open,
    preselectedProduct,
  }: {
    open: boolean;
    preselectedProduct?: { name: string; quantity?: string; mode?: string };
  }) =>
    open ? (
      <p data-testid="sheet">
        {preselectedProduct
          ? `${preselectedProduct.name} ${preselectedProduct.quantity} ${preselectedProduct.mode}`
          : "empty"}
      </p>
    ) : null,
}));

function renderAt(url: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <PageHeaderContext.Provider
      value={{ data: {}, setHeader: (_data: PageHeaderData) => undefined }}
    >
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[url]}>
          <ProductionListPage />
        </MemoryRouter>
      </QueryClientProvider>
    </PageHeaderContext.Provider>,
  );
}

describe("ProductionListPage opened from a reorder task", () => {
  beforeEach(() => {
    signInWith(["maker:write"]);
  });

  it("opens the form as a plan for the product, with the missing quantity", async () => {
    renderAt("/maker/production?plan=tpl-9&quantity=17");

    await waitFor(() =>
      expect(screen.getByTestId("sheet")).toHaveTextContent("Bread 17 planned"),
    );
  });

  it("opens nothing on a plain visit", () => {
    renderAt("/maker/production");

    expect(screen.queryByTestId("sheet")).not.toBeInTheDocument();
  });
});
