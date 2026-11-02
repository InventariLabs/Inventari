import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/utils";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import StockLevelsPage from "./StockLevelsPage";

const listSpy = vi.fn();

let searchParams = new URLSearchParams();
const writeSearchParams = vi.fn(
  (update: (current: URLSearchParams) => URLSearchParams) => {
    searchParams = update(searchParams);
  },
);
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useSearchParams: () => [searchParams, writeSearchParams],
  };
});

const ROWS = [
  {
    id: "q1",
    product_template_id: "p1",
    location_id: "l1",
    lot_id: "lot-1",
    quantity: "6.000",
    reserved_quantity: "4.000",
    available_quantity: "2.000",
    product_name: "Rye flour",
    uom_symbol: "kg",
    location_name: "Aisle 1",
    lot_name: "L-7",
    lot_status: "recalled",
  },
];

// What the shelf answers this render. Tests that care about the empty state
// set it to nothing; the rest leave the one row.
let listState: { items: typeof ROWS; total: number } = {
  items: ROWS,
  total: 1,
};

vi.mock("@/modules/inventory/hooks/useStockQuants", () => ({
  useStockQuants: (filters: unknown) => {
    listSpy(filters);
    return {
      data: {
        items: listState.items,
        total: listState.total,
        limit: 50,
        offset: 0,
        has_more: false,
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    };
  },
}));

// The places, as the endpoint answers for them: a page of those named by id
// or matching the search. The screen asks for the places it shows and for what
// the reader types; it never reads the organization's catalogue.
const PLACES = [
  { id: "l1", name: "Aisle 1", full_path: "Warehouse A → Aisle 1" },
  { id: "l2", name: "Aisle 1", full_path: "Warehouse B → Aisle 1" },
  { id: "l-archived", name: "Fridge B", full_path: "Fridge B" },
];
const placeAsks = vi.hoisted(() => [] as Array<Record<string, unknown>>);
vi.mock("@/lib/api/storages", () => ({
  storagesApi: {
    getPage: (params: { ids?: string[]; q?: string }) => {
      placeAsks.push(params);
      const items = PLACES.filter(
        (place) =>
          (!params.ids || params.ids.includes(place.id)) &&
          (!params.q ||
            place.full_path.toLowerCase().includes(params.q.toLowerCase())),
      );
      return Promise.resolve({
        items,
        total: items.length,
        limit: 100,
        offset: 0,
        has_more: false,
      });
    },
  },
}));

function renderPage() {
  return renderWithProviders(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: vi.fn() }}>
      <StockLevelsPage />
    </PageHeaderContext.Provider>,
  );
}

