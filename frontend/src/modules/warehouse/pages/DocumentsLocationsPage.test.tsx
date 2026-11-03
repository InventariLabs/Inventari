import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { onePage } from "@/test/mocks/page";
import { fireEvent, render, screen, waitFor, within } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { useFormGuardStore } from "@/store/formGuardStore";
import DocumentsLocationsPage from "./DocumentsLocationsPage";

const warehouse = {
  id: "w1",
  name: "Main Warehouse",
  parent_id: null,
  short_code: "W",
  sequence: null,
  usage: "internal",
  items_count: 0,
  subtree_items_count: 0,
  children: [] as unknown[],
};

const shelfA = {
  id: "shelf-a",
  name: "Shelf A",
  parent_id: "w1",
  short_code: "A-01",
  sequence: 10,
  usage: "internal",
  items_count: 3,
  subtree_items_count: 3,
  children: [],
};

const shelfB = {
  ...shelfA,
  id: "shelf-b",
  name: "Shelf B",
  short_code: "A-02",
  sequence: 20,
  items_count: 1,
  subtree_items_count: 1,
};

const shelfC = {
  ...shelfA,
  id: "shelf-c",
  name: "Shelf C",
  short_code: "A-03",
  sequence: 30,
  items_count: 0,
  subtree_items_count: 0,
};

const capacityEntries = [
  {
    id: "cap-1",
    organization_id: "org",
    location_id: "shelf-a",
    product_template_id: "p1",
    max_quantity: "200",
    location_name: "Shelf A",
    product_template_name: "Product One",
    product_unit_symbol: "kg",
    reorder_max_quantity: null,
    reorder_over_capacity: false,
  },
  {
    id: "cap-2",
    organization_id: "org",
    location_id: "shelf-a",
    product_template_id: "p2",
    max_quantity: "50",
    location_name: "Shelf A",
    product_template_name: "Product Two",
    product_unit_symbol: "pcs",
    reorder_max_quantity: null,
    reorder_over_capacity: false,
  },
];

const occupancy = {
  locations: [
    {
      location_id: "shelf-a",
      location_name: "Shelf A",
      entries: [],
      capacity_product_name: "Product One",
      capacity_used: "100",
      capacity_max: "200",
      capped_products: 2,
      fill: 50,
      status: "ok",
      unmeasured: false,
      items_count: 3,
    },
    {
      location_id: "shelf-b",
      location_name: "Shelf B",
      entries: [],
      capacity_product_name: null,
      capacity_used: null,
      capacity_max: null,
      capped_products: 0,
      fill: null,
      status: "no_limit",
      unmeasured: true,
      items_count: 4,
    },
  ],
  signals: [],
};

const shelfCodes = {
  warehouse_id: "w1",
  template: "{zone}-{rack:02}-{level:02}",
  is_tree: true,
  stored: false,
  default_template: "{zone}-{rack:02}-{level:02}",
  reprint: [] as unknown[],
};

beforeEach(() => {
  // The walk order is a storage-register write; the mix and the limits belong
  // to documents. A full warehouse user holds both, and the tests below that
  // separate the two say so explicitly.
  signInWith(["warehouse:read", "warehouse:write", "locations:write"]);
});

afterEach(() => {
  signOut();
  useFormGuardStore.getState().setDirtyForm(null);
});

interface TreeNode {
  id: string;
  name: string;
  parent_id: string | null;
  children: TreeNode[];
  [key: string]: unknown;
}

/** The tree the tests write as nested nodes, as the locations list answers it. */
function flatRows(nodes: TreeNode[], above = ""): Record<string, unknown>[] {
  return nodes.flatMap((node) => {
    const { children, ...row } = node;
    const full_path = above ? `${above} → ${node.name}` : node.name;
    return [
      { ...row, full_path, direct_children_count: children.length },
      ...flatRows(children, full_path),
    ];
  });
}

/** `GET /locations` over those rows: top level, `under`, `ids`, `q`, paging. */
function serveLocations(
  tree: TreeNode[] | (() => TreeNode[]),
  onTableRead?: () => void,
) {
  const below = (rows: Record<string, unknown>[], id: string): Set<string> => {
    const ids = new Set<string>();
    const walk = (parent: string) =>
      rows
        .filter((row) => row.parent_id === parent)
        .forEach((row) => {
          ids.add(row.id as string);
          walk(row.id as string);
        });
    walk(id);
    return ids;
  };
  return http.get("/api/v1/locations", ({ request }) => {
    const rows = flatRows(typeof tree === "function" ? tree() : tree);
    const params = new URL(request.url).searchParams;
    const under = params.get("under");
    if (under && Number(params.get("offset") ?? 0) === 0) onTableRead?.();
    const ids = params.getAll("ids");
    const needle = params.get("q")?.toLowerCase();
    const limit = Number(params.get("limit") ?? 50);
    const offset = Number(params.get("offset") ?? 0);
    const matching = rows.filter(
      (row) =>
        (!params.get("top_level") || row.parent_id === null) &&
        (!under || below(rows, under).has(row.id as string)) &&
        (ids.length === 0 || ids.includes(row.id as string)) &&
        (!needle ||
          [row.name, row.short_code, row.full_path].some((field) =>
            String(field ?? "")
              .toLowerCase()
              .includes(needle),
          )),
    );
    const items = matching.slice(offset, offset + limit);
    return HttpResponse.json({
      items,
      total: matching.length,
      limit,
      offset,
      has_more: offset + items.length < matching.length,
    });
  });
}

