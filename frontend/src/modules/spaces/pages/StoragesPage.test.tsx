import {
  render,
  screen,
  waitFor,
  fireEvent,
  within,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import StoragesPage from "./StoragesPage";
import { useAuthStore } from "@/store/authStore";
import { server } from "@/test/mocks/server";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { onePage } from "@/test/mocks/page";
import type { ReactNode } from "react";
import { serveLocations } from "@/test/serveLocations";

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
    loading: vi.fn(),
    dismiss: vi.fn(),
  },
}));

const createQueryClient = () =>
  new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });

const storageType = (id: string, name: string, code: string) => ({
  id,
  name,
  type_code: code,
  behavior_mode: "NONE",
  is_system: false,
  context_schema: [],
});

const summaries = [
  {
    id: "site",
    name: "Pantry Building",
    parent_id: null,
    short_code: "PB",
    usage: "internal",
    location_type: storageType("t1", "Building", "BUILDING"),
    items_count: 0,
    subtree_items_count: 5,
    direct_children_count: 1,
    total_subtree_items_count: 5,
    is_leaf: false,
    full_path: "Pantry Building",
  },
  {
    id: "zone",
    name: "Dry Goods",
    parent_id: "site",
    short_code: "DG",
    usage: "internal",
    location_type: storageType("t2", "Zone", "ZONE"),
    items_count: 1,
    subtree_items_count: 5,
    direct_children_count: 1,
    total_subtree_items_count: 5,
    is_leaf: false,
    full_path: "Pantry Building › Dry Goods",
  },
  {
    id: "leaf",
    name: "Shelf A",
    parent_id: "zone",
    short_code: "SA",
    usage: "internal",
    location_type: storageType("t3", "Shelf", "SHELF"),
    items_count: 4,
    subtree_items_count: 4,
    direct_children_count: 0,
    total_subtree_items_count: 4,
    is_leaf: true,
    full_path: "Pantry Building › Dry Goods › Shelf A",
  },
  {
    id: "freezer",
    name: "Freezer",
    parent_id: null,
    short_code: "FZ",
    usage: "internal",
    location_type: storageType("t4", "Fridge", "FRIDGE"),
    items_count: 0,
    subtree_items_count: 0,
    direct_children_count: 0,
    total_subtree_items_count: 0,
    is_leaf: true,
    full_path: "Freezer",
  },
];

const detailFor = (id: string) => {
  const summary = summaries.find((entry) => entry.id === id)!;
  return {
    ...summary,
    organization_id: "org",
    description: "",
    location_details: "",
    created_at: "2026-10-01T00:00:00Z",
    settings: {},
    context_schema: ["expiry_date"],
    field_definitions: [],
    behavior_mode: "STOCK",
    sequence: id === "zone" ? 20 : null,
  };
};

const item = (id: string, name: string, locationId: string) => ({
  id,
  name,
  quantity: "2",
  location_id: locationId,
  added_date: "2026-10-01",
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
  is_deleted: false,
});

/** What the storages screen asks of the two location endpoints, per request. */
let locationRequests: URLSearchParams[] = [];

/** The places leading to `id`, root first, as the breadcrumb endpoint answers. */
const breadcrumbFor = (id: string) => {
  const chain: Array<{ id: string; name: string }> = [];
  let current = summaries.find((entry) => entry.id === id);
  while (current) {
    chain.unshift({ id: current.id, name: current.name });
    current = summaries.find((entry) => entry.id === current?.parent_id);
  }
  return chain;
};

