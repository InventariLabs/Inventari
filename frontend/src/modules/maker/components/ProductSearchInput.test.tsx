import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render as renderBare,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ProductSearchInput } from "./ProductSearchInput";
import type { ProductOption } from "@/modules/maker/api/products";

const productSearch =
  vi.fn<(query: string, limit?: number) => Promise<ProductOption[]>>();
const createProduct =
  vi.fn<(name: string, uom: string) => Promise<ProductOption>>();

vi.mock("@/modules/maker/api/products", () => ({
  makerProductsApi: {
    search: (q: string, limit?: number) => productSearch(q, limit),
    create: (name: string, uomId: string) => createProduct(name, uomId),
  },
}));

// What the two lookups behind the search answer; a test flips one to a failure.
const reads = vi.hoisted(() => ({
  formulasFailed: false,
  unitsFailed: false,
  refetch: vi.fn(),
}));

vi.mock("@/modules/maker/hooks/useBom", () => ({
  useTemplateIdsWithBom: () => ({
    data: reads.formulasFailed ? undefined : ["tpl-with-formula"],
    isError: reads.formulasFailed,
    refetch: reads.refetch,
  }),
}));

vi.mock("@/modules/shared/hooks/useUoms", () => ({
  useFlatUoms: () => ({
    data: reads.unitsFailed
      ? undefined
      : [
          { id: "uom-kg", name: "Kilogram", symbol: "kg" },
          { id: "uom-pcs", name: "Piece", symbol: "pcs" },
        ],
    isError: reads.unitsFailed,
    refetch: reads.refetch,
  }),
}));

const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    error: (msg: string) => toastError(msg),
    success: vi.fn(),
  },
}));

// Creating a product tells the catalogue-count cache, so the search needs a client.
function render(ui: React.ReactElement) {
  return renderBare(
    <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>,
  );
}

function stub(name: string): ProductOption {
  return {
    product_template_id: "tpl-new",
    name,
    sku: "STM-0001",
    barcode: null,
    brand: null,
    uom_id: "uom-kg",
    uom_symbol: "kg",
    image_url: null,
    is_stub: false,
  };
}

function type(value: string) {
  fireEvent.change(screen.getByTestId("maker-product-search-input"), {
    target: { value },
  });
}