function serveOverview(options?: {
  tree?: unknown[];
  settings?: unknown[];
  occupancy?: unknown;
  onStorageUpdate?: (body: unknown) => void;
  onSettingUpdate?: (body: unknown) => void;
  onCapacityUpdate?: (body: unknown) => void;
  onCapacityCreate?: (body: unknown) => void;
  codes?: unknown;
}) {
  server.use(
    http.get("/api/v1/locations/:id/codes", () =>
      HttpResponse.json(options?.codes ?? shelfCodes),
    ),
    serveLocations(
      (options?.tree as TreeNode[] | undefined) ?? [
        { ...warehouse, children: [shelfA, shelfB, shelfC] },
      ],
    ),
    http.get("/api/v1/warehouse/putaway/capacity", () =>
      HttpResponse.json(onePage(capacityEntries)),
    ),
    http.get("/api/v1/warehouse/putaway/capacity-settings", () =>
      HttpResponse.json(
        onePage(
          options?.settings ?? [
            { location_id: "shelf-a", single_product: true },
          ],
        ),
      ),
    ),
    http.get(
      "/api/v1/warehouse/putaway/capacity-settings/:locationId",
      ({ params }) => {
        const rows = (options?.settings ?? [
          { location_id: "shelf-a", single_product: true },
        ]) as { location_id: string; single_product: boolean }[];
        for (const row of rows) {
          if (row.location_id === params.locationId) {
            return HttpResponse.json(row);
          }
        }
        return HttpResponse.json({
          location_id: params.locationId,
          single_product: false,
        });
      },
    ),
    http.put(
      "/api/v1/warehouse/putaway/capacity-settings/:locationId",
      async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        options?.onSettingUpdate?.(body);
        return HttpResponse.json({ location_id: "shelf-a", ...body });
      },
    ),
    http.get("/api/v1/warehouse/putaway/occupancy/:locationId", () =>
      HttpResponse.json(options?.occupancy ?? occupancy),
    ),
    http.put("/api/v1/locations/:id", async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      options?.onStorageUpdate?.(body);
      return HttpResponse.json({ ...shelfA, ...body });
    }),
    http.put(
      "/api/v1/warehouse/putaway/capacity/:entryId",
      async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        options?.onCapacityUpdate?.(body);
        return HttpResponse.json({
          ...capacityEntries[0],
          ...body,
        });
      },
    ),
    http.post("/api/v1/warehouse/putaway/capacity", async ({ request }) => {
      const body = (await request.json()) as {
        location_id: string;
        product_template_id: string;
        max_quantity: string;
      };
      options?.onCapacityCreate?.(body);
      return HttpResponse.json(
        {
          ...capacityEntries[0],
          id: "cap-new",
          ...body,
        },
        { status: 201 },
      );
    }),
  );
}

