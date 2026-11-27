import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@/test/utils";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import ImportModal from "./ImportModal";
import { serveLocations } from "@/test/serveLocations";
import { onePage } from "@/test/mocks/page";
import type { StorageLocationSummary } from "@/types";
import {
  makeLocationField,
  makeStorageSummary,
} from "@/test/factories/storage";

const analyzeImport = vi.fn();
const analyzeGrocy = vi.fn();
const mutateAsync = vi.fn();
const grocyMutateAsync = vi.fn();
const toastError = vi.fn();

vi.mock("@/lib/api/items", () => ({
  itemsApi: {
    analyzeImport: (file: File) => analyzeImport(file),
    analyzeGrocy: (file: File) => analyzeGrocy(file),
  },
}));

vi.mock("@/modules/inventory/hooks/useItemMutations", () => ({
  useImportItems: () => ({ mutateAsync }),
  useImportGrocy: () => ({ mutateAsync: grocyMutateAsync }),
}));

// Which keys the account holds, set per test; both by default, as for the
// ordinary member role this wizard was built for.
const canWrite = vi.fn((_moduleName: string) => true);

vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: (moduleName: string) => canWrite(moduleName),
}));

// The stats module's "Show inventory value" switch, on unless a test turns
// it off — as it is for an organization without the stats module.
const inventoryValue = { shown: true };
vi.mock("@/modules/shared/hooks/useShowInventoryValue", () => ({
  useShowInventoryValue: () => inventoryValue.shown,
}));

// The organization's locations, as the listing answers them; none unless a
// test sets the fields some of them ask for.
const storages = { list: [] as StorageLocationSummary[] };

vi.mock("sonner", () => ({
  toast: {
    error: (msg: string) => toastError(msg),
    success: vi.fn(),
  },
}));

async function reachMappingStep() {
  const requests = serveLocations(storages.list);
  render(<ImportModal onClose={vi.fn()} />);
  // The locations' fields shape the mapping the file is suggested, so they
  // are read before a file is picked — as they are by a person who opens the
  // dialog and then browses for the sheet.
  await waitFor(() => expect(requests.length).toBeGreaterThan(0));
  await act(() => new Promise((resolve) => setTimeout(resolve, 50)));
  const input = document.getElementById("import-file") as HTMLInputElement;
  fireEvent.change(input, {
    target: { files: [new File(["x"], "stock.csv")] },
  });
  await screen.findByText(/File analyzed/);
}