describe("StockLevelsPage", () => {
  beforeEach(() => {
    searchParams = new URLSearchParams();
    listState = { items: ROWS, total: 1 };
    listSpy.mockClear();
    writeSearchParams.mockClear();
    placeAsks.length = 0;
  });

  it("never subtracts the promise from the stock", () => {
    renderPage();

    const table = screen.getByRole("table");
    // "6 on the shelf, 4 promised, 2 free" -- three numbers, because
    // "2 on the shelf" is a different sentence and a picker cannot plan on it.
    expect(within(table).getByText("6 kg")).toBeInTheDocument();
    expect(within(table).getByText("4 kg")).toBeInTheDocument();
    expect(within(table).getByText("2 kg")).toBeInTheDocument();
  });

  it("says on the shelf that the batch must not be picked", () => {
    renderPage();

    // A recalled batch cannot be picked; until now nothing showed why, and
    // the refusal arrived only at picking time.
    const table = screen.getByRole("table");
    expect(within(table).getByText("Recalled")).toBeInTheDocument();
  });

  it("leads from the shelf to the batch it came from", () => {
    renderPage();

    expect(screen.getByRole("link", { name: "L-7" })).toHaveAttribute(
      "href",
      "/inventory/lots/lot-1",
    );
  });

  it("leaves out the empty storages until asked", async () => {
    const user = userEvent.setup();
    renderPage();

    expect(listSpy).toHaveBeenCalledWith(
      expect.objectContaining({ include_empty: undefined }),
    );

    await user.click(screen.getByRole("button", { name: /filter/i }));
    await user.click(screen.getByLabelText(/Include locations at zero/));

    expect(listSpy).toHaveBeenCalledWith(
      expect.objectContaining({ include_empty: true }),
    );
    expect(searchParams.get("include_empty")).toBe("true");
  });

  it("opens narrowed when a product's own card sends the reader here", () => {
    searchParams = new URLSearchParams("template=p1");

    renderPage();

    expect(listSpy).toHaveBeenCalledWith(
      expect.objectContaining({ product_template_id: "p1" }),
    );
    expect(
      screen.getByRole("button", { name: /Rye flour/ }),
    ).toBeInTheDocument();
  });

  it("narrows the shelf to what the reader types", async () => {
    renderPage();

    // The screen exists to answer "how much of this lies here". A test
    // organization had 143 rows of it and nothing to name a product with, so
    // the only way to one product was paging through all three pages of it.
    await userEvent.type(screen.getByTestId("list-search-input"), "Rye");

    await waitFor(() =>
      expect(listSpy).toHaveBeenLastCalledWith(
        expect.objectContaining({ search: "Rye" }),
      ),
    );
  });

  it("narrows by product and place at once", async () => {
    searchParams = new URLSearchParams("location=l1");
    renderPage();

    await userEvent.type(screen.getByTestId("list-search-input"), "Rye");

    // Two filters, one answer: what the reader typed goes to the server
    // together with the place, never instead of it.
    await waitFor(() =>
      expect(listSpy).toHaveBeenLastCalledWith(
        expect.objectContaining({ search: "Rye", location_id: "l1" }),
      ),
    );
  });

  it("names the search that found nothing, not the storage nobody picked", async () => {
    listState = { items: [], total: 0 };
    renderPage();

    await userEvent.type(screen.getByTestId("list-search-input"), "Rye");

    // With only a search on, the old copy sent the reader to "clear the
    // storage or the search" — one of which was never set.
    expect(await screen.findByText(/search: Rye/)).toBeInTheDocument();
    expect(screen.queryByText(/location:/)).toBeNull();
  });

  it("names the shelf by its path, so two shelves with one name are two places", async () => {
    renderPage();

    const table = screen.getByRole("table");
    expect(
      await within(table).findByText("Warehouse A → Aisle 1"),
    ).toBeInTheDocument();
  });

  it("names the storage the empty shelf was narrowed to by its path", async () => {
    searchParams = new URLSearchParams("location=l1");
    listState = { items: [], total: 0 };

    renderPage();

    expect(
      await screen.findByText(/location: Warehouse A → Aisle 1/),
    ).toBeInTheDocument();
  });

  it("names an archived storage the shelf is narrowed to", async () => {
    searchParams = new URLSearchParams("location=l-archived");
    listState = { items: [], total: 0 };

    renderPage();

    expect(await screen.findByText(/location: Fridge B/)).toBeInTheDocument();
    expect(screen.queryByText(/search:/)).toBeNull();
  });

  it("still names a storage the picker cannot resolve", async () => {
    searchParams = new URLSearchParams("location=l-gone");
    listState = { items: [], total: 0 };

    renderPage();

    expect(
      await screen.findByText(/location: one location/),
    ).toBeInTheDocument();
  });

  it("shows no package column, since nothing can create a package", () => {
    renderPage();

    // Every StockPackage row came from a test seed: no service writes the
    // model and no form has a pallet field, so the column could only ever
    // read "—" down the whole list.
    const table = screen.getByRole("table");
    expect(
      within(table).getByRole("columnheader", { name: "Batch" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("columnheader", { name: /package/i }),
    ).not.toBeInTheDocument();
  });
});

it("distinguishes equally named shelves by the way to them", async () => {
  renderPage();
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /filter/i }));
  await user.click(await screen.findByRole("combobox", { name: "Location" }));
  const rows = (await screen.findAllByText("Aisle 1"))
    .map((title) => title.closest("button"))
    .filter((row): row is HTMLButtonElement => row !== null);
  expect(rows.map((row) => row.textContent)).toEqual(
    expect.arrayContaining([
      expect.stringContaining("Warehouse A"),
      expect.stringContaining("Warehouse B"),
    ]),
  );
});

it("never reads the organization's locations to draw the filter", async () => {
  renderPage();
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /filter/i }));
  await user.click(await screen.findByRole("combobox", { name: "Location" }));
  await screen.findAllByText("Aisle 1");

  // One page of the places on offer, and the places the rows name — each ask
  // is bounded, none walks the catalogue page after page.
  expect(placeAsks.length).toBeGreaterThan(0);
  expect(placeAsks.every((ask) => Number(ask.limit) <= 100)).toBe(true);
  expect(placeAsks.every((ask) => ask.offset === undefined)).toBe(true);
});

it("removes a linked shelf from the address when Anywhere is chosen", async () => {
  searchParams = new URLSearchParams("location=l1&unrelated=kept");
  renderPage();
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /filter/i }));
  await user.click(await screen.findByRole("combobox", { name: "Location" }));
  await user.click(await screen.findByRole("button", { name: /^anywhere$/i }));
  expect(searchParams.has("location")).toBe(false);
  expect(searchParams.get("unrelated")).toBe("kept");
  expect(listSpy).toHaveBeenLastCalledWith(
    expect.objectContaining({ location_id: undefined }),
  );
});
