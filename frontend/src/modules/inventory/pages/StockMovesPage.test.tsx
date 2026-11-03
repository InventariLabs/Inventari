import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { TFunction } from "i18next";
import { http, HttpResponse } from "msw";
import { renderWithProviders } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import i18n from "@/i18n/config";
import type { StockMoveRow } from "@/lib/api/stockMoves";
import StockMovesPage, { describeMoveFilters } from "./StockMovesPage";

const listSpy = vi.fn();

// jsdom's location is stubbed in the test setup, so pushState never reaches
// the router. The address the screen opens on is this; what it writes back
// goes to the spy, and `addressAfter` replays those writes.
let searchParams = new URLSearchParams();
const setSearchParams = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useSearchParams: () => [searchParams, setSearchParams],
  };
});

/** The query string after every write the screen made, in order. */
function addressAfter(): string {
  let address = new URLSearchParams(searchParams);
  for (const [update] of setSearchParams.mock.calls) {
    address =
      typeof update === "function"
        ? update(address)
        : new URLSearchParams(update);
  }
  return address.toString();
}

const MOVES: StockMoveRow[] = [
  {
    id: "m1",
    organization_id: "org",
    product_template_id: "p1",
    from_location_id: null,
    to_location_id: "l1",
    quantity: "10.000",
    lot_id: null,
    state: "done",
    reference_type: "document",
    reference_id: "d1",
    created_by: "u1",
    created_at: "2026-06-20T10:00:00Z",
    updated_at: null,
    completed_at: "2026-06-20T10:00:00Z",
    product_name: "Rye flour",
    uom_symbol: "kg",
    from_location_name: null,
    to_location_name: "Aisle 1",
    lot_name: null,
    user_name: "Hanna Kowal",
  },
  {
    id: "m2",
    organization_id: "org",
    product_template_id: "p2",
    from_location_id: "l1",
    to_location_id: "l2",
    quantity: "5.000",
    lot_id: null,
    state: "done",
    // What production writes. The column used to print it verbatim.
    reference_type: "maker_production",
    reference_id: "o1",
    created_by: "u1",
    created_at: "2026-06-20T09:00:00Z",
    updated_at: null,
    completed_at: "2026-06-20T09:00:00Z",
    product_name: "Corn flakes",
    uom_symbol: "pcs.",
    from_location_name: "Aisle 2",
    to_location_name: "Fridge A",
    lot_name: null,
    user_name: "Jan Nowak",
  },
];

// What the ledger answers this render. Tests that care about the empty
// state set it to nothing; the rest leave the two rows.
let listState: { items: StockMoveRow[]; total: number; nextCursor?: string } = {
  items: MOVES,
  total: MOVES.length,
};

vi.mock("@/modules/inventory/hooks/useStockMoves", () => ({
  useStockMoves: (filters: unknown) => {
    listSpy(filters);
    return {
      data: {
        items: listState.items,
        total: listState.total,
        limit: 50,
        offset: 0,
        has_more: Boolean(listState.nextCursor),
        next_cursor: listState.nextCursor ?? null,
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    };
  },
}));

const exportSpy = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api/stockMoves", () => ({
  stockMovesApi: { exportXlsx: (filters: unknown) => exportSpy(filters) },
}));

vi.mock("sonner", () => ({
  toast: { loading: vi.fn(), success: vi.fn(), error: toastError },
}));

vi.mock("@/utils/helpers", async () => {
  const actual = await vi.importActual("@/utils/helpers");
  return { ...actual, downloadBlob: vi.fn() };
});

// The register links a movement to its source, and the source of a document
// move lives in a module that can be switched off. Held here so a test can
// switch one off and read what the column does then.
const enabledModules = vi.hoisted(() => ({ current: ["warehouse", "maker"] }));
vi.mock("@/contexts/ModulesContext", async () => {
  const actual = await vi.importActual("@/contexts/ModulesContext");
  return {
    ...actual,
    useModules: () => ({
      enabledModules: enabledModules.current,
      isLoading: false,
      isModuleEnabled: (name: string) =>
        name === "core" || enabledModules.current.includes(name),
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    }),
  };
});