describe("ImportModal (products)", () => {
  beforeEach(() => {
    inventoryValue.shown = true;
    storages.list = [];
  });

  /** The exported sheet's price column, as the export names it. */
  const PRICE_HEADER = "Purchase price per unit (USD)";
  const priceSheet = {
    headers: ["Name", "Quantity", PRICE_HEADER],
    preview_rows: [],
    total_rows: 0,
    filled_counts: {},
  };
  const imported = {
    total: 1,
    imported: 1,
    joined_existing: 0,
    updated: 0,
    skipped: 0,
    failed: 0,
    errors: [],
    created_locations: [],
    created_categories: [],
    created_suppliers: [],
    left_behind: [],
    brought_by_modules: [],
  };

  it("maps and sends the price column where the inventory value is shown", async () => {
    analyzeImport.mockResolvedValue(priceSheet);
    mutateAsync.mockResolvedValue(imported);
    await reachMappingStep();

    expect(screen.getByText("Purchase price per unit")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Process Import/ }));
    expect(await screen.findByText("Added 1 product.")).toBeInTheDocument();
    expect(mutateAsync).toHaveBeenLastCalledWith(
      expect.objectContaining({
        mapping: expect.objectContaining({ purchase_price: PRICE_HEADER }),
      }),
    );
  });

  it("says the location fields could not be read, with a retry, instead of leaving their columns out unannounced", async () => {
    analyzeImport.mockResolvedValue(priceSheet);
    server.use(
      http.get("/api/v1/locations", () =>
        HttpResponse.json({ detail: "down" }, { status: 500 }),
      ),
    );
    render(<ImportModal onClose={vi.fn()} />);
    fireEvent.change(
      document.getElementById("import-file") as HTMLInputElement,
      {
        target: { files: [new File(["x"], "stock.csv")] },
      },
    );
    await screen.findByText(/File analyzed/);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "An error occurred",
    );
    expect(
      screen.getByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();
  });

  it("neither offers nor sends the price where the inventory value is not shown", async () => {
    // The column is suggested from the header on its own, so hiding the
    // row alone would still have imported the price behind the reader's back.
    inventoryValue.shown = false;
    analyzeImport.mockResolvedValue(priceSheet);
    mutateAsync.mockResolvedValue(imported);
    await reachMappingStep();

    expect(
      screen.queryByText("Purchase price per unit"),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Process Import/ }));
    expect(await screen.findByText("Added 1 product.")).toBeInTheDocument();
    const { mapping } = mutateAsync.mock.lastCall![0];
    expect(mapping.purchase_price ?? "").toBe("");
    expect(mapping.name).toBe("Name");
  });

  it("keeps the create-missing options on the mapping step, and no Grocy column preset", async () => {
    // Grocy writes no sheet, so a preset for Grocy's columns mapped a file
    // nobody can produce; its tile opens a move that reads Grocy's database.
    analyzeImport.mockResolvedValue({
      headers: ["name", "amount", "location"],
      preview_rows: [],
      total_rows: 0,
      filled_counts: {},
    });
    await reachMappingStep();

    expect(
      screen.queryByRole("button", { name: /Grocy/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", {
        name: "Create missing locations automatically",
      }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", {
        name: "Create missing categories automatically",
      }),
    ).toBeChecked();
    expect(
      screen.getByText(/Every row becomes a new product/),
    ).toBeInTheDocument();
  });

  describe("the move from Grocy's database file", () => {
    const analysis = {
      products: 12,
      stock_entries: 30,
      already_imported: 0,
      locations: 3,
      product_groups: 4,
      stores: 2,
      shopping_list_entries: 5,
      new_locations: ["Pantry", "Chest freezer"],
      new_categories: [],
      new_suppliers: ["Corner shop"],
      currency: "EUR",
      steps: 31,
      left_behind: [
        { what: "recipes", count: 7, names: [] },
        { what: "units_as_pieces", count: 1, names: ["Tin"] },
      ],
    };

    async function reviewGrocyFile() {
      serveLocations(storages.list);
      render(<ImportModal onClose={vi.fn()} />);
      expect(screen.getByText(/one file, grocy\.db/)).toBeInTheDocument();
      const own = document.getElementById(
        "import-file-secondary",
      ) as HTMLInputElement;
      expect(own).toHaveAttribute("accept", ".db,.sqlite,.sqlite3");
      fireEvent.change(own, {
        target: { files: [new File(["x"], "grocy.db")] },
      });
      await screen.findByText("Batches of stock");
    }

    beforeEach(() => {
      analyzeGrocy.mockReset();
      grocyMutateAsync.mockReset();
      analyzeGrocy.mockResolvedValue(analysis);
    });

    it("reviews what the file holds in place of a sheet's columns, before writing anything", async () => {
      await reviewGrocyFile();

      expect(screen.getByText("30")).toBeInTheDocument();
      expect(
        screen.getByText("Locations: Pantry, Chest freezer"),
      ).toBeInTheDocument();
      expect(screen.getByText("Suppliers: Corner shop")).toBeInTheDocument();
      expect(screen.getByText(/Prices are read in EUR/)).toBeInTheDocument();
      expect(
        screen.getByText("Units counted in pieces: Tin"),
      ).toBeInTheDocument();
      expect(analyzeImport).not.toHaveBeenCalled();
      expect(grocyMutateAsync).not.toHaveBeenCalled();
    });

    it("moves the file and says what it created, what modules brought and what stayed", async () => {
      grocyMutateAsync.mockResolvedValue({
        total: 31,
        imported: 31,
        joined_existing: 18,
        updated: 0,
        skipped: 2,
        failed: 0,
        errors: [],
        created_locations: [],
        created_categories: [],
        created_suppliers: ["Corner shop"],
        left_behind: [{ what: "recipes", count: 7, names: [] }],
        brought_by_modules: [
          {
            module: "shopping_lists",
            sentence:
              "Shopping lists from Grocy — lists created: 1, entries: 5",
          },
        ],
      });
      await reviewGrocyFile();

      fireEvent.click(screen.getByRole("button", { name: /Move in/ }));

      expect(await screen.findByText(/Added 13 products/)).toBeInTheDocument();
      expect(grocyMutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({
          file: expect.any(File),
          categoryMatches: {},
        }),
      );
      expect(screen.getByText("1 supplier created")).toBeInTheDocument();
      expect(
        screen.getByText(
          "Shopping lists from Grocy — lists created: 1, entries: 5",
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/2 entries were already here/),
      ).toBeInTheDocument();
      expect(screen.getByText("Stays in Grocy")).toBeInTheDocument();
    });

    it("draws a database, not a spreadsheet, while the file is moved", async () => {
      grocyMutateAsync.mockReturnValue(new Promise(() => {}));
      await reviewGrocyFile();

      fireEvent.click(screen.getByRole("button", { name: /Move in/ }));

      const waiting = (await screen.findByText("Importing Data…")).closest(
        "div.flex-col",
      ) as HTMLElement;
      expect(waiting.querySelector(".lucide-database")).toBeInTheDocument();
      expect(waiting.querySelector(".lucide-file-spreadsheet")).toBeNull();
    });

    it("says which part of the move failed, and counts a refused batch without a sheet's row note", async () => {
      grocyMutateAsync.mockResolvedValue({
        total: 2,
        imported: 1,
        joined_existing: 0,
        updated: 0,
        skipped: 0,
        failed: 1,
        errors: [{ row: 2, error: "Milk: refused" }],
        created_locations: [],
        created_categories: [],
        created_suppliers: [],
        left_behind: [
          { what: "inactive_locations", count: 2, names: [], failed: false },
          { what: "shopping_list_entries", count: 5, names: [], failed: true },
        ],
        brought_by_modules: [],
      });
      await reviewGrocyFile();

      fireEvent.click(screen.getByRole("button", { name: /Move in/ }));

      expect(await screen.findByText("Milk: refused")).toBeInTheDocument();
      expect(
        screen.getByText("Locations switched off in Grocy"),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/Shopping list entries \(bringing them failed/),
      ).toBeInTheDocument();
      expect(screen.queryByText(/module is off/)).not.toBeInTheDocument();
      expect(screen.queryByText(/header row/)).not.toBeInTheDocument();
    });

    it("refuses a file that is not Grocy's with the server's reason and stays at the tiles", async () => {
      analyzeGrocy.mockRejectedValue({
        isAxiosError: true,
        response: {
          status: 400,
          data: {
            detail: {
              code: "GROCY_FILE_UNREADABLE",
              message: "This file is not a database Grocy wrote.",
            },
          },
        },
      });
      serveLocations(storages.list);
      render(<ImportModal onClose={vi.fn()} />);

      fireEvent.change(
        document.getElementById("import-file-secondary") as HTMLInputElement,
        { target: { files: [new File(["x"], "stock.csv")] } },
      );

      await waitFor(() =>
        expect(toastError).toHaveBeenCalledWith(
          "This file is not a database Grocy wrote.",
        ),
      );
      expect(screen.queryByText("Batches of stock")).not.toBeInTheDocument();
    });
  });

  it("warns when the match mode has not one code in the file, and not when codes sit below the preview", async () => {
    // The old warning looked at the mapping only: with the column mapped
    // and empty in every row — the export-reimport round trip of an
    // organization without printed labels — overwrite quietly added
    // duplicates and the summary said so after the fact. The first fix
    // scanned the preview rows, which stop at five: a sheet whose codes
    // start below them warned about a coded sheet. The count the analysis
    // returns is made over the whole file, and the warning reads that.
    analyzeImport.mockResolvedValue({
      headers: ["Name", "Quantity", "Label Code"],
      preview_rows: [
        { Name: "Coffee", Quantity: "1", "Label Code": "" },
        { Name: "Tea", Quantity: "2", "Label Code": null },
      ],
      total_rows: 8,
      filled_counts: { Name: 8, Quantity: 8, "Label Code": 0 },
    });
    const { unmount } = render(<ImportModal onClose={vi.fn()} />);
    const input = document.getElementById("import-file") as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["x"], "stock.csv")] },
    });
    await screen.findByText(/File analyzed/);

    // The mapper suggests by header name, so Label Code lands on label_code.
    fireEvent.click(screen.getByRole("radio", { name: "Overwrite" }));
    expect(
      await screen.findByText(/not a single row carries a code/),
    ).toBeInTheDocument();
    unmount();

    // The same preview — empty in its five rows — with the codes starting
    // below them: the whole-file count lifts the warning, because the mode
    // has codes to work with even though the preview never shows one.
    analyzeImport.mockResolvedValue({
      headers: ["Name", "Quantity", "Label Code"],
      preview_rows: [
        { Name: "Coffee", Quantity: "1", "Label Code": "" },
        { Name: "Tea", Quantity: "2", "Label Code": null },
      ],
      total_rows: 8,
      filled_counts: { Name: 8, Quantity: 8, "Label Code": 2 },
    });
    render(<ImportModal onClose={vi.fn()} />);
    const input2 = document.getElementById("import-file") as HTMLInputElement;
    fireEvent.change(input2, {
      target: { files: [new File(["x"], "stock.csv")] },
    });
    await screen.findByText(/File analyzed/);
    fireEvent.click(screen.getByRole("radio", { name: "Overwrite" }));
    expect(
      screen.queryByText(/not a single row carries a code/),
    ).not.toBeInTheDocument();
  });

  it("hands the file, the mapping and the create-missing choice to the import", async () => {
    analyzeImport.mockResolvedValue({
      headers: ["Name", "Quantity"],
      preview_rows: [],
      total_rows: 0,
      filled_counts: {},
    });
    mutateAsync.mockResolvedValue({
      total: 1,
      imported: 1,
      joined_existing: 0,
      updated: 0,
      skipped: 0,
      failed: 0,
      errors: [],
      created_locations: ["Pantry"],
      created_categories: [],
      created_suppliers: [],
      left_behind: [],
      brought_by_modules: [],
    });
    await reachMappingStep();

    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Create missing locations automatically",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: /Process Import/ }));

    expect(await screen.findByText("Added 1 product.")).toBeInTheDocument();
    expect(screen.getByText("1 location created")).toBeInTheDocument();
    expect(mutateAsync).toHaveBeenCalledWith({
      file: expect.any(File),
      mapping: expect.objectContaining({ name: "Name", quantity: "Quantity" }),
      createLocations: false,
      createCategories: true,
      onLabelMatch: "add",
      locationSlash: "path",
      countAsOne: false,
      onProgress: expect.any(Function),
    });
  });

  it("offers products without stock for a list with no quantity, and sends one of each when asked", async () => {
    analyzeImport.mockResolvedValue({
      headers: ["Name", "Category"],
      preview_rows: [],
      total_rows: 0,
      filled_counts: {},
    });
    mutateAsync.mockResolvedValue(imported);
    await reachMappingStep();

    expect(screen.getByRole("radio", { name: "Products only" })).toBeChecked();
    expect(screen.getByText(/takes its last step/)).toBeInTheDocument();
    expect(
      screen.queryByRole("radio", { name: "Separates levels" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "One of each" }));
    fireEvent.click(screen.getByRole("button", { name: /Process Import/ }));
    await screen.findByText("Added 1 product.");
    expect(mutateAsync).toHaveBeenLastCalledWith(
      expect.objectContaining({ countAsOne: true }),
    );
  });

  it("asks how a slash in a location reads and sends the answer", async () => {
    analyzeImport.mockResolvedValue({
      headers: ["Name", "Quantity", "Location"],
      preview_rows: [],
      total_rows: 0,
      filled_counts: {},
    });
    mutateAsync.mockResolvedValue(imported);
    await reachMappingStep();

    expect(
      screen.getByRole("radio", { name: "Separates levels" }),
    ).toBeChecked();
    expect(
      screen.queryByRole("radio", { name: "Products only" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Part of the name" }));
    fireEvent.click(screen.getByRole("button", { name: /Process Import/ }));
    await screen.findByText("Added 1 product.");
    expect(mutateAsync).toHaveBeenLastCalledWith(
      expect.objectContaining({ locationSlash: "name", countAsOne: false }),
    );
  });

  it("names the columns that hold stock per location, which can be left unread", async () => {
    analyzeImport.mockResolvedValue({
      headers: ["Item Name", "Qty(Warehouse)", "Qty(Shop)"],
      preview_rows: [],
      total_rows: 0,
      filled_counts: {},
    });
    mutateAsync.mockResolvedValue(imported);
    await reachMappingStep();

    const perLocation = screen.getByRole("checkbox", {
      name: /Qty\(Warehouse\), Qty\(Shop\)/,
    });
    expect(perLocation).toBeChecked();
    expect(
      screen.queryByRole("radio", { name: "Products only" }),
    ).not.toBeInTheDocument();
    fireEvent.click(perLocation);
    expect(screen.getByRole("radio", { name: "Products only" })).toBeChecked();
    fireEvent.click(perLocation);
    fireEvent.click(screen.getByRole("button", { name: /Process Import/ }));
    await screen.findByText("Added 1 product.");
    expect(mutateAsync.mock.lastCall![0].mapping).toMatchObject({
      "stock_at:Warehouse": "Qty(Warehouse)",
      "stock_at:Shop": "Qty(Shop)",
    });
  });

  it("shows a toggle only to the account whose key it spends", async () => {
    // One switch wired to both flags left an account holding
    // categories:write but not locations:write no setting under which its
    // permission worked: on, the import was refused; off, the category it
    // asked for was silently dropped.
    canWrite.mockImplementation(
      (moduleName: string) => moduleName === "categories",
    );
    analyzeImport.mockResolvedValue({
      headers: ["name"],
      preview_rows: [],
      total_rows: 0,
      filled_counts: {},
    });
    await reachMappingStep();

    expect(
      screen.queryByRole("checkbox", {
        name: "Create missing locations automatically",
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", {
        name: "Create missing categories automatically",
      }),
    ).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: /Process Import/ }));
    expect(await screen.findByText("Added 1 product.")).toBeInTheDocument();
    expect(mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        createLocations: false,
        createCategories: true,
      }),
    );
  });

  it("reads the gate's refusal to the reader instead of a generic failure", async () => {
    // The refusal a backend gate writes carries its reason and its remedy;
    // the catch shows it to the reader, not a generic "Import failed".
    analyzeImport.mockResolvedValue({
      headers: ["name"],
      preview_rows: [],
      total_rows: 0,
      filled_counts: {},
    });
    mutateAsync.mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 403,
        data: {
          detail: {
            code: "FORBIDDEN",
            message: "This account does not hold categories:write",
          },
        },
      },
    });
    await reachMappingStep();

    fireEvent.click(screen.getByRole("button", { name: /Process Import/ }));

    await vi.waitFor(() => {
      expect(toastError).toHaveBeenCalledWith(
        "This account does not hold categories:write",
      );
    });
  });

  it("sends the chosen update mode and counts what it matched", async () => {
    analyzeImport.mockResolvedValue({
      headers: ["Name", "Label Code"],
      preview_rows: [],
      total_rows: 0,
      filled_counts: {},
    });
    mutateAsync.mockResolvedValue({
      total: 2,
      imported: 0,
      joined_existing: 0,
      updated: 1,
      skipped: 1,
      failed: 0,
      errors: [],
      created_locations: [],
      created_categories: [],
      created_suppliers: [],
      left_behind: [],
      brought_by_modules: [],
    });
    await reachMappingStep();

    fireEvent.click(screen.getByRole("radio", { name: "Overwrite" }));
    expect(screen.getByText(/writes its columns onto it/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Process Import/ }));

    // The first line carries what overwrite did; the count the stats grid
    // has no tile for is no longer left to a box further down.
    expect(await screen.findByText("1 product updated")).toBeInTheDocument();
    expect(screen.getByText("1 product left alone")).toBeInTheDocument();
    expect(mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ onLabelMatch: "overwrite" }),
    );
  });

  it("opens the report with what the overwrite did, not only what it added", async () => {
    // The headline names what the overwrite did as well as what it added, so
    // the first sentence a reader sees carries the effect the mode was chosen for.
    analyzeImport.mockResolvedValue({
      headers: ["Name", "Label Code"],
      preview_rows: [],
      total_rows: 0,
      filled_counts: {},
    });
    mutateAsync.mockResolvedValue({
      total: 3,
      imported: 1,
      joined_existing: 0,
      updated: 2,
      skipped: 0,
      failed: 0,
      errors: [],
      created_locations: [],
      created_categories: [],
      created_suppliers: [],
      left_behind: [],
      brought_by_modules: [],
    });
    await reachMappingStep();

    fireEvent.click(screen.getByRole("button", { name: /Process Import/ }));

    expect(
      await screen.findByText("2 products updated · Added 1 product."),
    ).toBeInTheDocument();
  });

  it("does not call a row filed under an existing product a new product", async () => {
    // Two rows came in; one was another record of a product the shop had.
    analyzeImport.mockResolvedValue({
      headers: ["Name", "Barcode"],
      preview_rows: [],
      total_rows: 0,
      filled_counts: {},
    });
    mutateAsync.mockResolvedValue({
      total: 2,
      imported: 2,
      joined_existing: 1,
      updated: 0,
      skipped: 0,
      failed: 0,
      errors: [],
      created_locations: [],
      created_categories: [],
      created_suppliers: [],
      left_behind: [],
      brought_by_modules: [],
    });
    await reachMappingStep();

    fireEvent.click(screen.getByRole("button", { name: /Process Import/ }));

    expect(
      await screen.findByText(
        "Added 1 product. · 1 record added to a product you already had. It is listed as its own row under the same name.",
      ),
    ).toBeInTheDocument();
  });

  it("warns when the update mode has no Label Code column to match on", async () => {
    analyzeImport.mockResolvedValue({
      headers: ["Name", "Quantity"],
      preview_rows: [],
      total_rows: 0,
      filled_counts: {},
    });
    await reachMappingStep();

    fireEvent.click(screen.getByRole("radio", { name: "Leave alone" }));

    expect(
      screen.getByText(/Map the Label Code column first/),
    ).toBeInTheDocument();
  });

  it("offers the fields locations ask for and maps the columns the export wrote", async () => {
    // A field set on a warehouse applies to every shelf inside it and the
    // form asks for it; the wizard offered only its fixed columns, so the
    // answers a sheet carried were dropped with no failure reported.
    storages.list = [
      makeStorageSummary({
        id: "wh",
        field_definitions: [
          makeLocationField("supplier", { label: "Supplier" }),
          makeLocationField("deposit", { label: "Deposit", type: "money" }),
        ],
      }),
      makeStorageSummary({
        id: "rack",
        parent_id: "wh",
        field_definitions: [
          makeLocationField("opened_on", { label: "Opened on", type: "date" }),
          makeLocationField("supplier", { label: "Supplier" }),
        ],
      }),
    ];
    analyzeImport.mockResolvedValue({
      headers: ["Name", "supplier", "Custom: opened_on"],
      preview_rows: [],
      total_rows: 0,
      filled_counts: {},
    });
    mutateAsync.mockResolvedValue(imported);
    await reachMappingStep();

    expect(await screen.findByText("Opened on")).toBeInTheDocument();
    // A cell carries no currency, so a money field is not offered.
    expect(screen.queryByText("Deposit")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Process Import/ }));
    expect(await screen.findByText("Added 1 product.")).toBeInTheDocument();
    expect(mutateAsync).toHaveBeenLastCalledWith(
      expect.objectContaining({
        mapping: expect.objectContaining({
          "field:supplier": "supplier",
          "field:opened_on": "Custom: opened_on",
        }),
      }),
    );
  });

  it("offers the fields a category asks for and sends the column mapped to a required one", async () => {
    // Every row of a category with a required field of its own was refused,
    // because the wizard could name no column for it.
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json(
          onePage([
            {
              id: "cat-fasteners",
              name: "Fasteners",
              code: null,
              icon: null,
              field_definitions: [
                makeLocationField("thread_size", {
                  label: "Thread size",
                  required: true,
                }),
                makeLocationField("price_tag", {
                  label: "Price tag",
                  type: "money",
                }),
              ],
            },
          ]),
        ),
      ),
    );
    analyzeImport.mockResolvedValue({
      headers: ["Name", "Thread size"],
      preview_rows: [],
      total_rows: 0,
      filled_counts: {},
    });
    mutateAsync.mockResolvedValue(imported);
    await reachMappingStep();

    // The field is a row of the mapping (its label) beside the sheet's own
    // header of the same name.
    expect(
      await screen.findByText("Thread size", { selector: "label" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Price tag")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Process Import/ }));
    await screen.findByText("Added 1 product.");
    expect(mutateAsync).toHaveBeenLastCalledWith(
      expect.objectContaining({
        mapping: expect.objectContaining({
          "field:thread_size": "Thread size",
        }),
      }),
    );
  });

  it("says before processing that a category with a required money field cannot be imported", async () => {
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json(
          onePage([
            {
              id: "cat-loans",
              name: "Loan stock",
              code: null,
              icon: null,
              field_definitions: [
                makeLocationField("replacement", {
                  label: "Replacement Value",
                  type: "money",
                  required: true,
                }),
              ],
            },
          ]),
        ),
      ),
    );
    analyzeImport.mockResolvedValue({
      headers: ["Name"],
      preview_rows: [],
      total_rows: 0,
      filled_counts: {},
    });
    await reachMappingStep();

    expect(await screen.findByRole("note")).toHaveTextContent(
      "Loan stock rows cannot be imported from a file",
    );
    expect(screen.getByRole("note")).toHaveTextContent("Replacement Value");
  });

  it("holds the import back while the category lookup has failed", async () => {
    // A failed lookup read as "no categories": the mapping lacked their
    // fields, no warning showed, and processing failed every row.
    server.use(
      http.get(
        "/api/v1/categories",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    analyzeImport.mockResolvedValue({
      headers: ["Name"],
      preview_rows: [],
      total_rows: 0,
      filled_counts: {},
    });
    await reachMappingStep();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Process Import/ }),
    ).toBeDisabled();
  });
});
