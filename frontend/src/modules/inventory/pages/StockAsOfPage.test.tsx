import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router-dom";
import { renderWithProviders } from "@/test/utils";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { todayIso } from "@/utils/formatters";
import StockAsOfPage, { endOfDay } from "./StockAsOfPage";

const REPORT = {
  as_of: "2026-06-30T23:59:59Z",
  generated_at: "2026-08-29T10:00:00Z",
  complete_from: "2026-05-01T00:00:00Z",
  organization_name: "QA Many",
  currency: "USD",
  value_source: "valuation_layers",
  excluded_currency_rows: 0,
  total_value: "144.84",
  items: [
    {
      product_template_id: "p1",
      product_name: "Rye flour",
      uom_symbol: "kg",
      quantity: "14.000",
      value: "144.84",
    },
    {
      product_template_id: "p2",
      product_name: "Sugar",
      uom_symbol: "kg",
      quantity: "3.000",
      value: null,
    },
  ],
  total: 2,
  limit: 50,
  offset: 0,
  has_more: false,
  unpriced: 1,
};

let state: {
  data?: unknown;
  isError: boolean;
  error?: unknown;
} = { data: REPORT, isError: false };

// What the page asked for, last.
const asked = vi.hoisted(() => ({ query: {} as Record<string, unknown> }));

vi.mock("@/modules/inventory/hooks/useStockAsOf", () => ({
  useStockAsOf: (query: Record<string, unknown>) => {
    asked.query = query;
    return {
      data: state.data,
      isLoading: false,
      isError: state.isError,
      error: state.error,
    };
  },
}));

// The one switch every stock-value surface reads.
const showInventoryValue = vi.hoisted(() => ({ current: true }));
vi.mock("@/modules/shared/hooks/useShowInventoryValue", () => ({
  useShowInventoryValue: () => showInventoryValue.current,
}));

// What the place picker offers. Tests that ask about a filtered day load a
// place into it first.
let locations: { id: string; name: string; full_path?: string }[] = [];