describe("DocumentsLocationsPage — the shelves of one warehouse", () => {
  it("shows the walk order, mix, limits and occupancy of each shelf", async () => {
    serveOverview();
    render(<DocumentsLocationsPage />);

    expect(await screen.findByText("Shelf A")).toBeInTheDocument();
    expect(screen.getByText("Shelf B")).toBeInTheDocument();

    const rowA = screen.getByText("Shelf A").closest("tr")!;
    expect(within(rowA).getByText("A-01")).toBeInTheDocument();
    expect(within(rowA).getByText("10")).toBeInTheDocument();
    expect(within(rowA).getByText("One product")).toBeInTheDocument();
    expect(within(rowA).getByText("2 product limits")).toBeInTheDocument();
    // Two limited products share this shelf: its fill is the sum of their
    // shares, the number the planner decides by. One product's own pair
    // alone would call a half-full shelf half empty.
    expect(
      await screen.findByText(
        "50% — the shares of 2 limited products added up",
      ),
    ).toBeInTheDocument();
    expect(within(rowA).queryByText("100/200")).not.toBeInTheDocument();
    expect(within(rowA).getByRole("meter")).toHaveAttribute(
      "aria-valuenow",
      "50",
    );

    // A shelf nobody capped has no fill: the line counts records instead of
    // drawing a percentage that would mean zero units.
    const rowB = screen.getByText("Shelf B").closest("tr")!;
    expect(within(rowB).getByText("Different products")).toBeInTheDocument();
    expect(within(rowB).getByText("No limit")).toBeInTheDocument();
    expect(within(rowB).getByText("No limit · 4 records")).toBeInTheDocument();
  });

  it("reads a page of the warehouse at a time, never the whole tree", async () => {
    const shelves = Array.from({ length: 130 }, (_, n) => ({
      ...shelfA,
      id: `bulk-${n}`,
      name: `Bulk shelf ${String(n).padStart(3, "0")}`,
      short_code: `B-${n}`,
      sequence: n + 1,
    }));
    const asked: string[] = [];
    serveOverview({ tree: [{ ...warehouse, children: shelves }] });
    server.use(
      http.get("/api/v1/locations/tree", () => {
        asked.push("tree");
        return HttpResponse.json([]);
      }),
    );
    render(<DocumentsLocationsPage />);

    await screen.findByText("Bulk shelf 000");
    // The warehouse and the first hundred below it; the rest waits.
    expect(
      screen.getAllByRole("checkbox", { name: /^Select (?!all)/ }),
    ).toHaveLength(101);
    expect(screen.queryByText("Bulk shelf 129")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Show more" }));

    expect(await screen.findByText("Bulk shelf 129")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Show more" }),
    ).not.toBeInTheDocument();
    expect(asked).toEqual([]);
  });

  it("says when stock without a limit is left out of the percentage", async () => {
    // A cap for a product that is not on the shelf reads 0/200 while 28
    // other records stand there uncapped. The percentage counts only the
    // limited product, so the cell has to say the rest is not counted.
    serveOverview({
      occupancy: {
        locations: [
          {
            location_id: "shelf-a",
            location_name: "Shelf A",
            entries: [
              {
                product_template_id: "milk",
                product_template_name: "UHT Milk",
                product_unit_symbol: "l",
                quantity: "0",
                max_quantity: "200",
                share: 0,
              },
            ],
            capacity_product_name: "UHT Milk",
            capacity_used: "0",
            capacity_max: "200",
            capped_products: 1,
            fill: 0,
            status: "empty",
            unmeasured: true,
            items_count: 28,
          },
        ],
        signals: [],
      },
    });
    render(<DocumentsLocationsPage />);

    const rowA = (await screen.findByText("Shelf A")).closest("tr")!;
    // The pair speaks the limit's unit, as the limit itself does.
    expect(await within(rowA).findByText("0/200 l")).toBeInTheDocument();
    expect(
      within(rowA).getByText("A product here has no limit and is not counted"),
    ).toBeInTheDocument();
  });

  it("marks the unit missing rather than inventing one for a product without it", async () => {
    serveOverview({
      occupancy: {
        locations: [
          {
            location_id: "shelf-a",
            location_name: "Shelf A",
            entries: [
              {
                product_template_id: "bolts",
                product_template_name: "Bolts",
                product_unit_symbol: null,
                quantity: "7",
                max_quantity: "10",
                share: 70,
              },
            ],
            capacity_product_name: "Bolts",
            capacity_used: "7",
            capacity_max: "10",
            capped_products: 1,
            fill: 70,
            status: "ok",
            unmeasured: false,
            items_count: 1,
          },
        ],
        signals: [],
      },
    });
    render(<DocumentsLocationsPage />);

    const rowA = (await screen.findByText("Shelf A")).closest("tr")!;
    expect(await within(rowA).findByText("7/10 —")).toHaveAttribute(
      "title",
      "No unit of measure recorded for this product",
    );
  });

  it("says what is missing before a limit can be added", async () => {
    serveOverview();
    render(<DocumentsLocationsPage />);

    await userEvent.click(await screen.findByText("Shelf A"));
    expect(
      await screen.findByRole("heading", { name: "Location settings" }),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Add limit" }));

    expect(screen.getByText("Choose a product.")).toBeInTheDocument();
    expect(
      screen.getByText("Enter how much this location holds."),
    ).toBeInTheDocument();
  });

  it("saves the walk order, the mix and an edited limit together", async () => {
    let storageUpdate: unknown;
    let settingUpdate: unknown;
    let capacityUpdate: unknown;
    serveOverview({
      onStorageUpdate: (body) => {
        storageUpdate = body;
      },
      onSettingUpdate: (body) => {
        settingUpdate = body;
      },
      onCapacityUpdate: (body) => {
        capacityUpdate = body;
      },
    });
    render(<DocumentsLocationsPage />);

    await userEvent.click(await screen.findByText("Shelf A"));

    const sequence = await screen.findByLabelText("Walk order");
    await userEvent.clear(sequence);
    await userEvent.type(sequence, "30");

    await userEvent.click(
      screen.getByRole("radio", { name: /Different products/ }),
    );

    const quantity = screen.getByLabelText("Limit for Product One");
    await userEvent.clear(quantity);
    await userEvent.type(quantity, "150");

    // Nothing has been written while the panel is open.
    expect(storageUpdate).toBeUndefined();
    expect(settingUpdate).toBeUndefined();
    expect(capacityUpdate).toBeUndefined();

    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => {
      expect(storageUpdate).toEqual({ sequence: 30 });
      expect(settingUpdate).toEqual({ single_product: false });
      expect(capacityUpdate).toEqual({ max_quantity: "150" });
    });
  });

  it("numbers the selected shelves in the order shown", async () => {
    const updates: unknown[] = [];
    serveOverview({
      onStorageUpdate: (body) => updates.push(body),
    });
    render(<DocumentsLocationsPage />);

    await screen.findByText("Shelf A");
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Select Shelf A" }),
    );
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Select Shelf B" }),
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Number walk order in sequence" }),
    );
    const confirmation = await screen.findByRole("alertdialog");
    await userEvent.click(
      within(confirmation).getByRole("button", {
        name: "Number walk order in sequence",
      }),
    );

    await waitFor(() => {
      expect(updates).toEqual([{ sequence: 10 }, { sequence: 20 }]);
    });
  });

  it("numbers every ticked shelf, also those a later search no longer shows", async () => {
    const updates: unknown[] = [];
    serveOverview({
      onStorageUpdate: (body) => updates.push(body),
    });
    render(<DocumentsLocationsPage />);

    await screen.findByText("Shelf A");
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Select Shelf A" }),
    );
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Select Shelf B" }),
    );
    await userEvent.type(
      screen.getByPlaceholderText("Search by location name or code"),
      "Shelf A",
    );
    await waitFor(() => {
      expect(screen.queryByText("Shelf B")).not.toBeInTheDocument();
    });

    await userEvent.click(
      screen.getByRole("button", { name: "Number walk order in sequence" }),
    );
    const confirmation = await screen.findByRole("alertdialog");
    await userEvent.click(
      within(confirmation).getByRole("button", {
        name: "Number walk order in sequence",
      }),
    );

    await waitFor(() => {
      expect(updates).toEqual([{ sequence: 10 }, { sequence: 20 }]);
    });
  });

  it("lists stock-holding parents and standalone locations, not only the leaves", async () => {
    const fridgeA = {
      ...shelfA,
      id: "fridge-a",
      name: "Fridge A",
      parent_id: "w1",
      short_code: "SEED-3VDX",
      sequence: 3,
      items_count: 27,
      subtree_items_count: 30,
      children: [
        {
          ...shelfA,
          id: "shelf-a1",
          name: "Shelf A1",
          parent_id: "fridge-a",
          short_code: "A-11",
        },
        {
          ...shelfB,
          id: "shelf-a2",
          name: "Shelf A2",
          parent_id: "fridge-a",
          short_code: "A-12",
        },
      ],
    };
    const quarantine = {
      ...warehouse,
      id: "quarantine",
      name: "Quarantine",
      short_code: "Q-01",
      sequence: 5,
      items_count: 0,
      subtree_items_count: 0,
      children: [],
    };
    serveOverview({
      tree: [{ ...warehouse, children: [fridgeA, shelfC] }, quarantine],
    });
    render(<DocumentsLocationsPage />);

    // Fridge A holds stock itself — its walk order and limits are settings
    // this table exists for — so it is a row, not only a heading over its
    // two shelves.
    expect(
      await screen.findByRole("button", { name: /Fridge A/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Shelf A1/ }),
    ).toBeInTheDocument();

    // The code on its label finds it too.
    const search = screen.getByPlaceholderText(
      "Search by location name or code",
    );
    await userEvent.type(search, "SEED-3VDX");
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: /Shelf A1/ }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: /Fridge A/ }),
    ).toBeInTheDocument();

    // A standalone location is a filter of its own even when the
    // organization also keeps a deeper tree.
    await userEvent.clear(search);
    await userEvent.click(screen.getByRole("combobox", { name: /Location/ }));
    await userEvent.click(await screen.findByText("Quarantine"));
    expect(
      await screen.findByRole("button", { name: /Quarantine/ }),
    ).toBeInTheDocument();
  });

  it("writes the limit still open in the add row with the same Save", async () => {
    let created: unknown;
    serveOverview({
      onCapacityCreate: (body) => {
        created = body;
      },
    });
    server.use(
      http.get("/api/v1/warehouse/product-search", () =>
        HttpResponse.json([
          {
            product_template_id: "p-uht",
            name: "UHT Milk",
            sku: "MILK-1",
            uom_symbol: "l",
          },
        ]),
      ),
    );
    render(<DocumentsLocationsPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: /Shelf A/ }),
    );
    fireEvent.change(await screen.findByLabelText("1. Product"), {
      target: { value: "UHT" },
    });
    await userEvent.click(await screen.findByText("UHT Milk"));
    await userEvent.type(screen.getByLabelText("2. Holds up to"), "200");

    // Typed but not added is still unsaved work.
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => {
      expect(created).toEqual({
        location_id: "shelf-a",
        product_template_id: "p-uht",
        max_quantity: "200",
      });
    });
  });

  it("names the unit when a new limit falls under what replenishment asks", async () => {
    const warning = vi.spyOn(toast, "warning");
    serveOverview();
    server.use(
      http.get("/api/v1/warehouse/product-search", () =>
        HttpResponse.json([
          {
            product_template_id: "p-uht",
            name: "UHT Milk",
            sku: "MILK-1",
            uom_symbol: "l",
          },
        ]),
      ),
      http.post("/api/v1/warehouse/putaway/capacity", () =>
        HttpResponse.json(
          {
            ...capacityEntries[0],
            id: "cap-new",
            product_template_id: "p-uht",
            product_template_name: "UHT Milk",
            product_unit_symbol: "l",
            max_quantity: "200",
            reorder_max_quantity: "300",
            reorder_over_capacity: true,
          },
          { status: 201 },
        ),
      ),
    );
    render(<DocumentsLocationsPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: /Shelf A/ }),
    );
    fireEvent.change(await screen.findByLabelText("1. Product"), {
      target: { value: "UHT" },
    });
    await userEvent.click(await screen.findByText("UHT Milk"));
    await userEvent.type(screen.getByLabelText("2. Holds up to"), "200");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(warning).toHaveBeenCalledWith(
        "Capacity saved. Note: replenishment for UHT Milk wants 300 l — more than the shelf holds (200 l).",
      ),
    );
    warning.mockRestore();
  });

  it("keeps what saved when one limit is refused, and a corrected save finishes", async () => {
    const attempts: { product: string; quantity: string }[] = [];
    const accepted = new Set<string>();
    const storageUpdates: unknown[] = [];
    let treeReads = 0;
    serveOverview({
      onStorageUpdate: (body) => storageUpdates.push(body),
    });
    server.use(
      serveLocations(
        () => [{ ...warehouse, children: [shelfA, shelfB, shelfC] }],
        () => {
          treeReads += 1;
        },
      ),
      http.get("/api/v1/warehouse/product-search", () =>
        HttpResponse.json([
          {
            product_template_id: "p-uht",
            name: "UHT Milk",
            sku: "MILK-1",
            uom_symbol: "l",
          },
          {
            product_template_id: "p-choc",
            name: "Chocolate Milk Drink",
            sku: "MILK-2",
            uom_symbol: "pcs",
          },
        ]),
      ),
      http.post("/api/v1/warehouse/putaway/capacity", async ({ request }) => {
        const body = (await request.json()) as {
          product_template_id: string;
          max_quantity: string;
        };
        attempts.push({
          product: body.product_template_id,
          quantity: body.max_quantity,
        });
        // Whole pieces: the API refuses a fraction, as it did when the
        // reviewer typed 0.5 into a product whose unit is pcs.
        if (body.max_quantity === "0.5") {
          return HttpResponse.json(
            { detail: "Quantity must be a whole number." },
            { status: 400 },
          );
        }
        if (accepted.has(body.product_template_id)) {
          return HttpResponse.json(
            { detail: "This product already has a limit here." },
            { status: 400 },
          );
        }
        accepted.add(body.product_template_id);
        return HttpResponse.json(
          {
            ...capacityEntries[0],
            id: `cap-${body.product_template_id}`,
            product_template_id: body.product_template_id,
            max_quantity: body.max_quantity,
          },
          { status: 201 },
        );
      }),
    );
    render(<DocumentsLocationsPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: /Shelf A/ }),
    );
    const sequence = await screen.findByLabelText("Walk order");
    await userEvent.clear(sequence);
    await userEvent.type(sequence, "25");

    fireEvent.change(screen.getByLabelText("1. Product"), {
      target: { value: "UHT" },
    });
    await userEvent.click(await screen.findByText("UHT Milk"));
    await userEvent.type(screen.getByLabelText("2. Holds up to"), "100");
    await userEvent.click(screen.getByRole("button", { name: "Add limit" }));

    fireEvent.change(screen.getByLabelText("1. Product"), {
      target: { value: "Chocolate" },
    });
    await userEvent.click(await screen.findByText("Chocolate Milk Drink"));
    await userEvent.type(screen.getByLabelText("2. Holds up to"), "0.5");
    await userEvent.click(screen.getByRole("button", { name: "Add limit" }));

    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    // The order and the valid limit landed; the refused row stays in the
    // panel as work to correct instead of reading as saved.
    await waitFor(() =>
      expect(attempts.map((attempt) => attempt.product)).toEqual([
        "p-uht",
        "p-choc",
      ]),
    );
    expect(storageUpdates).toEqual([{ sequence: 25 }]);
    await waitFor(() => expect(treeReads).toBeGreaterThan(1));
    expect(
      screen.getByRole("heading", { name: "Location settings" }),
    ).toBeInTheDocument();

    // Correcting the refused quantity finishes the same Save without
    // posting the limit that already landed a second time.
    const quantity = screen.getByLabelText("Limit for Chocolate Milk Drink");
    await userEvent.clear(quantity);
    await userEvent.type(quantity, "1");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(attempts.map((attempt) => attempt.product)).toEqual([
        "p-uht",
        "p-choc",
        "p-choc",
      ]),
    );
    expect(
      attempts.filter((attempt) => attempt.product === "p-uht"),
    ).toHaveLength(1);
    expect(storageUpdates).toEqual([{ sequence: 25 }]);
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Location settings" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("names the missing half of a half-entered limit before it saves", async () => {
    let created: unknown;
    serveOverview({
      onCapacityCreate: (body) => {
        created = body;
      },
    });
    server.use(
      http.get("/api/v1/warehouse/product-search", () =>
        HttpResponse.json([
          {
            product_template_id: "p-uht",
            name: "UHT Milk",
            sku: "MILK-1",
            uom_symbol: "l",
          },
        ]),
      ),
    );
    render(<DocumentsLocationsPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: /Shelf A/ }),
    );
    fireEvent.change(await screen.findByLabelText("1. Product"), {
      target: { value: "UHT" },
    });
    await userEvent.click(await screen.findByText("UHT Milk"));

    // A product with no quantity is not a limit: Save says so instead of
    // closing with the row dropped.
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(
      screen.getByText("Enter how much this location holds."),
    ).toBeInTheDocument();

    // The other half: a quantity with no product.
    await userEvent.click(screen.getByRole("button", { name: "Clear" }));
    await userEvent.type(screen.getByLabelText("2. Holds up to"), "200");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(screen.getByText("Choose a product.")).toBeInTheDocument();
    expect(created).toBeUndefined();
  });

  it("refreshes the tree after a panel save so the table shows the new order", async () => {
    let treeReads = 0;
    serveOverview();
    server.use(
      serveLocations(
        () => [{ ...warehouse, children: [shelfA, shelfB, shelfC] }],
        () => {
          treeReads += 1;
        },
      ),
    );
    render(<DocumentsLocationsPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: /Shelf A/ }),
    );
    await waitFor(() => expect(treeReads).toBe(1));

    const sequence = await screen.findByLabelText("Walk order");
    await userEvent.clear(sequence);
    await userEvent.type(sequence, "40");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(treeReads).toBeGreaterThan(1));
  });

  it("refreshes the tree after bulk numbering", async () => {
    let treeReads = 0;
    serveOverview();
    server.use(
      serveLocations(
        () => [{ ...warehouse, children: [shelfA, shelfB, shelfC] }],
        () => {
          treeReads += 1;
        },
      ),
    );
    render(<DocumentsLocationsPage />);

    await screen.findByText("Shelf A");
    await waitFor(() => expect(treeReads).toBe(1));
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Select Shelf A" }),
    );
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Select Shelf B" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Number walk order in sequence" }),
    );
    const confirmation = await screen.findByRole("alertdialog");
    await userEvent.click(
      within(confirmation).getByRole("button", {
        name: "Number walk order in sequence",
      }),
    );

    await waitFor(() => expect(treeReads).toBeGreaterThan(1));
  });

  it("numbers the walk order only for accounts the storage API accepts", async () => {
    serveOverview();
    // The mix and the limits are documents writes; the walk order is a
    // storage-register write the backend checks separately.
    signInWith(["warehouse:read", "warehouse:write", "locations:read"]);
    render(<DocumentsLocationsPage />);

    await screen.findByText("Shelf A");
    // Selecting rows exists for numbering, so without that right there is
    // nothing to select.
    expect(
      screen.queryByRole("checkbox", { name: "Select Shelf A" }),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Shelf A/ }));
    expect(await screen.findByLabelText("Walk order")).toBeDisabled();
    // The rest of the panel is still this account's to save.
    expect(
      screen.getByRole("button", { name: "Save changes" }),
    ).toBeInTheDocument();
  });

  it("keeps the walk order editable for an account that may write storages", async () => {
    serveOverview();
    signInWith(["warehouse:read", "locations:read", "locations:write"]);
    render(<DocumentsLocationsPage />);

    await screen.findByText("Shelf A");
    await userEvent.click(screen.getByRole("button", { name: /Shelf A/ }));
    expect(await screen.findByLabelText("Walk order")).toBeEnabled();
    // Limits are documents writes this account does not hold.
    expect(
      screen.queryByRole("button", { name: "Add limit" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Save changes" }),
    ).toBeInTheDocument();
  });

  it("shows the rows that saved when another bulk write is refused", async () => {
    let treeReads = 0;
    let shelfBSequence = 20;
    serveOverview();
    server.use(
      serveLocations(
        () => [
          {
            ...warehouse,
            children: [shelfA, { ...shelfB, sequence: shelfBSequence }, shelfC],
          },
        ],
        () => {
          treeReads += 1;
        },
      ),
      http.put("/api/v1/locations/:id", async ({ params, request }) => {
        // The second write of the batch is refused: the first one still
        // landed on the server and belongs on the screen.
        if (params.id === shelfC.id) {
          return HttpResponse.json({ detail: "Not found" }, { status: 404 });
        }
        const body = (await request.json()) as { sequence: number };
        shelfBSequence = body.sequence;
        return HttpResponse.json({ ...shelfB, ...body });
      }),
    );
    render(<DocumentsLocationsPage />);

    await screen.findByText("Shelf B");
    await waitFor(() => expect(treeReads).toBe(1));
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Select Shelf B" }),
    );
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Select Shelf C" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Number walk order in sequence" }),
    );
    const confirmation = await screen.findByRole("alertdialog");
    await userEvent.click(
      within(confirmation).getByRole("button", {
        name: "Number walk order in sequence",
      }),
    );

    await waitFor(() => expect(treeReads).toBeGreaterThan(1));
    const rowB = screen.getByRole("button", { name: /Shelf B/ }).closest("tr")!;
    expect(within(rowB).getByText("10")).toBeInTheDocument();
  });
});