describe("StoragesPage — one screen", () => {
  let queryClient: QueryClient;
  const setHeader = vi.fn();

  beforeEach(() => {
    queryClient = createQueryClient();
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/locations/:id/breadcrumb", ({ params }) =>
        HttpResponse.json(breadcrumbFor(String(params.id))),
      ),
      http.get("/api/v1/locations/:id/items", ({ params, request }) => {
        // One ask for the place and everything below it.
        if (
          params.id === "zone" &&
          new URL(request.url).searchParams.get("include_inside") === "true"
        )
          return HttpResponse.json(
            onePage([
              item("item-0", "Bulk rice", "zone"),
              item("item-1", "Flour", "leaf"),
            ]),
          );
        if (params.id === "leaf")
          return HttpResponse.json(
            onePage([
              item("item-1", "Flour", "leaf"),
              item("item-2", "Sugar", "leaf"),
            ]),
          );
        if (params.id === "zone")
          return HttpResponse.json(
            onePage([item("item-0", "Bulk rice", "zone")]),
          );
        return HttpResponse.json(onePage([]));
      }),
      http.get("/api/v1/locations/:id", ({ params }) =>
        HttpResponse.json(detailFor(String(params.id))),
      ),
      http.get("/api/v1/location-types", () =>
        HttpResponse.json(
          onePage([
            storageType("t1", "Building", "BUILDING"),
            storageType("t2", "Zone", "ZONE"),
            storageType("t3", "Shelf", "SHELF"),
          ]),
        ),
      ),
      http.get("/api/v1/categories", () => HttpResponse.json(onePage([]))),
      http.get("/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "org", name: "Test", settings: {} }),
      ),
      http.get("/api/v1/modules/my", () => HttpResponse.json([])),
      http.get("/api/v1/printing/agents", () => HttpResponse.json([])),
    );
    // After the rest, so the list and the tree win over `/locations/:id`.
    locationRequests = serveLocations(summaries);

    useAuthStore.setState({
      user: {
        is_blocked: false,
        is_superuser: false,
        is_active: true,
        id: "1",
        full_name: "Test User",
        email: "test@example.com",
        preferred_language: "en",
        role: "user",
        permissions: [
          "locations:read",
          "locations:write",
          "items:read",
          "items:write",
        ],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
    });
  });

  const renderPage = (entry: string) => {
    render(
      <QueryClientProvider client={queryClient}>
        <ModulesProvider>
          <PageHeaderContext.Provider value={{ data: {}, setHeader }}>
            <MemoryRouter initialEntries={[entry]}>
              <Routes>
                <Route path="/settings" element={<h1>Settings page</h1>} />
                <Route path="/inventory/locations" element={<StoragesPage />} />
                <Route
                  path="/inventory/locations/zone/:zoneId"
                  element={<StoragesPage />}
                />
                <Route
                  path="/inventory/locations/:id"
                  element={<StoragesPage />}
                />
              </Routes>
            </MemoryRouter>
          </PageHeaderContext.Provider>
        </ModulesProvider>
      </QueryClientProvider>,
    );
  };

  /**
   * The reorg endpoint: a dry run reads what each move carries and is not a
   * move, so only the real call is recorded. These locations hold no stock,
   * so the dry run answers with no scopes and nothing asks.
   */
  const mockReorg = (calls: unknown[]) =>
    http.post("/api/v1/locations/reorg", async ({ request }) => {
      const body = (await request.json()) as { dry_run?: boolean };
      if (!body.dry_run) calls.push(body);
      return HttpResponse.json({
        applied: true,
        created: {},
        rejections: [],
        moves: [],
      });
    });

  it("shows the tree beside the selected location and its clickable path", async () => {
    // The branches are read after the tree is drawn; a loaded machine makes
    // that gap long. Held here so the test meets it on every run, and has to
    // wait for the child rather than read it the moment the tree appears.
    server.use(
      http.get("/api/v1/locations", async ({ request }) => {
        if (new URL(request.url).searchParams.has("parent_id"))
          await new Promise((resolve) => setTimeout(resolve, 300));
      }),
    );
    renderPage("/inventory/locations/zone");

    const treeView = await screen.findByRole("tree", {
      name: "Locations",
    });
    expect(
      within(treeView).getByRole("treeitem", { name: /Pantry Building/ }),
    ).toBeInTheDocument();
    expect(
      await within(treeView).findByRole("treeitem", { name: /Shelf A/ }),
    ).toBeInTheDocument();

    const path = screen.getByRole("navigation", { name: "Location path" });
    expect(
      within(path).getByRole("button", { name: "Pantry Building" }),
    ).toBeInTheDocument();
    expect(within(path).getByText("Dry Goods")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Dry Goods" }),
    ).toBeInTheDocument();
  });

  it("never reads the location catalogue to draw the screen", async () => {
    renderPage("/inventory/locations/zone");
    await screen.findByRole("heading", { name: "Dry Goods" });
    await screen.findByRole("treeitem", { name: /Shelf A/ });

    // Every read names what it needs: a level of the tree, one place, the
    // children of one place, or a count — never the list or the tree whole.
    const wholeReads = locationRequests.filter(
      (r) =>
        !r.has("depth") &&
        !r.has("parent_id") &&
        !r.has("ids") &&
        !r.has("top_level") &&
        !r.has("q") &&
        Number(r.get("limit") ?? 50) > 2,
    );
    expect(wholeReads.map((r) => r.toString())).toEqual([]);
  });

  it("opens a location from the tree", async () => {
    renderPage("/inventory/locations/zone");

    const treeView = await screen.findByRole("tree", {
      name: "Locations",
    });
    await userEvent.click(
      within(treeView).getByRole("treeitem", { name: /Freezer/ }),
    );

    expect(
      await screen.findByRole("heading", { name: "Freezer" }),
    ).toBeInTheDocument();
  });

  it("keeps the tree on screen while the chosen location loads", async () => {
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.get("/api/v1/locations", async ({ request }) => {
        const ids = new URL(request.url).searchParams.getAll("ids");
        if (ids.includes("freezer")) await held;
      }),
    );
    renderPage("/inventory/locations/zone");

    const treeView = await screen.findByRole("tree", { name: "Locations" });
    await userEvent.click(
      within(treeView).getByRole("treeitem", { name: /Freezer/ }),
    );

    // Only the pane waits for the place; the tree it was chosen from, and
    // the branches open in it, stay.
    expect(screen.getByRole("tree", { name: "Locations" })).toBe(treeView);
    release();
    expect(
      await screen.findByRole("heading", { name: "Freezer" }),
    ).toBeInTheDocument();
  });

  it("goes up through a segment of the full path", async () => {
    renderPage("/inventory/locations/leaf");

    const path = await screen.findByRole("navigation", {
      name: "Location path",
    });
    await userEvent.click(
      within(path).getByRole("button", { name: "Pantry Building" }),
    );

    expect(
      await screen.findByRole("heading", { name: "Pantry Building" }),
    ).toBeInTheDocument();
  });

  it("offers the same actions on a location that holds others", async () => {
    renderPage("/inventory/locations/zone");

    expect(
      await screen.findByRole("button", { name: "Add location inside" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /add product here/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Download label" }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: "Move to…" }).length,
    ).toBeGreaterThan(0);
  });

  it("edits the settings of an inner level on the page with one Save", async () => {
    const updates: Array<Record<string, unknown>> = [];
    server.use(
      http.put("/api/v1/locations/:id", async ({ request, params }) => {
        updates.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(detailFor(String(params.id)));
      }),
    );
    renderPage("/inventory/locations/zone");

    await userEvent.click(await screen.findByRole("tab", { name: "Settings" }));

    expect(await screen.findByText("Product fields here")).toBeInTheDocument();
    // A location with children edits its own product fields too.
    expect(screen.getByText("Tracked fields")).toBeInTheDocument();
    expect(screen.getByText("Custom fields")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    const name = screen.getByLabelText("Name");
    await userEvent.clear(name);
    await userEvent.type(name, "Dry Goods renamed");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(updates).toHaveLength(1));
    expect(updates[0]).toMatchObject({
      name: "Dry Goods renamed",
      context_schema: ["expiry_date"],
    });
  });

  it("moves a location through the picker, which excludes itself and its children", async () => {
    const reorgs: unknown[] = [];
    server.use(mockReorg(reorgs));
    renderPage("/inventory/locations/zone");

    const moveButtons = await screen.findAllByRole("button", {
      name: "Move to…",
    });
    await userEvent.click(moveButtons[0]);

    const dialog = await screen.findByRole("dialog");
    const picker = within(dialog).getByRole("tree", {
      name: "Destination locations",
    });
    expect(
      within(picker).queryByRole("treeitem", { name: /Dry Goods/ }),
    ).toBeNull();
    expect(
      within(picker).queryByRole("treeitem", { name: /Shelf A/ }),
    ).toBeNull();
    await userEvent.click(
      within(picker).getByRole("treeitem", { name: /Freezer/ }),
    );

    await waitFor(() => expect(reorgs).toHaveLength(1));
    expect(reorgs[0]).toEqual({
      operations: [{ op: "move", id: "zone", parent_id: "freezer" }],
    });
    expect(toast.success).toHaveBeenCalledWith(
      "Location moved",
      expect.objectContaining({
        action: expect.objectContaining({ label: "Undo" }),
      }),
    );

    const options = vi.mocked(toast.success).mock.calls[0][1] as unknown as {
      action: { onClick: () => void };
    };
    options.action.onClick();
    await waitFor(() => expect(reorgs).toHaveLength(2));
    expect(reorgs[1]).toEqual({
      operations: [{ op: "move", id: "zone", parent_id: "site" }],
    });
  });

  it("moves to the destination a label or a short code scanned into the picker names", async () => {
    const reorgs: unknown[] = [];
    server.use(
      http.get("/api/v1/labels/scan/:code", () =>
        HttpResponse.json({
          status: "storage_context",
          label_code: "FZ-999",
          action: "set_storage_context",
          location: { id: "freezer", name: "Freezer", icon: "BOX" },
        }),
      ),
      mockReorg(reorgs),
    );
    renderPage("/inventory/locations/zone");

    const moveButtons = await screen.findAllByRole("button", {
      name: "Move to…",
    });
    await userEvent.click(moveButtons[0]);

    const dialog = await screen.findByRole("dialog");
    await userEvent.type(
      within(dialog).getByLabelText("Scan a location label…"),
      "FZ-999{enter}",
    );

    await waitFor(() => expect(reorgs).toHaveLength(1));
    expect(reorgs[0]).toEqual({
      operations: [{ op: "move", id: "zone", parent_id: "freezer" }],
    });
  });

  it("refuses a scanned label of the location being moved or one inside it", async () => {
    const reorgs: unknown[] = [];
    server.use(
      http.get("/api/v1/labels/scan/:code", () =>
        HttpResponse.json({
          status: "storage_context",
          label_code: "DG-999",
          action: "set_storage_context",
          location: { id: "zone", name: "Dry Goods", icon: "BOX" },
        }),
      ),
      mockReorg(reorgs),
    );
    renderPage("/inventory/locations/zone");

    const moveButtons = await screen.findAllByRole("button", {
      name: "Move to…",
    });
    await userEvent.click(moveButtons[0]);

    const dialog = await screen.findByRole("dialog");
    const scan = within(dialog).getByLabelText("Scan a location label…");
    await userEvent.type(scan, "DG-999{enter}");

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringContaining("cannot be the destination"),
      ),
    );
    expect(reorgs).toHaveLength(0);
    // The field keeps what was scanned, so the next label is one keystroke away.
    expect(scan).toHaveValue("DG-999");
  });

  it("moves several selected children from the Contents table", async () => {
    const reorgs: unknown[] = [];
    server.use(mockReorg(reorgs));
    renderPage("/inventory/locations/zone");

    const table = await screen.findByRole("table");
    await userEvent.click(
      within(table).getByRole("checkbox", { name: "Select Shelf A" }),
    );
    expect(screen.getByText("1 location selected")).toBeInTheDocument();
    const moveButtons = screen.getAllByRole("button", { name: "Move to…" });
    await userEvent.click(moveButtons[moveButtons.length - 1]);
    const dialog = await screen.findByRole("dialog");
    const picker = within(dialog).getByRole("tree", {
      name: "Destination locations",
    });
    await userEvent.click(
      within(picker).getByRole("treeitem", { name: /Freezer/ }),
    );

    await waitFor(() => expect(reorgs).toHaveLength(1));
    expect(reorgs[0]).toEqual({
      operations: [{ op: "move", id: "leaf", parent_id: "freezer" }],
    });
  });

  it("forgets a selected child once it has moved out of Contents", async () => {
    const shelfB = {
      ...summaries.find((entry) => entry.id === "leaf")!,
      id: "leaf-b",
      name: "Shelf B",
      short_code: "SB",
      full_path: "Pantry Building › Dry Goods › Shelf B",
    };
    const floor = (shelves: Array<{ id: string; parent_id: string }>) => [
      ...summaries.filter((entry) => entry.id !== "leaf"),
      ...shelves.map((shelf) => ({
        ...(shelf.id === "leaf-b"
          ? shelfB
          : summaries.find((entry) => entry.id === "leaf")!),
        parent_id: shelf.parent_id,
      })),
    ];
    locationRequests = serveLocations(
      floor([
        { id: "leaf", parent_id: "zone" },
        { id: "leaf-b", parent_id: "zone" },
      ]),
    );
    const reorgs: unknown[] = [];
    server.use(
      http.post("/api/v1/locations/reorg", async ({ request }) => {
        const body = (await request.json()) as { dry_run?: boolean };
        if (!body.dry_run) {
          reorgs.push(body);
          serveLocations(
            floor([
              { id: "leaf", parent_id: "freezer" },
              { id: "leaf-b", parent_id: "zone" },
            ]),
          );
        }
        return HttpResponse.json({
          applied: true,
          created: {},
          rejections: [],
          moves: [],
        });
      }),
    );
    renderPage("/inventory/locations/zone");

    const pickFreezer = async () => {
      const moveButtons = screen.getAllByRole("button", { name: "Move to…" });
      await userEvent.click(moveButtons[moveButtons.length - 1]);
      const dialog = await screen.findByRole("dialog");
      await userEvent.click(
        await within(
          within(dialog).getByRole("tree", { name: "Destination locations" }),
        ).findByRole("treeitem", { name: /Freezer/ }),
      );
    };

    await userEvent.click(
      within(await screen.findByRole("table")).getByRole("checkbox", {
        name: "Select Shelf A",
      }),
    );
    await pickFreezer();
    await waitFor(() => expect(reorgs).toHaveLength(1));
    await waitFor(() =>
      expect(
        within(screen.getByRole("table")).queryByText("Shelf A"),
      ).not.toBeInTheDocument(),
    );
    // Shelf A left with the move, so nothing is selected any more.
    expect(screen.queryByText(/locations? selected/)).not.toBeInTheDocument();

    await userEvent.click(
      within(screen.getByRole("table")).getByRole("checkbox", {
        name: "Select Shelf B",
      }),
    );
    expect(screen.getByText("1 location selected")).toBeInTheDocument();
    await pickFreezer();
    await waitFor(() => expect(reorgs).toHaveLength(2));
    expect(reorgs[1]).toEqual({
      operations: [{ op: "move", id: "leaf-b", parent_id: "freezer" }],
    });
  });

  it("keeps the old name when a rename is cancelled", async () => {
    const updates: unknown[] = [];
    server.use(
      http.put("/api/v1/locations/:id", async ({ request, params }) => {
        updates.push(await request.json());
        return HttpResponse.json(detailFor(String(params.id)));
      }),
    );
    renderPage("/inventory/locations/zone");

    await userEvent.click(
      await screen.findByRole("button", { name: "Rename" }),
    );
    const input = screen.getByLabelText("Location name");
    await userEvent.clear(input);
    await userEvent.type(input, "Cancelled name");
    await userEvent.click(
      screen.getByRole("button", { name: "Cancel rename" }),
    );

    expect(
      screen.getByRole("heading", { name: "Dry Goods" }),
    ).toBeInTheDocument();
    expect(updates).toHaveLength(0);
  });

  it("moves a location by dragging it onto another row", async () => {
    const reorgs: unknown[] = [];
    server.use(mockReorg(reorgs));
    renderPage("/inventory/locations/leaf");

    const treeView = await screen.findByRole("tree", {
      name: "Locations",
    });
    const shelf = await within(treeView).findByRole("treeitem", {
      name: /Shelf A/,
    });
    const freezer = within(treeView).getByRole("treeitem", { name: /Freezer/ });
    const dataTransfer = {
      setData: vi.fn(),
      getData: vi.fn(),
      effectAllowed: "",
      dropEffect: "",
    };
    fireEvent.dragStart(shelf, { dataTransfer });
    fireEvent.dragOver(freezer, { dataTransfer });
    fireEvent.drop(freezer, { dataTransfer });

    await waitFor(() => expect(reorgs).toHaveLength(1));
    expect(reorgs[0]).toEqual({
      operations: [{ op: "move", id: "leaf", parent_id: "freezer" }],
    });
  });

  it("asks whether a moved location that holds stock physically moved", async () => {
    const posts: Array<{ dry_run?: boolean }> = [];
    server.use(
      http.post("/api/v1/locations/reorg", async ({ request }) => {
        const body = (await request.json()) as { dry_run?: boolean };
        posts.push(body);
        if (body.dry_run) {
          return HttpResponse.json({
            applied: false,
            created: {},
            rejections: [],
            moves: [
              {
                index: 0,
                id: "leaf",
                name: "Shelf A",
                locations_inside: 0,
                products: 4,
                from_path: "Pantry Building / Dry Goods",
                to_path: "Freezer",
                warehouse_changes: true,
              },
            ],
          });
        }
        return HttpResponse.json({
          applied: true,
          created: {},
          rejections: [],
        });
      }),
    );
    renderPage("/inventory/locations/leaf");

    const treeView = await screen.findByRole("tree", {
      name: "Locations",
    });
    const shelf = await within(treeView).findByRole("treeitem", {
      name: /Shelf A/,
    });
    const freezer = within(treeView).getByRole("treeitem", { name: /Freezer/ });
    const dataTransfer = {
      setData: vi.fn(),
      getData: vi.fn(),
      effectAllowed: "",
      dropEffect: "",
    };
    fireEvent.dragStart(shelf, { dataTransfer });
    fireEvent.dragOver(freezer, { dataTransfer });
    fireEvent.drop(freezer, { dataTransfer });

    const question = await screen.findByText("Did it physically move?");
    expect(question).toBeInTheDocument();
    // Backing out of the question moves nothing.
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByText("Did it physically move?")).toBeNull(),
    );
    expect(posts.filter((body) => !body.dry_run)).toHaveLength(0);
  });

  it("opens the node an old zone URL names", async () => {
    renderPage("/inventory/locations/zone/leaf");

    expect(
      await screen.findByRole("heading", { name: "Shelf A" }),
    ).toBeInTheDocument();
  });

  it("backs a phone out to the parent by name and shows the whole path", async () => {
    renderPage("/inventory/locations/leaf");

    expect(
      await screen.findByRole("heading", { name: "Shelf A" }),
    ).toBeInTheDocument();
    const backButtons = screen.getAllByRole("button", { name: "Dry Goods" });
    expect(backButtons.length).toBeGreaterThan(0);
    const path = screen.getByRole("navigation", { name: "Location path" });
    expect(
      within(path).getByRole("button", { name: "Pantry Building" }),
    ).toBeInTheDocument();
    expect(within(path).getByText("Shelf A")).toBeInTheDocument();
  });

  it("says a leaf has nothing inside and points at its products", async () => {
    renderPage("/inventory/locations/leaf");

    expect(
      await screen.findByText("Nothing inside this location"),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Show products" }),
    );
    expect((await screen.findAllByText("Flour")).length).toBeGreaterThan(0);
  });

  it("includes the products of locations inside when asked", async () => {
    renderPage("/inventory/locations/zone");

    await userEvent.click(await screen.findByRole("tab", { name: "Products" }));
    expect((await screen.findAllByText("Bulk rice")).length).toBeGreaterThan(0);
    expect(screen.queryByText("Flour")).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("checkbox", { name: "Include locations inside" }),
    );
    expect((await screen.findAllByText("Flour")).length).toBeGreaterThan(0);
  });

  it("searches the locations on the server by name or code", async () => {
    renderPage("/inventory/locations/zone");

    const search = await screen.findByLabelText("Search by name or code");
    await userEvent.type(search, "Shelf A");

    const results = await screen.findByRole("list", { name: "Locations" });
    const hit = within(results).getByRole("button", { name: /Shelf A/ });
    expect(hit).toHaveTextContent("Pantry Building › Dry Goods › Shelf A");
    expect(
      within(results).queryByRole("button", { name: /Freezer/ }),
    ).toBeNull();
    expect(locationRequests.some((r) => r.get("q") === "Shelf A")).toBe(true);
  });

  it("selects the location a scanned label names", async () => {
    server.use(
      http.get("/api/v1/labels/scan/:code", () =>
        HttpResponse.json({
          status: "storage_context",
          label_code: "FZ",
          action: "set_storage_context",
          location: { id: "freezer", name: "Freezer", icon: "BOX" },
        }),
      ),
    );
    renderPage("/inventory/locations/zone");

    const scan = await screen.findByLabelText("Scan a location label…");
    await userEvent.type(scan, "FZ-999{enter}");

    expect(
      await screen.findByRole("heading", { name: "Freezer" }),
    ).toBeInTheDocument();
  });

  /** The page header's action, rendered the way the shell would. */
  const headerActions = (): ReactNode => {
    const calls = setHeader.mock.calls;
    const last = calls[calls.length - 1]?.[0] as
      { actions?: ReactNode } | undefined;
    return last?.actions;
  };

  it("opens the wizard from the header's Add location button and closes it when nothing was typed", async () => {
    renderPage("/inventory/locations/zone");
    await screen.findByRole("heading", { name: "Dry Goods" });
    await waitFor(() => expect(headerActions()).toBeTruthy());

    render(<>{headerActions()}</>);
    await userEvent.click(screen.getByRole("button", { name: "Add location" }));

    const wizard = await screen.findByRole("dialog", {
      name: "Location Wizard",
    });
    await userEvent.click(
      within(wizard).getByRole("button", { name: "Close" }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Location Wizard" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("opens the wizard on the location that is open when 'Add location inside' is pressed", async () => {
    renderPage("/inventory/locations/zone");

    await userEvent.click(
      await screen.findByRole("button", { name: "Add location inside" }),
    );

    const wizard = await screen.findByRole("dialog", {
      name: "Location Wizard",
    });
    // The second step is the one that names the place inside the parent.
    expect(
      await within(wizard).findByText(/What is inside this location\?/),
    ).toBeInTheDocument();
    await userEvent.click(
      within(wizard).getByRole("button", { name: "Close" }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Location Wizard" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("offers to add the first location when there are none, and opens the wizard from it", async () => {
    serveLocations([]);
    renderPage("/inventory/locations");

    await userEvent.click(
      await screen.findByRole("button", { name: "Add first location" }),
    );

    const wizard = await screen.findByRole("dialog", {
      name: "Location Wizard",
    });
    await userEvent.click(
      within(wizard).getByRole("button", { name: "Close" }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Location Wizard" }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: "Add first location" }),
    ).toBeInTheDocument();
  });

  it("points at the settings, not at an empty list, when module-owned locations are the only ones", async () => {
    serveLocations([
      { id: "rack", name: "Server rack", context_tag: "equipment" },
    ]);
    server.use(http.get("/api/v1/locations/tree", () => HttpResponse.json([])));
    renderPage("/inventory/locations");

    expect(
      await screen.findByText("Some locations are hidden"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Add first location" }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Open settings" }),
    );

    expect(
      await screen.findByRole("heading", { name: "Settings page" }),
    ).toBeInTheDocument();
  });

  it("retries the tree and the selected location together after the tree failed to load", async () => {
    let failing = true;
    server.use(
      http.get("/api/v1/locations/tree", () =>
        failing
          ? HttpResponse.json({ detail: "down" }, { status: 500 })
          : undefined,
      ),
    );
    renderPage("/inventory/locations/zone");

    const retry = await screen.findByRole("button", { name: "Try again" });
    failing = false;
    await userEvent.click(retry);

    expect(
      await screen.findByRole("heading", { name: "Dry Goods" }),
    ).toBeInTheDocument();
  });

  it.each([
    [
      "a module-owned",
      { context_tag: "equipment" },
      "This location belongs to a module",
    ],
    [
      "an archived",
      { settings: { archived: true } },
      "This location is archived",
    ],
    ["a system", { usage: "transit" }, "This is a system location"],
  ])(
    "says why %s location is not on the tree instead of calling it missing, and goes back to the list",
    async (_label, extra, title) => {
      serveLocations([
        ...summaries,
        { id: "withheld", name: "Hidden spot", ...extra },
      ]);
      renderPage("/inventory/locations/withheld");

      expect(await screen.findByText(title)).toBeInTheDocument();
      expect(screen.queryByText("Location not found")).not.toBeInTheDocument();

      await userEvent.click(
        screen.getByRole("button", { name: "Back to list" }),
      );

      expect(await screen.findByText("Choose a location")).toBeInTheDocument();
      expect(screen.queryByText(title)).not.toBeInTheDocument();
    },
  );

  it("says an unknown location is not found, and goes back to the list from there", async () => {
    server.use(
      http.get("/api/v1/locations/:id", ({ params }) =>
        params.id === "ghost"
          ? HttpResponse.json({ detail: "Not found" }, { status: 404 })
          : undefined,
      ),
    );
    renderPage("/inventory/locations/ghost");

    expect(await screen.findByText("Location not found")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Back to list" }));

    expect(await screen.findByText("Choose a location")).toBeInTheDocument();
    expect(screen.queryByText("Location not found")).not.toBeInTheDocument();
  });

  it("gives an address that is not an identifier the same page as an unknown location", async () => {
    // The server refuses a cut link with a validation error, not a 404; a
    // retry could only be refused again, so it is "not found", not a failure.
    server.use(
      http.get("/api/v1/locations", ({ request }) =>
        new URL(request.url).searchParams.getAll("ids").includes("zone-12")
          ? HttpResponse.json(
              {
                detail: [
                  {
                    type: "uuid_parsing",
                    loc: ["query", "ids", 0],
                    msg: "Input should be a valid UUID",
                  },
                ],
              },
              { status: 422 },
            )
          : undefined,
      ),
    );
    renderPage("/inventory/locations/zone/zone-12");

    expect(await screen.findByText("Location not found")).toBeInTheDocument();
    expect(screen.queryByText(/try again/i)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Back to list" }),
    ).toBeInTheDocument();
  });

  it("reaches the archived locations from the phone's first level too, not only from the tree beside it", async () => {
    renderPage("/inventory/locations");

    await screen.findByRole("button", { name: /^Freezer/ });
    // One link in the tree's aside (desktop), one under the phone's list of
    // roots; the aside is not drawn on a phone.
    const links = screen.getAllByRole("link", { name: "Archived locations" });
    expect(links).toHaveLength(2);
    expect(
      links.every(
        (l) => l.getAttribute("href") === "/inventory/locations/archived",
      ),
    ).toBe(true);
  });

  it("opens a root from the phone's first level, which lists the roots themselves", async () => {
    renderPage("/inventory/locations");

    // The tree's own rows are tree items; this list is plain buttons.
    await userEvent.click(
      await screen.findByRole("button", { name: /^Freezer/ }),
    );

    expect(
      await screen.findByRole("heading", { name: "Freezer" }),
    ).toBeInTheDocument();
  });

  it("opens the move picker from a tree row's menu and closes it without moving anything", async () => {
    const reorgs: unknown[] = [];
    server.use(mockReorg(reorgs));
    renderPage("/inventory/locations");

    await userEvent.click(
      await screen.findByRole("button", { name: "Actions for Freezer" }),
    );
    // The row is chosen by the same press, so the open location's own Move
    // button is on screen too; the menu's is the one inside its popover.
    const menu = await screen.findByRole("dialog", { name: "" });
    await userEvent.click(
      within(menu).getByRole("button", { name: "Move to…" }),
    );

    const picker = await screen.findByRole("dialog", { name: "Move to…" });
    await userEvent.click(
      within(picker).getByRole("button", { name: "Cancel" }),
    );

    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Move to…" }),
      ).not.toBeInTheDocument(),
    );
    expect(reorgs).toHaveLength(0);
  });

  it("moves a location to the top level from the picker's 'Top level'", async () => {
    const reorgs: unknown[] = [];
    server.use(mockReorg(reorgs));
    renderPage("/inventory/locations/zone");

    const moveButtons = await screen.findAllByRole("button", {
      name: "Move to…",
    });
    await userEvent.click(moveButtons[0]);
    const picker = await screen.findByRole("dialog", { name: "Move to…" });
    await userEvent.click(
      await within(picker).findByRole("button", { name: "Top level" }),
    );

    await waitFor(() => expect(reorgs).toHaveLength(1));
    expect(reorgs[0]).toEqual({
      operations: [{ op: "move", id: "zone", parent_id: null }],
    });
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Move to…" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("selects the parent once the open location is deleted from its settings", async () => {
    const deleted: string[] = [];
    server.use(
      http.delete("/api/v1/locations/:id", ({ params }) => {
        deleted.push(String(params.id));
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderPage("/inventory/locations/zone");

    await userEvent.click(await screen.findByRole("tab", { name: "Settings" }));
    await userEvent.click(
      await within(await screen.findByRole("tabpanel")).findByRole("button", {
        name: "Actions for Dry Goods",
      }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Delete" }),
    );
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Delete",
      }),
    );

    await waitFor(() => expect(deleted).toEqual(["zone"]));
    expect(
      await screen.findByRole("heading", { name: "Pantry Building" }),
    ).toBeInTheDocument();
  });

  it("renames the open location inline and confirms with the toast", async () => {
    const updates: Array<Record<string, unknown>> = [];
    server.use(
      http.put("/api/v1/locations/:id", async ({ request, params }) => {
        updates.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(detailFor(String(params.id)));
      }),
    );
    renderPage("/inventory/locations/zone");

    await userEvent.click(
      await screen.findByRole("button", { name: "Rename" }),
    );
    const field = screen.getByLabelText("Location name");
    await userEvent.clear(field);
    await userEvent.type(field, "Dry pantry");
    await userEvent.click(screen.getByRole("button", { name: "Save name" }));

    await waitFor(() => expect(updates).toEqual([{ name: "Dry pantry" }]));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "Location updated successfully!",
      ),
    );
  });

  it("puts the old name back and shows the reason when the rename is refused", async () => {
    server.use(
      http.put("/api/v1/locations/:id", () =>
        HttpResponse.json({ detail: "Name taken" }, { status: 409 }),
      ),
    );
    renderPage("/inventory/locations/zone");

    await userEvent.click(
      await screen.findByRole("button", { name: "Rename" }),
    );
    const field = screen.getByLabelText("Location name");
    await userEvent.clear(field);
    await userEvent.type(field, "Freezer");
    await userEvent.keyboard("{Enter}");

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Name taken"));
    expect(
      await screen.findByRole("heading", { name: "Dry Goods" }),
    ).toBeInTheDocument();
  });

  it("says the label could not be downloaded when the server refuses the preview", async () => {
    server.use(
      http.get("/api/v1/locations/:id/print", () =>
        HttpResponse.json({ detail: "Printer offline" }, { status: 400 }),
      ),
    );
    renderPage("/inventory/locations/zone");

    await userEvent.click(
      await screen.findByRole("button", { name: "Download label" }),
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Error downloading labels"),
    );
  });

  it("climbs to the parent by name from the phone's back button", async () => {
    renderPage("/inventory/locations/leaf");
    await screen.findByRole("heading", { name: "Shelf A" });

    const back = screen.getAllByRole("button", { name: "Dry Goods" });
    await userEvent.click(back[0]);

    expect(
      await screen.findByRole("heading", { name: "Dry Goods" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Shelf A" }),
    ).not.toBeInTheDocument();
  });

  it("returns to the unselected screen from the first step of the path", async () => {
    renderPage("/inventory/locations/zone");
    const path = await screen.findByRole("navigation", {
      name: "Location path",
    });

    await userEvent.click(within(path).getByRole("button", { name: /^All/ }));

    expect(await screen.findByText("Choose a location")).toBeInTheDocument();
  });

  it("opens a child from the Contents table by its row, its name or its phone row", async () => {
    renderPage("/inventory/locations/zone");
    const table = await screen.findByRole("table");

    // Anywhere on the row.
    await userEvent.click(within(table).getByText("SA"));
    expect(
      await screen.findByRole("heading", { name: "Shelf A" }),
    ).toBeInTheDocument();

    // The name inside the row.
    await userEvent.click(
      within(
        screen.getByRole("navigation", { name: "Location path" }),
      ).getByRole("button", { name: "Dry Goods" }),
    );
    await userEvent.click(
      await within(await screen.findByRole("table")).findByRole("button", {
        name: "Shelf A",
      }),
    );
    expect(
      await screen.findByRole("heading", { name: "Shelf A" }),
    ).toBeInTheDocument();

    // The phone's full-width row.
    await userEvent.click(
      within(
        screen.getByRole("navigation", { name: "Location path" }),
      ).getByRole("button", { name: "Dry Goods" }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: /^Shelf A\s*SA/ }),
    );
    expect(
      await screen.findByRole("heading", { name: "Shelf A" }),
    ).toBeInTheDocument();
  });

  it("selects a child from the phone list and clears the selection again", async () => {
    renderPage("/inventory/locations/zone");
    await screen.findByRole("table");

    const boxes = await screen.findAllByRole("checkbox", {
      name: "Select Shelf A",
    });
    await userEvent.click(boxes[boxes.length - 1]);
    expect(screen.getByText("1 location selected")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Clear" }));

    expect(screen.queryByText("1 location selected")).not.toBeInTheDocument();
    for (const box of screen.getAllByRole("checkbox", {
      name: "Select Shelf A",
    })) {
      expect(box).not.toBeChecked();
    }
  });

  it("pages through a location holding more children than one page, and back", async () => {
    const requests = serveLocations([
      ...summaries,
      ...Array.from({ length: 70 }, (_, i) => ({
        id: `extra-${i}`,
        name: `Extra ${String(i).padStart(2, "0")}`,
        parent_id: "zone",
      })),
    ]);
    renderPage("/inventory/locations/zone");
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Shelf A")).toBeInTheDocument();
    expect(within(table).queryByText("Extra 55")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));

    expect(await within(table).findByText("Extra 55")).toBeInTheDocument();
    expect(within(table).queryByText("Shelf A")).not.toBeInTheDocument();
    const offsets = requests
      .filter((r) => r.get("parent_id") === "zone" && r.get("limit") === "50")
      .map((r) => r.get("offset"));
    expect(offsets).toContain("50");

    await userEvent.click(
      screen.getByRole("button", { name: "Previous page" }),
    );

    expect(await within(table).findByText("Shelf A")).toBeInTheDocument();
  });

  it("offers a retry when what stands inside could not be read", async () => {
    let failing = true;
    server.use(
      http.get("/api/v1/locations", ({ request }) => {
        const query = new URL(request.url).searchParams;
        return failing && query.get("parent_id") === "zone"
          ? HttpResponse.json({ detail: "down" }, { status: 500 })
          : undefined;
      }),
    );
    renderPage("/inventory/locations/zone");

    const retry = await screen.findByRole("button", { name: "Try again" });
    failing = false;
    await userEvent.click(retry);

    expect(
      within(await screen.findByRole("table")).getByText("Shelf A"),
    ).toBeInTheDocument();
  });

  it("selects the scanned location when the scan button is pressed instead of Enter", async () => {
    server.use(
      http.get("/api/v1/labels/scan/:code", () =>
        HttpResponse.json({
          status: "storage_context",
          label_code: "FZ",
          action: "set_storage_context",
          location: { id: "freezer", name: "Freezer", icon: "BOX" },
        }),
      ),
    );
    renderPage("/inventory/locations/zone");

    const scan = await screen.findByLabelText("Scan a location label…");
    expect(
      screen.getByRole("button", { name: "Select the scanned location" }),
    ).toBeDisabled();
    await userEvent.type(scan, "FZ-999");
    await userEvent.click(
      screen.getByRole("button", { name: "Select the scanned location" }),
    );

    expect(
      await screen.findByRole("heading", { name: "Freezer" }),
    ).toBeInTheDocument();
    expect(scan).toHaveValue("");
  });
});