// The places, as the endpoint answers for them: the ones named by id or
// matching the search. The screen never reads the whole catalogue; the archived
// shelf is nameable because the filter's link outlives the archive.
const PLACES = [
  { id: "l1", name: "Aisle 1", full_path: "Warehouse A › Aisle 1" },
  { id: "l2", name: "Aisle 1", full_path: "Warehouse B › Aisle 1" },
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
      <StockMovesPage />
    </PageHeaderContext.Provider>,
  );
}

describe("StockMovesPage", () => {
  beforeEach(() => {
    searchParams = new URLSearchParams();
    setSearchParams.mockClear();
    listState = { items: MOVES, total: MOVES.length };
    enabledModules.current = ["warehouse", "maker"];
    placeAsks.length = 0;
    exportSpy.mockReset();
    exportSpy.mockResolvedValue(new Blob());
    toastError.mockReset();
    // The register names the page's document sources in one ask, by id.
    server.use(
      http.get("/api/v1/warehouse/documents", ({ request }) => {
        const ids = new URL(request.url).searchParams.getAll("ids");
        return HttpResponse.json({
          items: ids.map((id) => ({ id, number: `IN/2026/${id}` })),
          total: ids.length,
        });
      }),
    );
  });

  it("turns the page by the cursor the page on screen carried, and back", async () => {
    // The ledger is paged by the last row seen: page two is asked for with
    // the first page's cursor, never with a position that would make the
    // server count every row above it.
    listState = { items: MOVES, total: 120, nextCursor: "after-m2" };
    const user = userEvent.setup();
    renderPage();
    listSpy.mockClear();

    await user.click(screen.getByRole("button", { name: "Next page" }));

    expect(listSpy).toHaveBeenLastCalledWith(
      expect.objectContaining({ cursor: "after-m2" }),
    );
    expect(listSpy.mock.lastCall?.[0]).not.toHaveProperty("offset");

    await user.click(screen.getByRole("button", { name: "Previous page" }));

    expect(listSpy.mock.lastCall?.[0].cursor).toBeUndefined();
  });

  it("starts again from the first page when the question changes", async () => {
    listState = { items: MOVES, total: 120, nextCursor: "after-m2" };
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Next page" }));
    expect(listSpy.mock.lastCall?.[0].cursor).toBe("after-m2");

    await user.click(screen.getByRole("tab", { name: "Issued" }));

    expect(listSpy.mock.lastCall?.[0]).toEqual(
      expect.objectContaining({ direction: "out" }),
    );
    expect(listSpy.mock.lastCall?.[0].cursor).toBeUndefined();
  });

  it("reads a movement as a sentence, not as identifiers", () => {
    renderPage();

    const table = screen.getByRole("table");
    expect(within(table).getByText("Rye flour")).toBeInTheDocument();
    expect(within(table).getByText("Aisle 1")).toBeInTheDocument();
    expect(within(table).getByText("Hanna Kowal")).toBeInTheDocument();
    // The unit travels with the number in one string: "10" alone is not a
    // quantity, and the trailing zeros the column serialises are not
    // precision anybody typed.
    expect(within(table).getByText("10 kg")).toBeInTheDocument();
  });

  it("names each end of a movement by its path, so two aisles with one name are two places", async () => {
    renderPage();

    const table = screen.getByRole("table");
    // "Aisle 1" under Warehouse A and "Aisle 1" under Warehouse B: the bare
    // name read as the same place on both ends of the arrow.
    expect(
      (await within(table).findAllByText("Warehouse A › Aisle 1")).length,
    ).toBeGreaterThan(0);
    expect(
      within(table).getByText("Warehouse B › Aisle 1"),
    ).toBeInTheDocument();
  });

  it("names the source of a production move instead of printing the wire value", () => {
    // The translation existed under `production`, and nothing sends that:
    // the backend writes `maker_production`, so `defaultValue` printed the
    // table name — with an underscore, in a column where every other row
    // said a word.
    renderPage();

    const table = screen.getByRole("table");
    expect(within(table).getByText("Production")).toBeInTheDocument();
    expect(within(table).queryByText("maker_production")).toBeNull();
  });

  it("leads to the source itself, not only to its kind", async () => {
    // "Stock take" as an answer to "why did the yoghurt go down" is the kind
    // of thing, not the thing: `reference_id` names which stock take, and the
    // row carried it unused. A recall, or a question about a correction, ends
    // at the record that made it.
    renderPage();

    const table = screen.getByRole("table");
    // Named by its number, which the register answers for the ids on the
    // page — asked as ids=d1, the parameter the server reads.
    const toDocument = await within(table).findByRole("link", {
      name: "Document IN/2026/d1",
    });
    expect(toDocument).toHaveAttribute("href", "/warehouse/documents/d1");
    const toProduction = within(table).getByRole("link", {
      name: "Production",
    });
    expect(toProduction).toHaveAttribute("href", "/maker/production/o1");
  });

  it("stops offering the link when the module that owns the page is off", () => {
    // A badge that leads to the "this module is switched off" wall explains
    // less than a badge.
    enabledModules.current = ["maker"];
    renderPage();

    const table = screen.getByRole("table");
    expect(within(table).getByText("Document")).toBeInTheDocument();
    expect(within(table).queryByRole("link", { name: "Document" })).toBeNull();
    expect(
      within(table).getByRole("link", { name: "Production" }),
    ).toBeInTheDocument();
  });

  it("leaves a source with no page of its own as a plain badge", () => {
    // The ItemHistory backfill's rows point at a record nothing renders. A
    // link there would be a link to a wall.
    MOVES.push({
      ...MOVES[0],
      id: "m3",
      reference_type: "item_history",
      reference_id: "h1",
      product_name: "Oat bran",
    });
    try {
      renderPage();

      const table = screen.getByRole("table");
      expect(within(table).getByText("Historical record")).toBeInTheDocument();
      expect(
        within(table).queryByRole("link", { name: "Historical record" }),
      ).toBeNull();
    } finally {
      MOVES.pop();
    }
  });

  it("says where goods with no origin came from", () => {
    renderPage();

    // A receipt has no from-location. The cell must say so rather than
    // leaving the reader with an arrow pointing at nothing. Both renderings
    // are in the DOM under jsdom -- the split is a media query -- so this
    // asks the table, which is the one the rule is about.
    const table = screen.getByRole("table");
    expect(within(table).getByText("outside")).toBeInTheDocument();
  });

  it("declines the outside by the end of the arrow it stands on", async () => {
    // An issue never comes from anywhere -- it leaves. One word for both
    // ends made every Polish issue read as if the goods had arrived from
    // outside on their way out, so the two ends get two words.
    MOVES.push({
      ...MOVES[0],
      id: "m4",
      product_name: "Oat milk",
      from_location_id: "l1",
      from_location_name: "Aisle 1",
      to_location_id: null,
      to_location_name: null,
    });
    try {
      await i18n.changeLanguage("pl");
      renderPage();

      const table = screen.getByRole("table");
      const receipt = within(table).getByText("Rye flour").closest("tr")!;
      expect(within(receipt).getByText("z zewnątrz")).toBeInTheDocument();
      const issue = within(table).getByText("Oat milk").closest("tr")!;
      expect(within(issue).getByText("na zewnątrz")).toBeInTheDocument();
      expect(within(issue).queryByText("z zewnątrz")).toBeNull();

      // Both renderings carry the decline: the table cell and the phone
      // card are the same rule in two shapes.
      expect(screen.getAllByText("z zewnątrz").length).toBeGreaterThanOrEqual(
        2,
      );
      expect(screen.getAllByText("na zewnątrz").length).toBeGreaterThanOrEqual(
        2,
      );
    } finally {
      MOVES.pop();
      await i18n.changeLanguage("en");
    }
  });

  it("orders by when the goods moved and says so to a screen reader", () => {
    renderPage();

    const sorted = screen.getByRole("columnheader", { name: "When" });
    expect(sorted).toHaveAttribute("aria-sort", "descending");
    // Only the column the order is on carries it.
    expect(
      screen.getByRole("columnheader", { name: "Product" }),
    ).not.toHaveAttribute("aria-sort");
  });

  it("asks the ledger a narrower question when a direction is picked", async () => {
    const user = userEvent.setup();
    renderPage();
    listSpy.mockClear();

    await user.click(screen.getByRole("tab", { name: "Issued" }));

    expect(listSpy).toHaveBeenCalledWith(
      expect.objectContaining({ direction: "out" }),
    );
  });

  it("does not ask for a direction when the reader wants all of them", () => {
    renderPage();

    expect(listSpy).toHaveBeenCalledWith(
      expect.objectContaining({ direction: undefined }),
    );
  });

  it("opens already narrowed when a product's own card sends the reader here", () => {
    searchParams = new URLSearchParams("template=p1");
    listSpy.mockClear();

    renderPage();

    expect(listSpy).toHaveBeenCalledWith(
      expect.objectContaining({ product_template_id: "p1" }),
    );
    // A filter with no control of its own has to be visible, or the reader
    // is looking at a narrowed ledger with nothing saying so.
    expect(
      screen.getByRole("button", { name: /Rye flour/ }),
    ).toBeInTheDocument();
  });

  it("gives the product filter back", async () => {
    searchParams = new URLSearchParams("template=p1");
    const user = userEvent.setup();
    renderPage();
    listSpy.mockClear();

    await user.click(screen.getByRole("button", { name: /Rye flour/ }));

    expect(listSpy).toHaveBeenCalledWith(
      expect.objectContaining({ product_template_id: undefined }),
    );
  });

  it("opens on a location when a storage page sends the reader here", () => {
    searchParams = new URLSearchParams("location=l1");
    listSpy.mockClear();

    renderPage();

    expect(listSpy).toHaveBeenCalledWith(
      expect.objectContaining({ location_id: "l1" }),
    );
  });

  // A refresh, or a link copied to a colleague, used to drop every filter
  // the reader had set: the screen read the address once and never wrote it.
  it("writes the direction to the address, replacing the entry", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("tab", { name: "Issued" }));

    expect(addressAfter()).toBe("direction=out");
    expect(setSearchParams).toHaveBeenLastCalledWith(expect.any(Function), {
      replace: true,
    });
  });

  it("writes the storage the reader picks to the address", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /filter/i }));
    await user.click(await screen.findByRole("combobox", { name: "Location" }));
    const shelf = (await screen.findAllByText("Aisle 1"))
      .map((title) => title.closest("button"))
      .find((row) => row?.textContent?.includes("Warehouse A"));

    await user.click(shelf!);

    expect(addressAfter()).toBe("location=l1");
    expect(listSpy).toHaveBeenLastCalledWith(
      expect.objectContaining({ location_id: "l1" }),
    );
  });

  it("opens on the direction and days a copied address carries", () => {
    searchParams = new URLSearchParams(
      "direction=in&since=2026-06-01&until=2026-06-30",
    );
    listSpy.mockClear();

    renderPage();

    expect(listSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        direction: "in",
        since: "2026-06-01",
        until: "2026-06-30",
      }),
    );
    expect(screen.getByRole("tab", { name: "Received" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("reads a direction it does not know as all of them", () => {
    searchParams = new URLSearchParams("direction=sideways");

    renderPage();

    expect(listSpy).toHaveBeenLastCalledWith(
      expect.objectContaining({ direction: undefined }),
    );
  });

  it("takes the product off the address when the filter is given back", async () => {
    searchParams = new URLSearchParams("template=p1&location=l1");
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /Rye flour/ }));

    expect(addressAfter()).toBe("location=l1");
  });

  it("hands the sheet the question that is on screen", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("tab", { name: "Issued" }));
    await user.click(screen.getByRole("button", { name: /export/i }));

    // Not the paging: the file carries every matching row, and offset/limit
    // would silently cut it to one page.
    expect(exportSpy).toHaveBeenCalledWith(
      expect.objectContaining({ direction: "out" }),
    );
    const asked = exportSpy.mock.calls[0][0] as Record<string, unknown>;
    expect(asked).not.toHaveProperty("limit");
    expect(asked).not.toHaveProperty("cursor");
    expect(asked).not.toHaveProperty("offset");
  });

  it('repeats the refusal instead of replacing it with "export failed"', async () => {
    exportSpy.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 400,
        data: { detail: "80000 movements match — narrow the dates." },
      },
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /export/i }));

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        expect.stringContaining("80000"),
        expect.anything(),
      ),
    );
  });

  it("names the filter that is set, not the ones that are not", async () => {
    // The direction tab was the only narrowing on, and the hint sent the
    // reader to dates and storage — controls that were not even open.
    listState = { items: [], total: 0 };
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("tab", { name: "Issued" }));

    expect(
      await screen.findByText(
        /No movement matches the filter you set \(direction: Issued\)/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/dates:/)).toBeNull();
    expect(screen.queryByText(/location:/)).toBeNull();
  });

  it("names the storage the ledger was narrowed to", async () => {
    searchParams = new URLSearchParams("location=l1");
    listState = { items: [], total: 0 };

    renderPage();

    // Two aisles share the name; the hint says which one is the filter, the
    // way the picker above it does.
    expect(
      await screen.findByText(/\(location: Warehouse A › Aisle 1\)/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/direction:/)).toBeNull();
  });

  it("names an archived storage the ledger is still narrowed to", async () => {
    // The storage card links here, and archiving the storage afterwards
    // used to turn the hint into "filters you set ()" — a filter named by
    // nothing, on the one path a reader can actually reach. The picker
    // reads archived storages as well.
    searchParams = new URLSearchParams("location=l-archived");
    listState = { items: [], total: 0 };

    renderPage();

    expect(
      await screen.findByText(/\(location: Fridge B\)/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/filters you set \(\)/)).toBeNull();
  });

  it("still names a storage the picker cannot resolve", async () => {
    // Past the archived read there is nothing left to look up: a deleted
    // row, a failed request. Empty parentheses would name nothing, so the
    // hint falls back the way a product filter does.
    searchParams = new URLSearchParams("location=l-gone");
    listState = { items: [], total: 0 };

    renderPage();

    expect(
      await screen.findByText(/\(location: one location\)/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/filters you set \(\)/)).toBeNull();
  });
});