describe("DocumentsLocationsPage — codes and shelf labels", () => {
  it("says how the warehouse makes its codes", async () => {
    serveOverview();
    render(<DocumentsLocationsPage />);

    expect(
      await screen.findByText(
        "Locations below the top level are numbered one level after another: A, A-01, A-01-01. The top-level location keeps its own code.",
      ),
    ).toBeInTheDocument();
  });

  // The generator gives a placeholder with a width digits and one without a
  // letter, whatever the level: the explanation reads the template the same
  // way instead of describing the default one.
  it("explains a template of its own by the codes it gives", async () => {
    serveOverview({
      codes: { ...shelfCodes, template: "{zone:02}-{rack}", stored: true },
    });
    render(<DocumentsLocationsPage />);

    expect(
      await screen.findByText(/one level after another: 01, 01-A\./),
    ).toBeInTheDocument();
  });

  it("renumbers by template only after the reader agrees", async () => {
    const asked: unknown[] = [];
    serveOverview();
    server.use(
      http.post("/api/v1/locations/:id/number", async ({ params, request }) => {
        asked.push({ id: params.id, ...((await request.json()) as object) });
        return HttpResponse.json({ changes: [], codes: shelfCodes });
      }),
    );
    render(<DocumentsLocationsPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "Renumber by template" }),
    );
    const confirmation = await screen.findByRole("alertdialog");
    expect(
      within(confirmation).getByText(
        /Old stickers keep scanning until replaced/,
      ),
    ).toBeInTheDocument();
    expect(asked).toEqual([]);
    await userEvent.click(
      within(confirmation).getByRole("button", {
        name: "Renumber by template",
      }),
    );

    await waitFor(() => expect(asked).toEqual([{ id: "w1", renumber: true }]));
  });

  it("renumbers only the zone chosen, not its warehouse", async () => {
    const asked: unknown[] = [];
    const zone = (id: string, name: string, rack: string) => ({
      ...shelfA,
      id,
      name,
      short_code: `LOC-${id}`,
      children: [{ ...shelfA, id: rack, name: `Rack ${name}`, parent_id: id }],
    });
    serveOverview({
      tree: [
        {
          ...warehouse,
          children: [
            zone("z1", "Zone One", "r1"),
            zone("z2", "Zone Two", "r2"),
          ],
        },
      ],
    });
    server.use(
      http.post("/api/v1/locations/:id/number", async ({ params, request }) => {
        asked.push({ id: params.id, ...((await request.json()) as object) });
        return HttpResponse.json({ changes: [], codes: shelfCodes });
      }),
    );
    render(<DocumentsLocationsPage />);

    const picker = await screen.findByRole("combobox", { name: /Location/ });
    await userEvent.click(picker);
    // The table row carries the name too: choose it inside the picker's panel.
    const panel = document.getElementById(
      picker.getAttribute("aria-controls")!,
    )!;
    await userEvent.click(await within(panel).findByText("Zone One"));
    await userEvent.click(
      await screen.findByRole("button", { name: "Renumber by template" }),
    );
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Renumber by template",
      }),
    );

    // The codes card belongs to the warehouse; the renumbering, to the zone
    // the reader picked — Zone Two's stickers stay as they are.
    await waitFor(() => expect(asked).toEqual([{ id: "z1", renumber: true }]));
  });

  it("lists the stickers to replace, prints them and marks them replaced", async () => {
    const replaced: unknown[] = [];
    const previewed: unknown[] = [];
    serveOverview({
      codes: {
        ...shelfCodes,
        reprint: [
          {
            id: "shelf-a",
            name: "Shelf A",
            path: "Main Warehouse → Shelf A",
            short_code: "A-01",
            old_code: "LOC-7KQ2",
          },
        ],
      },
    });
    server.use(
      http.post("/api/v1/locations/reprinted", async ({ request }) => {
        replaced.push(await request.json());
        return new HttpResponse(null, { status: 204 });
      }),
      http.post("/api/v1/printing/location-labels/png", async ({ request }) => {
        previewed.push(await request.json());
        return new HttpResponse(new Uint8Array([0x89, 0x50]), {
          headers: { "Content-Type": "image/png" },
        });
      }),
      http.get("/api/v1/printing/agents", () => HttpResponse.json([])),
    );
    render(<DocumentsLocationsPage />);

    expect(await screen.findByText("1 sticker to replace")).toBeInTheDocument();
    expect(screen.getByText("LOC-7KQ2 → A-01")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Print new labels" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Location labels" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(previewed[0]).toMatchObject({
        location_ids: ["shelf-a"],
        qr: false,
      }),
    );
    const sheet = screen.getByRole("dialog", { name: "Location labels" });
    await userEvent.click(
      within(sheet).getAllByRole("button", { name: "Close" })[0],
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Mark as replaced" }),
    );
    await waitFor(() =>
      expect(replaced).toEqual([{ location_ids: ["shelf-a"] }]),
    );
  });

  it("prints the selected shelves' labels from the selection bar", async () => {
    const previewed: unknown[] = [];
    serveOverview();
    server.use(
      http.post("/api/v1/printing/location-labels/png", async ({ request }) => {
        previewed.push(await request.json());
        return new HttpResponse(new Uint8Array([0x89, 0x50]), {
          headers: { "Content-Type": "image/png" },
        });
      }),
      http.get("/api/v1/printing/agents", () => HttpResponse.json([])),
    );
    render(<DocumentsLocationsPage />);

    await userEvent.click(
      await screen.findByRole("checkbox", { name: "Select Shelf B" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Print labels" }));
    await userEvent.click(
      await screen.findByRole("checkbox", {
        name: "QR beside the bars, for a phone camera",
      }),
    );

    await waitFor(() =>
      expect(previewed.at(-1)).toMatchObject({
        location_ids: ["shelf-b"],
        qr: true,
      }),
    );
  });

  it("prints the labels of the whole list without selecting a row first", async () => {
    const previewed: unknown[] = [];
    serveOverview();
    server.use(
      http.post("/api/v1/printing/location-labels/png", async ({ request }) => {
        previewed.push(await request.json());
        return new HttpResponse(new Uint8Array([0x89, 0x50]), {
          headers: { "Content-Type": "image/png" },
        });
      }),
      http.get("/api/v1/printing/agents", () => HttpResponse.json([])),
    );
    render(<DocumentsLocationsPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "Print labels for this list" }),
    );

    await waitFor(() => expect(previewed.length).toBeGreaterThan(0));
    const ids = (previewed.at(-1) as { location_ids: string[] }).location_ids;
    expect(ids).toEqual(expect.arrayContaining(["shelf-a", "shelf-b"]));
  });

  it("gives the selected branches their shelf codes, parents first", async () => {
    const numbered: unknown[] = [];
    const rack = { ...shelfA, id: "rack", name: "Rack 1", short_code: null };
    const level = {
      ...shelfA,
      id: "level",
      name: "Level 1",
      parent_id: "rack",
      short_code: null,
    };
    serveOverview({
      tree: [{ ...warehouse, children: [{ ...rack, children: [level] }] }],
    });
    server.use(
      http.post("/api/v1/locations/:id/number", async ({ params, request }) => {
        numbered.push({ id: params.id, ...((await request.json()) as object) });
        return HttpResponse.json({
          changes: [
            { id: params.id, name: "x", old_code: null, new_code: "A" },
          ],
          codes: shelfCodes,
        });
      }),
    );
    render(<DocumentsLocationsPage />);

    await userEvent.click(
      await screen.findByRole("checkbox", { name: "Select Level 1" }),
    );
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Select Rack 1" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Give template codes" }),
    );

    await waitFor(() =>
      expect(numbered).toEqual([
        { id: "rack", renumber: false },
        { id: "level", renumber: false },
      ]),
    );
  });

  it("says under the field why a template was refused, and saves a good one", async () => {
    const sent: unknown[] = [];
    serveOverview();
    server.use(
      http.put("/api/v1/locations/:id/code-template", async ({ request }) => {
        const body = (await request.json()) as { template: string | null };
        sent.push(body);
        if (body.template === "{zone}{rack:02}") {
          return HttpResponse.json(
            {
              detail: {
                code: "VALIDATION_ERROR",
                message: "The code template '{zone}{rack:02}' cannot be used.",
              },
            },
            { status: 400 },
          );
        }
        return HttpResponse.json({ ...shelfCodes, stored: true });
      }),
    );
    render(<DocumentsLocationsPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "Code template" }),
    );
    const field = await screen.findByRole("textbox", { name: "Template" });
    fireEvent.change(field, { target: { value: "{zone}{rack:02}" } });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText(
        "The code template '{zone}{rack:02}' cannot be used.",
      ),
    ).toBeInTheDocument();

    fireEvent.change(field, { target: { value: "W2/{aisle:03}" } });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("textbox", { name: "Template" }),
      ).not.toBeInTheDocument(),
    );
    expect(sent).toEqual([
      { template: "{zone}{rack:02}" },
      { template: "W2/{aisle:03}" },
    ]);
  });

  it("offers no code writes to an account that may not write locations", async () => {
    signInWith(["warehouse:read", "warehouse:write"]);
    serveOverview();
    render(<DocumentsLocationsPage />);

    await screen.findByText(/numbered one level after another/);
    expect(
      screen.queryByRole("button", { name: "Renumber by template" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Code template" }),
    ).not.toBeInTheDocument();
  });
});
