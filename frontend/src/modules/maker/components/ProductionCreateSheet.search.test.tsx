import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ProductionCreateSheet } from "./ProductionCreateSheet";
import {
  makerProductsApi,
  type ProductOption,
} from "@/modules/maker/api/products";

vi.mock("@/modules/maker/api/products", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/modules/maker/api/products")>();
  return {
    ...actual,
    makerProductsApi: {
      ...actual.makerProductsApi,
      search: vi.fn(),
    },
  };
});

const mockedSearch = vi.mocked(makerProductsApi.search);

// The output search marks products that have a BOM; the marker's one
// request is not what these tests are about.
vi.mock("@/modules/maker/api/bom", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/modules/maker/api/bom")>();
  return {
    ...actual,
    bomApi: {
      ...actual.bomApi,
      templateIdsWithBom: vi.fn().mockResolvedValue({ template_ids: [] }),
    },
  };
});

function product(overrides: Partial<ProductOption> = {}): ProductOption {
  return {
    product_template_id: "tpl-candle",
    name: "Lavender candle",
    sku: "STM-71FB66B9",
    barcode: null,
    brand: null,
    uom_id: null,
    uom_symbol: null,
    image_url: null,
    is_stub: false,
    ...overrides,
  };
}

function renderSheet() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // No preselected product: the sheet opens on the product search.
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ProductionCreateSheet open onClose={vi.fn()} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ProductionCreateSheet — product suggestion semantics", () => {
  beforeEach(() => {
    mockedSearch.mockReset();
  });

  it("opens a listbox of options under the combobox, like the recipe sheet", async () => {
    // The sheet used to answer its search with plain buttons in plain divs:
    // after a query a screen reader heard nothing, and the arrow keys had
    // nothing to walk. The shared picker owns the combobox/listbox/option
    // semantics, so the test pins them on this sheet too.
    mockedSearch.mockResolvedValue([product()]);
    renderSheet();
    const input = screen.getByTestId("maker-create-search-input");
    expect(input).toHaveAttribute("role", "combobox");
    expect(input).toHaveAttribute("aria-expanded", "false");

    fireEvent.change(input, { target: { value: "lav" } });

    const listbox = await screen.findByRole("listbox", {}, { timeout: 3000 });
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(input).toHaveAttribute("aria-controls", listbox.id);

    const option = within(listbox).getByRole("option", {
      name: /Lavender candle/,
    });
    expect(option).toHaveAttribute("aria-selected", "false");
  });

  it("walks the suggestions with the arrow keys via aria-activedescendant", async () => {
    mockedSearch.mockResolvedValue([
      product({ product_template_id: "tpl-1", name: "Candle A", sku: "A-1" }),
      product({ product_template_id: "tpl-2", name: "Candle B", sku: "B-2" }),
    ]);
    renderSheet();
    const input = screen.getByTestId("maker-create-search-input");
    fireEvent.change(input, { target: { value: "can" } });

    const options = await screen.findAllByRole("option", {}, { timeout: 3000 });
    expect(input).not.toHaveAttribute("aria-activedescendant");

    fireEvent.keyDown(input, { key: "ArrowDown" });
    await waitFor(() =>
      expect(input).toHaveAttribute("aria-activedescendant", options[0].id),
    );
    expect(options[0]).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(input, { key: "ArrowDown" });
    await waitFor(() =>
      expect(input).toHaveAttribute("aria-activedescendant", options[1].id),
    );
    expect(options[0]).toHaveAttribute("aria-selected", "false");
    expect(options[1]).toHaveAttribute("aria-selected", "true");
  });

  it("picks the suggestion and swaps the search for the selected product card", async () => {
    mockedSearch.mockResolvedValue([product()]);
    renderSheet();
    const input = screen.getByTestId("maker-create-search-input");
    fireEvent.change(input, { target: { value: "lav" } });

    const option = await screen.findByRole(
      "option",
      { name: /Lavender candle/ },
      { timeout: 3000 },
    );
    fireEvent.click(option);

    const change = await screen.findByTestId("maker-create-change-product");
    expect(change).toBeInTheDocument();
    expect(screen.getByText("Lavender candle")).toBeInTheDocument();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});