vi.mock("@/lib/api/storages", () => ({
  storagesApi: {
    // The places the screen asks for: the ones named by id or matching the
    // search, one page — never the organization's catalogue.
    getPage: (params: { ids?: string[]; q?: string }) => {
      const items = locations.filter(
        (place) =>
          (!params.ids || params.ids.includes(place.id)) &&
          (!params.q ||
            (place.full_path ?? place.name)
              .toLowerCase()
              .includes(params.q.toLowerCase())),
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
      <StockAsOfPage />
    </PageHeaderContext.Provider>,
  );
}

describe("StockAsOfPage", () => {
  beforeEach(() => {
    state = { data: REPORT, isError: false };
    locations = [];
    showInventoryValue.current = true;
  });

  it("totals what it could price and says what it could not", () => {
    renderPage();

    const table = screen.getByRole("table");
    expect(within(table).getByText("14 kg")).toBeInTheDocument();
    // A product that never went through a priced path is not worth 0.00.
    expect(within(table).getAllByText("—").length).toBeGreaterThan(0);
    expect(
      screen.getByText(
        /1 product has no cost history and is left out of the total/,
      ),
    ).toBeInTheDocument();
  });

  it("counts the products it could not price over every page, not this one", () => {
    // A hundred thousand products are read fifty at a time; the note under
    // the table is about the whole report, as the server counts it.
    state = { data: { ...REPORT, total: 120, unpriced: 7 }, isError: false };
    renderPage();

    expect(
      screen.getByText(
        /7 products have no cost history and are left out of the total/,
      ),
    ).toBeInTheDocument();
  });

  it("reads the report a page at a time", () => {
    state = {
      data: { ...REPORT, total: 120, has_more: true },
      isError: false,
    };
    renderPage();

    expect(asked.query).toMatchObject({ limit: 50, offset: 0 });
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(asked.query).toMatchObject({ limit: 50, offset: 50 });
  });

  it("says from when the ledger can answer at all", () => {
    renderPage();

    expect(
      screen.getByText(/The movement ledger starts on/),
    ).toBeInTheDocument();
  });

  it("prints the refusal where the table would be", () => {
    state = {
      data: undefined,
      isError: true,
      error: {
        isAxiosError: true,
        response: {
          status: 400,
          data: { detail: "The movement ledger starts on 2026-05-01." },
        },
      },
    };

    renderPage();

    // The refusal is the answer, not an error to swallow into a toast.
    expect(
      screen.getByText(/The movement ledger starts on 2026-05-01/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("offers a retry when the server failed rather than refused", () => {
    state = {
      data: undefined,
      isError: true,
      error: { isAxiosError: true, response: { status: 500, data: {} } },
    };

    renderPage();

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(
      within(screen.getByRole("alert")).getByRole("button"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/cannot be answered/i)).not.toBeInTheDocument();
  });

  it("opens on the reader's own day, not the UTC one", () => {
    // West of Greenwich an evening is already tomorrow in UTC, and the
    // report opened on the wrong day for anyone closing the books after
    // their own midnight had passed.
    const original = process.env.TZ;
    process.env.TZ = "America/New_York";
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 8, 11, 20, 0)); // 11 Sep, 20:00 local
    try {
      renderPage();
      expect(screen.getByLabelText("As of")).toHaveTextContent("Sep 11, 2026");
    } finally {
      vi.useRealTimers();
      process.env.TZ = original;
    }
  });

  it("says so when the shelves were empty on that day", () => {
    state = {
      data: { ...REPORT, items: [], total_value: null },
      isError: false,
    };

    renderPage();

    expect(screen.getByText("Nothing was on the shelf")).toBeInTheDocument();
  });

  it("names the storage the empty answer is about", async () => {
    // With a storage picked, "none of the products it records were in
    // stock" answered for the whole organization while the reader was
    // asking about one shelf.
    locations = [{ id: "l1", name: "Rack 9" }];
    state = {
      data: { ...REPORT, items: [], total_value: null },
      isError: false,
    };

    renderPage();
    fireEvent.click(screen.getByRole("combobox", { name: "Location" }));
    fireEvent.click(await screen.findByText("Rack 9"));

    expect(
      await screen.findByText(/Rack 9 — on this date it held none/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/none of the products it records were in stock/),
    ).toBeNull();
  });
});

/**
 * The report stays — what the shelves held is quantity, not a business
 * metric — but where the profile does not show stock value, the money
 * column, its total and the cost-ledger notes go with it. The page used to
 * answer a home organization with prices it keeps nowhere.
 */
describe("StockAsOfPage — a profile that does not show stock value", () => {
  beforeEach(() => {
    state = { data: REPORT, isError: false };
    locations = [];
    showInventoryValue.current = false;
  });

  it("reports quantities with no value column, total or ledger notes", () => {
    renderPage();

    const table = screen.getByRole("table");
    expect(within(table).getByText("Quantity")).toBeInTheDocument();
    expect(within(table).getByText("Rye flour")).toBeInTheDocument();
    expect(within(table).queryByText("Value")).toBeNull();
    expect(screen.queryByText("Total")).toBeNull();
    expect(screen.queryByText(/144\.84/)).toBeNull();
    expect(screen.queryByText(/cost history/i)).toBeNull();
  });

  it("still says from when the ledger can answer", () => {
    renderPage();

    expect(
      screen.getByText(/The movement ledger starts on/),
    ).toBeInTheDocument();
  });

  it("describes the page without the worth it no longer states", () => {
    const setHeader = vi.fn();
    renderWithProviders(
      <PageHeaderContext.Provider value={{ data: {}, setHeader }}>
        <StockAsOfPage />
      </PageHeaderContext.Provider>,
    );

    expect(setHeader).toHaveBeenCalledWith(
      expect.objectContaining({
        subtitle: expect.not.stringContaining("worth"),
      }),
    );
  });
});

describe("endOfDay — the day ends when the reader's day ends", () => {
  function inZone(zone: string, body: () => void): void {
    const original = process.env.TZ;
    process.env.TZ = zone;
    try {
      body();
    } finally {
      process.env.TZ = original;
    }
  }

  it("a Tokyo reader's September 12th ends at 23:59:59.999 JST", () => {
    inZone("Asia/Tokyo", () => {
      expect(endOfDay("2026-09-12")).toBe("2026-09-12T14:59:59.999Z");
    });
  });

  it("a movement booked 02:00 on the thirteenth, Tokyo time, falls outside", () => {
    // The UTC boundary swallowed nine hours of September 13th; the reader's
    // boundary must not.
    inZone("Asia/Tokyo", () => {
      const movement = new Date("2026-09-13T02:00:00+09:00").getTime();
      expect(movement).toBeGreaterThan(
        new Date(endOfDay("2026-09-12")).getTime(),
      );
    });
  });

  it("a New York reader's day runs past the UTC midnight", () => {
    inZone("America/New_York", () => {
      expect(endOfDay("2026-09-12")).toBe("2026-09-13T03:59:59.999Z");
    });
  });

  it("a UTC reader gets the same answer as before", () => {
    inZone("UTC", () => {
      expect(endOfDay("2026-09-12")).toBe("2026-09-12T23:59:59.999Z");
    });
  });
});

it("distinguishes equally named shelves by the way to them", async () => {
  locations = [
    { id: "l1", name: "Aisle 1", full_path: "Warehouse A › Aisle 1" },
    { id: "l2", name: "Aisle 1", full_path: "Warehouse B › Aisle 1" },
  ];
  renderPage();
  fireEvent.click(screen.getByRole("combobox", { name: "Location" }));
  const rows = (await screen.findAllByText("Aisle 1")).map((title) =>
    title.closest("button"),
  );
  expect(rows.map((row) => row?.textContent)).toEqual([
    expect.stringContaining("Warehouse A"),
    expect.stringContaining("Warehouse B"),
  ]);
});

/**
 * The day and the place used to live only in the page's own state: a refresh
 * brought back today and every storage, and a link copied to a colleague
 * opened a different report from the one on screen.
 */
describe("StockAsOfPage — the address carries the report", () => {
  beforeEach(() => {
    state = { data: REPORT, isError: false };
    locations = [{ id: "l1", name: "Rack 9" }];
    showInventoryValue.current = true;
  });

  /** Where the router stands, written out so a test can read it. */
  function Here() {
    return <p data-testid="here">{useLocation().search}</p>;
  }

  function renderAt(path: string) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    return render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: vi.fn() }}>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={[path]}>
            <StockAsOfPage />
            <Here />
          </MemoryRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );
  }

  it("opens on the day and the storage a copied address names", () => {
    renderAt("/inventory/stock/as-of?date=2026-06-30&location=l1");

    expect(asked.query).toMatchObject({
      as_of: endOfDay("2026-06-30"),
      location_id: "l1",
    });
  });

  it("writes the storage the reader picks to the address", async () => {
    renderAt("/inventory/stock/as-of");

    fireEvent.click(screen.getByRole("combobox", { name: "Location" }));
    fireEvent.click(await screen.findByText("Rack 9"));

    expect(screen.getByTestId("here")).toHaveTextContent("?location=l1");
    expect(asked.query).toMatchObject({ location_id: "l1" });
  });

  it("writes another day to the address, and leaves today out of it", () => {
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    const expected = [
      yesterday.getFullYear(),
      String(yesterday.getMonth() + 1).padStart(2, "0"),
      String(yesterday.getDate()).padStart(2, "0"),
    ].join("-");
    renderAt("/inventory/stock/as-of");
    expect(screen.getByTestId("here")).toHaveTextContent(/^$/);

    fireEvent.click(screen.getByRole("combobox", { name: "As of" }));
    fireEvent.click(screen.getByRole("button", { name: "Yesterday" }));

    expect(screen.getByTestId("here")).toHaveTextContent(`?date=${expected}`);
    expect(asked.query).toMatchObject({ as_of: endOfDay(expected) });
  });

  it("answers for today when the address names no day at all", () => {
    // A hand-typed address must not take the page down: there is no end
    // to a day that does not exist.
    renderAt("/inventory/stock/as-of?date=last-tuesday");

    expect(asked.query).toMatchObject({ as_of: endOfDay(todayIso()) });
    expect(screen.getByRole("table")).toBeInTheDocument();
  });
});