describe("describeMoveFilters", () => {
  const t = i18n.t.bind(i18n) as unknown as TFunction;

  it("names only what the reader set", () => {
    expect(
      describeMoveFilters(t, {
        direction: "out",
        locationName: undefined,
        since: "",
        until: "",
        productName: undefined,
      }),
    ).toEqual(["direction: Issued"]);
  });

  it("describes an open date range without inventing the other end", () => {
    expect(
      describeMoveFilters(t, {
        direction: "all",
        locationName: "Aisle 1",
        since: "2026-08-01",
        until: "",
        productName: undefined,
      }),
    ).toEqual(["location: Aisle 1", "dates: from Aug 1, 2026"]);
  });

  it("names the product the ledger is narrowed to", () => {
    expect(
      describeMoveFilters(t, {
        direction: "all",
        locationName: undefined,
        since: "",
        until: "",
        productName: "Rye flour",
      }),
    ).toEqual(["product: Rye flour"]);
  });
});

it("distinguishes equally named shelves by the way to them", async () => {
  renderPage();
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /filter/i }));
  await user.click(await screen.findByRole("combobox", { name: "Location" }));
  const rows = (await screen.findAllByText("Aisle 1")).map((title) =>
    title.closest("button"),
  );
  expect(rows.map((row) => row?.textContent)).toEqual(
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

  // One page of the places on offer and the places the rows name: each ask is
  // bounded and none walks the catalogue page after page.
  expect(placeAsks.length).toBeGreaterThan(0);
  expect(placeAsks.every((ask) => Number(ask.limit) <= 100)).toBe(true);
  expect(placeAsks.every((ask) => ask.offset === undefined)).toBe(true);
});