describe("ProductSearchInput", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    reads.formulasFailed = false;
    reads.unitsFailed = false;
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  it("says the formula badges did not load, with a retry", () => {
    // A product without its badge reads as a product without a formula.
    reads.formulasFailed = true;
    render(<ProductSearchInput onSelect={vi.fn()} formulaBadge />);

    expect(screen.getByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(reads.refetch).toHaveBeenCalledTimes(1);
  });

  it("says the units did not load beside the create option, with a retry", async () => {
    // An empty unit list reads as a catalogue without units, and the new
    // product cannot be created without one.
    reads.unitsFailed = true;
    productSearch.mockResolvedValue([]);
    render(<ProductSearchInput onSelect={vi.fn()} />);

    type("kiełbasa");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });

    await screen.findByTestId("maker-product-search-create");
    expect(screen.getByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(reads.refetch).toHaveBeenCalledTimes(1);
  });

  it("offers creating the typed product when the search comes back empty", async () => {
    productSearch.mockResolvedValue([]);
    createProduct.mockResolvedValue(stub("kiełbasa zwyczajna"));
    const onSelect = vi.fn();
    render(<ProductSearchInput onSelect={onSelect} />);

    type("kiełbasa zwyczajna");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });

    const createButton = await screen.findByTestId(
      "maker-product-search-create",
    );
    // A product with no unit leaves every later quantity without a measure,
    // so the button waits for one.
    expect(createButton).toBeDisabled();

    fireEvent.change(screen.getByTestId("maker-product-search-uom"), {
      target: { value: "uom-kg" },
    });
    fireEvent.click(createButton);

    await waitFor(() =>
      expect(createProduct).toHaveBeenCalledWith(
        "kiełbasa zwyczajna",
        "uom-kg",
      ),
    );
    await waitFor(() =>
      expect(onSelect).toHaveBeenCalledWith(
        expect.objectContaining({ product_template_id: "tpl-new" }),
      ),
    );
  });

  it("hides the create option while matches exist", async () => {
    productSearch.mockResolvedValue([{ ...stub("kiełbasa"), is_stub: false }]);
    render(<ProductSearchInput onSelect={vi.fn()} />);

    type("kiełbasa");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });

    expect(
      await screen.findByTestId("maker-product-search-result"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("maker-product-search-create"),
    ).not.toBeInTheDocument();
  });

  it("never offers the product the caller excluded", async () => {
    // The composition form passes the recipe's own output product: the
    // server refuses it as a self-reference, so the list must not carry it.
    const output = {
      ...stub("The recipe itself"),
      product_template_id: "tpl-out",
    };
    const other = { ...stub("Flour"), product_template_id: "tpl-flour" };
    productSearch.mockResolvedValue([output, other]);
    render(
      <ProductSearchInput onSelect={vi.fn()} excludeTemplateId="tpl-out" />,
    );

    type("flour");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });

    const results = await screen.findAllByTestId("maker-product-search-result");
    expect(results).toHaveLength(1);
    expect(results[0]).toHaveTextContent("Flour");
    expect(screen.queryByText("The recipe itself")).not.toBeInTheDocument();
  });

  it("keeps the query when creation fails so the user can retry", async () => {
    productSearch.mockResolvedValue([]);
    createProduct.mockRejectedValue(new Error("boom"));
    const onSelect = vi.fn();
    render(<ProductSearchInput onSelect={onSelect} />);

    type("nowy produkt");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });
    fireEvent.change(screen.getByTestId("maker-product-search-uom"), {
      target: { value: "uom-pcs" },
    });
    fireEvent.click(await screen.findByTestId("maker-product-search-create"));

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByTestId("maker-product-search-input")).toHaveValue(
      "nowy produkt",
    );
  });

  it("seeds the unit from the caller so one click creates the product", async () => {
    productSearch.mockResolvedValue([]);
    createProduct.mockResolvedValue(stub("kiełbasa zwyczajna"));
    const onSelect = vi.fn();
    render(<ProductSearchInput onSelect={onSelect} defaultUomId="uom-kg" />);

    type("kiełbasa zwyczajna");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });

    const createButton = await screen.findByTestId(
      "maker-product-search-create",
    );
    // The line already holds its unit — the panel must not re-ask for it.
    expect(createButton).toBeEnabled();
    expect(
      screen.queryByTestId("maker-product-search-uom-required"),
    ).not.toBeInTheDocument();

    fireEvent.click(createButton);
    await waitFor(() =>
      expect(createProduct).toHaveBeenCalledWith(
        "kiełbasa zwyczajna",
        "uom-kg",
      ),
    );
  });

  it("says why the create button waits when no default unit exists", async () => {
    productSearch.mockResolvedValue([]);
    const onSelect = vi.fn();
    render(<ProductSearchInput onSelect={onSelect} />);

    type("kiełbasa zwyczajna");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });

    const createButton = await screen.findByTestId(
      "maker-product-search-create",
    );
    expect(createButton).toBeDisabled();
    // A disabled button swallows clicks silently — the missing-unit reason
    // stands next to it and is tied to the button for screen readers.
    const reason = screen.getByTestId("maker-product-search-uom-required");
    expect(reason).toBeInTheDocument();
    expect(createButton).toHaveAttribute(
      "aria-describedby",
      "maker-product-search-uom-required",
    );

    // Choosing a unit clears the sentence and wakes the button.
    fireEvent.change(screen.getByTestId("maker-product-search-uom"), {
      target: { value: "uom-pcs" },
    });
    expect(
      screen.queryByTestId("maker-product-search-uom-required"),
    ).not.toBeInTheDocument();
    expect(createButton).toBeEnabled();
  });

  it("takes the unit from the caller's form and asks for none itself", async () => {
    productSearch.mockResolvedValue([]);
    createProduct.mockResolvedValue(stub("powidła"));
    const client = new QueryClient();
    const withUnit = (uomId: string | null) => (
      <QueryClientProvider client={client}>
        <ProductSearchInput
          onSelect={vi.fn()}
          formUnit={{ uomId, missingHint: "Pick it beside the quantity." }}
        />
      </QueryClientProvider>
    );
    const { rerender } = renderBare(withUnit(null));

    type("powidła");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });

    const createButton = await screen.findByTestId(
      "maker-product-search-create",
    );
    // No second unit picker inside the dropdown: the sentence points at the
    // one on the form, and the button waits for it.
    expect(
      screen.queryByTestId("maker-product-search-uom"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("maker-product-search-uom-required"),
    ).toHaveTextContent("Pick it beside the quantity.");
    expect(createButton).toBeDisabled();

    // The form's unit is picked: the same panel now creates in it.
    rerender(withUnit("uom-kg"));
    expect(createButton).toBeEnabled();
    fireEvent.click(createButton);
    await waitFor(() =>
      expect(createProduct).toHaveBeenCalledWith("powidła", "uom-kg"),
    );
  });

  it("ignores a default unit the catalogue does not know", async () => {
    productSearch.mockResolvedValue([]);
    render(<ProductSearchInput onSelect={vi.fn()} defaultUomId="uom-gone" />);

    type("kiełbasa zwyczajna");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });

    expect(
      await screen.findByTestId("maker-product-search-create"),
    ).toBeDisabled();
    expect(
      screen.getByTestId("maker-product-search-uom-required"),
    ).toBeInTheDocument();
  });

  it("marks the results that already have a formula when asked to", async () => {
    const withFormula = {
      ...stub("Soup base"),
      product_template_id: "tpl-with-formula",
    };
    const without = {
      ...stub("Plain water"),
      product_template_id: "tpl-plain",
    };
    productSearch.mockResolvedValue([withFormula, without]);
    const onSelect = vi.fn();
    render(<ProductSearchInput onSelect={onSelect} formulaBadge />);

    type("soup");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });

    await screen.findAllByTestId("maker-product-search-result");
    const marked = screen.getAllByTestId("maker-product-search-has-formula");
    expect(marked).toHaveLength(1);
    expect(marked[0]).toHaveAttribute("aria-label", "Has a BOM");
    expect(marked[0].closest("button")).toHaveTextContent("Soup base");
  });

  it("without the flag the rows carry no formula marker", async () => {
    const withFormula = {
      ...stub("Soup base"),
      product_template_id: "tpl-with-formula",
    };
    productSearch.mockResolvedValue([withFormula]);
    const onSelect = vi.fn();
    render(<ProductSearchInput onSelect={onSelect} />);

    type("soup");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });

    await screen.findAllByTestId("maker-product-search-result");
    expect(
      screen.queryByTestId("maker-product-search-has-formula"),
    ).not.toBeInTheDocument();
  });
});
