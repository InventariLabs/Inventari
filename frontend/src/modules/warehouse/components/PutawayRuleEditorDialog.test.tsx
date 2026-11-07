import { describe, expect, it, vi, beforeEach } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { render, screen, waitFor } from "@/test/utils";
import { within } from "@testing-library/react";
import { server } from "@/test/mocks/server";
import { serveLocations } from "@/test/serveLocations";

import { PutawayRuleEditorDialog } from "./PutawayRuleEditorDialog";
import type { PutawayRule } from "@/modules/warehouse/api/putaway";
import { useAuthStore } from "@/store/authStore";
import type { Category, StorageType } from "@/types/inventory";
import { onePage } from "@/test/mocks/page";

const categories = [
  { id: "cat-1", name: "Dairy", context_tag: "cold_storage" },
  { id: "cat-2", name: "Meat", context_tag: "cold_storage" },
  { id: "cat-3", name: "Dry goods", context_tag: "ambient" },
  { id: "cat-4", name: "Uncategorised", context_tag: null },
  // A module-owned category: the module-data policy keeps it off this
  // general screen's pickers while it is off.
  { id: "cat-eq", name: "Laptop", context_tag: "equipment" },
] as unknown as Category[];

const storageTypes = [
  { id: "st-1", name: "Freezer", type_code: "FREEZER" },
  { id: "st-2", name: "Shelf", type_code: "SHELF" },
] as unknown as StorageType[];

const { storageTypesMock, storageTypesFailure } = vi.hoisted(() => ({
  storageTypesMock: vi.fn(),
  storageTypesFailure: { failed: false },
}));

/**
 * The categories endpoint as the backend answers it: the flag is the
 * organization policy's, and the scoped answer drops the module rows. Serving
 * it here — rather than mocking the hook — is what lets a test see whether
 * the picker asked with the flag at all.
 */
function serveCategories() {
  server.use(
    http.get("/api/v1/categories", ({ request }) => {
      const url = new URL(request.url);
      const exclude =
        url.searchParams.get("exclude_module_contexts") === "true";
      // Only the tag a module claims is excluded — the core categories'
      // cold_storage / ambient groups stay, exactly as the backend's
      // `get_claimed_context_tags` answers.
      return HttpResponse.json(
        onePage(
          exclude
            ? categories.filter((c) => c.context_tag !== "equipment")
            : categories,
        ),
      );
    }),
  );
}

// What the server holds: a warehouse and a rack inside it.
const PLACES = [
  { id: "loc-1", name: "Cold Store" },
  { id: "loc-2", name: "Rack C-2", parent_id: "loc-1" },
];
let locationRequests: URLSearchParams[] = [];

vi.mock("@/modules/shared/hooks/useStorages", () => ({
  useStorages: () => ({ data: [{ id: "loc-1", name: "Cold Store" }] }),
  useStorageTypes: () =>
    storageTypesFailure.failed
      ? {
          data: undefined,
          isError: true,
          error: new Error("boom"),
          refetch: vi.fn(),
        }
      : { data: storageTypesMock() },
}));

function renderDialog(
  props: Partial<React.ComponentProps<typeof PutawayRuleEditorDialog>> = {},
) {
  return render(
    <PutawayRuleEditorDialog
      open
      onClose={vi.fn()}
      onSubmit={vi.fn()}
      isPending={false}
      {...props}
    />,
  );
}

beforeEach(() => {
  storageTypesFailure.failed = false;
  storageTypesMock.mockReturnValue(storageTypes);
  locationRequests = serveLocations(PLACES);
  serveCategories();
});

describe("PutawayRuleEditorDialog", () => {
  it("says the locations could not be loaded instead of offering none", async () => {
    server.use(
      http.get("/api/v1/locations", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    renderDialog();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it("says the storage types could not be loaded instead of dropping the picker", async () => {
    storageTypesFailure.failed = true;
    renderDialog();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Location type/i }),
    ).not.toBeInTheDocument();
  });

  it("offers the context tags the organization actually has, not a text box", async () => {
    // the server knows the closed set — it builds it to reject
    // anything outside it. Asking the user to retype a technical identifier
    // they have never been shown is asking them to guess a password.
    const user = userEvent.setup();
    renderDialog();

    expect(
      screen.queryByPlaceholderText("e.g. cold_storage"),
    ).not.toBeInTheDocument();

    await user.click(
      await screen.findByRole("combobox", { name: /Category group/i }),
    );

    expect(await screen.findByText("cold_storage")).toBeInTheDocument();
    expect(screen.getByText("ambient")).toBeInTheDocument();
    // The tag is an identifier; the categories behind it are what the user knows.
    expect(screen.getByText(/Dairy, Meat/)).toBeInTheDocument();
  });

  it("lays the match pickers out in a column that cannot outgrow the form", async () => {
    // jsdom measures no widths, so the class is what can be asserted: the
    // bare implicit grid column is `auto`, and a chosen group's list of
    // category names stretched it to 849 px inside a 334 px phone form.
    renderDialog();

    const picker = await screen.findByRole("combobox", {
      name: /Category group/i,
    });
    const grid = picker.closest(".grid");
    expect(grid).not.toBeNull();
    expect(grid).toHaveClass("grid-cols-1");
  });

  it("names storage types and never shows the word code", async () => {
    const user = userEvent.setup();
    renderDialog();

    expect(
      screen.queryByPlaceholderText("e.g. FREEZER"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/Location type code/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("combobox", { name: /Location type/i }));

    expect(await screen.findByText("Freezer")).toBeInTheDocument();
    expect(screen.getByText("Shelf")).toBeInTheDocument();
  });

  it("submits the type code the engine matches on, not the display name", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    servePutawayState({ capacity: [], cells: [] });
    renderDialog({ onSubmit });

    await user.click(screen.getByRole("combobox", { name: /Location type/i }));
    await user.click(await screen.findByText("Freezer"));
    await user.click(screen.getByRole("combobox", { name: /To location/i }));
    await user.click(await screen.findByText("Rack C-2"));
    await user.click(screen.getByRole("button", { name: "Create rule" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        location_type_code: "FREEZER",
        // The rule's shelves travel as an ordered list now — one picker
        // choice is a list of one.
        location_ids: ["loc-2"],
      }),
    );
  });

  it("appends shelves in order and lets the order be changed", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    servePutawayState({ capacity: [], cells: [] });
    renderDialog({ onSubmit });

    const targetPicker = () =>
      screen.getByRole("combobox", { name: /To location/i });
    await user.click(targetPicker());
    await user.click(await screen.findByText("Rack C-2"));
    // The popover closes on a pick; reopen for the second shelf.
    await user.click(targetPicker());
    await user.click(await screen.findByText("Cold Store"));
    await user.click(screen.getByRole("combobox", { name: /Location type/i }));
    await user.click(await screen.findByText("Freezer"));
    // The list keeps the choosing order: first picked tries first.
    const items = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Rack C-2");
    expect(items[1]).toHaveTextContent("Cold Store");

    // Moving the second shelf up makes it the one the resolver tries first.
    await user.click(
      within(screen.getByRole("list")).getAllByRole("button", {
        name: /Move up/i,
      })[1],
    );
    const reordered = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(reordered[0]).toHaveTextContent("Cold Store");

    await user.click(screen.getByRole("button", { name: "Create rule" }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        location_type_code: "FREEZER",
        location_ids: ["loc-1", "loc-2"],
      }),
    );
  });

  it("asks for the target location in a sentence, not a field name", async () => {
    servePutawayState({ capacity: [], cells: [] });
    renderDialog({});

    const picker = screen.getByRole("combobox", { name: /To location/i });
    expect(picker).toHaveTextContent("Select a location");
    expect(picker).not.toHaveTextContent("Select the To location");
  });

  it("says the conditions are an alternative, not a conjunction", async () => {
    // four fields stacked in a column read as filters joined by
    // AND. The resolver fires on ANY filled key, so a user filling two
    // gets a rule far wider than the form suggested.
    const user = userEvent.setup();
    renderDialog();

    expect(
      screen.getByText(/fires when any one of these matches/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("combobox", { name: /Category$/i }));
    await user.click(await screen.findByText("Dairy"));
    await user.click(screen.getByRole("combobox", { name: /Location type/i }));
    await user.click(await screen.findByText("Freezer"));

    // The summary spells out the rule the user just built.
    const summary = screen.getByTestId("putaway-match-summary");
    expect(summary).toHaveTextContent("Dairy");
    expect(summary).toHaveTextContent("Freezer");
    expect(summary).toHaveTextContent(/ or /i);
    // …and which of the two decides when both match.
    expect(summary).toHaveTextContent(/most specific wins/i);
  });

  it("scopes the priority hint to what priority actually decides", () => {
    // "Lower number = higher priority" read as though priority settled
    // everything; it only ranks rules of the same specificity tier.
    renderDialog();

    expect(
      screen.getByText(/only decides between rules of the same specificity/i),
    ).toBeInTheDocument();
  });

  it("will not offer to create a rule the server would refuse", async () => {
    // A blank form has no match key, and the server answers one with 400.
    // The button stood ready to send it, and the refusal arrived after the
    // work — with nothing on screen saying why the click did nothing.
    const user = userEvent.setup();
    renderDialog();

    const submit = screen.getByRole("button", { name: "Create rule" });
    expect(submit).toBeDisabled();
    expect(
      screen.getByText("At least one match key is required"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("combobox", { name: /Category$/i }));
    await user.click(await screen.findByText("Dairy"));

    expect(submit).toBeEnabled();
    expect(screen.queryByText("At least one match key is required")).toBeNull();
  });

  it("offers locations inside a warehouse, not just the warehouses", async () => {
    // the target list was fed by the top-level storages endpoint
    // while the field said "location" — two different levels of the
    // hierarchy and two different words (UI_GUIDELINES §14.2). Putaway is
    // only useful at the shelf: "dairy to Cold Store" is a rough rule,
    // "dairy to Rack C-2" is an actionable one.
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole("combobox", { name: /To location/i }));

    expect(await screen.findByText("Rack C-2")).toBeInTheDocument();
    // Twice: once as a warehouse of its own, once as the path telling the
    // reader which warehouse the shelf sits in.
    expect(screen.getAllByText("Cold Store")).toHaveLength(2);
  });

  it("hides a match key the organization has no values for", () => {
    // An empty picker is a worse answer than no picker: it invites the user
    // to look for something that does not exist yet.
    server.use(
      http.get("/api/v1/categories", () => HttpResponse.json(onePage([]))),
    );
    storageTypesMock.mockReturnValue([]);
    renderDialog();

    expect(screen.queryByText(/Category group/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Location type/i)).not.toBeInTheDocument();
  });

  it("does not offer a module-owned category while module data is off", async () => {
    // The same dialog already scopes its target locations to the policy; the
    // category picker used the unscoped list, so a rule could be written on
    // "Laptop" — a category whose records the list below then never shows.
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole("combobox", { name: /Category$/i }));

    expect(await screen.findByText("Dairy")).toBeInTheDocument();
    expect(screen.queryByText("Laptop")).not.toBeInTheDocument();
  });

  it("offers the module categories once the organization mixes lists", async () => {
    server.use(
      http.get("/api/v1/organizations/my", () =>
        HttpResponse.json({
          id: "1",
          name: "Test Organization",
          currency: "PLN",
          settings: { show_module_data: true },
        }),
      ),
    );
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole("combobox", { name: /Category$/i }));

    expect(await screen.findByText("Laptop")).toBeInTheDocument();
  });

  it("asks the server to hide module-owned locations while the policy is off", async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole("combobox", { name: /To location/i }));
    await screen.findByText("Rack C-2");

    expect(locationRequests.length).toBeGreaterThan(0);
    for (const asked of locationRequests) {
      expect(asked.get("exclude_module_contexts")).toBe("true");
    }
  });

  it("asks for every location once the organization mixes lists", async () => {
    server.use(
      http.get("/api/v1/organizations/my", () =>
        HttpResponse.json({
          id: "1",
          name: "Test Organization",
          currency: "PLN",
          settings: { show_module_data: true },
        }),
      ),
    );
    const user = userEvent.setup();
    renderDialog();

    await waitFor(() => {
      const last = locationRequests.at(-1);
      expect(last).toBeDefined();
      expect(last?.get("exclude_module_contexts")).toBeNull();
    });
    await user.click(screen.getByRole("combobox", { name: /To location/i }));
    await screen.findByText("Rack C-2");
  });

  it("never reads the organization's locations whole", async () => {
    locationRequests = serveLocations(
      Array.from({ length: 400 }, (_, i) => ({
        id: `shelf-${i}`,
        name: `Shelf ${i}`,
      })),
    );
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole("combobox", { name: /To location/i }));
    await screen.findByText("Shelf 0");

    expect(screen.queryByText("Shelf 399")).not.toBeInTheDocument();
    expect(
      locationRequests.every((asked) => Number(asked.get("limit")) <= 30),
    ).toBe(true);
  });

  it("says which module a module-owned location belongs to", async () => {
    // The module's place only reaches the picker when the organization
    // mixes module data into its lists.
    server.use(
      http.get("/api/v1/organizations/my", () =>
        HttpResponse.json({
          id: "1",
          name: "Test Organization",
          currency: "PLN",
          settings: { show_module_data: true },
        }),
      ),
    );
    serveLocations([
      { id: "loc-1", name: "Cold Store" },
      {
        id: "loc-2",
        name: "Rack C-2",
        parent_id: "loc-1",
        context_tag: "equipment",
      },
    ]);
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole("combobox", { name: /To location/i }));

    // Rack C-2 is tagged equipment — the option names the owner next to the
    // name, or it would read as one of the organization's own locations.
    expect(
      await screen.findByText("Module: Equipment Tracking"),
    ).toBeInTheDocument();
  });
});

describe("PutawayRuleEditorDialog on a short screen", () => {
  // At 320×568 the dialog rendered 814px tall with no scrolling of
  // its own and centred, so all three exits — close, Create, Cancel — sat
  // outside the screen and the only way out was a page reload. jsdom cannot
  // measure pixels; what it can pin is who owns the scroll and who may never
  // be scrolled away. The rest takes a real browser to measure.
  function scrollBodyOf(dialog: HTMLElement): HTMLElement | null {
    return dialog.querySelector(".overflow-y-auto");
  }

  it("caps itself to the viewport and owns its scrolling inside the fields", () => {
    renderDialog();

    const dialog = screen.getByRole("dialog");
    // The cap is a height criterion, not a width one — the report measured
    // 33 sibling dialogs at the same width and found no other hit.
    expect(dialog).toHaveClass("max-h-[90vh]");
    expect(dialog).toHaveClass("overflow-hidden");

    expect(scrollBodyOf(dialog)).not.toBeNull();
  });

  it("keeps every exit out of the scrolling region", () => {
    renderDialog();

    const scrollBody = scrollBodyOf(screen.getByRole("dialog"));
    expect(scrollBody).not.toBeNull();

    const exits = [
      ...screen.getAllByRole("button", { name: /close/i }),
      screen.getByRole("button", { name: "Create rule" }),
      screen.getByRole("button", { name: "Cancel" }),
    ];
    for (const exit of exits) {
      expect(scrollBody).not.toContainElement(exit);
    }
  });

  it("shows a validation refusal above the actions, not buried in the scroll", async () => {
    // Create without a target location refuses; the refusal is the thing the
    // reader must see at the moment they press, so it belongs next to the
    // buttons, not at the bottom of a scrolled-away field list. A match key
    // comes first — without one the button does not offer to send at all.
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole("combobox", { name: /Category$/i }));
    await user.click(await screen.findByText("Dairy"));
    await user.click(screen.getByRole("button", { name: "Create rule" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "To location is required",
    );
    const scrollBody = scrollBodyOf(screen.getByRole("dialog"));
    expect(scrollBody).not.toBeNull();
    expect(scrollBody).not.toContainElement(screen.getByRole("alert"));
  });
});

/* What each target of the rule holds: its limit and fill for the rule's
 * product, or the mixing and the number of limits when the rule matches no
 * product — read from the shared fill response, not counted here. */

interface CapacityRowFixture {
  id: string;
  organization_id: string;
  location_id: string;
  product_template_id: string;
  max_quantity: string;
  product_template_name?: string | null;
  product_unit_symbol?: string | null;
}

interface OccupancyCellFixture {
  location_id: string;
  location_name: string | null;
  entries: {
    product_template_id: string;
    product_template_name?: string | null;
    quantity: string;
    max_quantity: string | null;
    share: number | null;
  }[];
  status: "empty" | "no_limit" | "ok" | "nearly_full" | "over";
  fill: number | null;
  capped_products: number;
  unmeasured: boolean;
}

function capRow(
  id: string,
  locationId: string,
  productId: string,
  maxQuantity: string,
  unit = "kg",
): CapacityRowFixture {
  return {
    id,
    organization_id: "org-1",
    location_id: locationId,
    product_template_id: productId,
    max_quantity: maxQuantity,
    product_template_name: "Damson Plums",
    product_unit_symbol: unit,
  };
}

function cell(
  fixture: Partial<OccupancyCellFixture> & { location_id: string },
): OccupancyCellFixture {
  return {
    location_name: null,
    entries: [],
    status: "empty",
    fill: null,
    capped_products: 0,
    unmeasured: false,
    ...fixture,
  };
}

function ruleFixture(overrides: Record<string, unknown> = {}): PutawayRule {
  return {
    id: "rule-1",
    organization_id: "org-1",
    product_template_id: "prod-1",
    category_id: null,
    context_tag: null,
    location_type_code: null,
    target_location_id: "loc-1",
    locations: [
      {
        location_id: "loc-1",
        position: 1,
        location_name: "Cold Store",
        active: true,
      },
      {
        location_id: "loc-2",
        position: 2,
        location_name: "Rack C-2",
        active: true,
      },
    ],
    priority: 100,
    is_active: true,
    created_at: "2026-10-20T10:00:00.000Z",
    product_template_name: "Damson Plums",
    ...overrides,
  } as unknown as PutawayRule;
}

/**
 * The capacity, the mix flag and the shared fill read, as the backend
 * answers them — held in state the save test can change, so the read after
 * a Save carries what the settings panel wrote.
 */
function servePutawayState(initial: {
  capacity: CapacityRowFixture[];
  settings?: { location_id: string; single_product: boolean }[];
  cells: OccupancyCellFixture[];
}) {
  const state = {
    capacity: initial.capacity.map((entry) => ({ ...entry })),
    settings: initial.settings ?? [],
    cells: initial.cells,
  };
  server.use(
    http.get("/api/v1/warehouse/putaway/capacity", ({ request }) => {
      const locationId = new URL(request.url).searchParams.get("location_id");
      return HttpResponse.json(
        onePage(
          locationId
            ? state.capacity.filter((entry) => entry.location_id === locationId)
            : state.capacity,
        ),
      );
    }),
    http.get("/api/v1/warehouse/putaway/capacity-settings", () =>
      HttpResponse.json(onePage(state.settings)),
    ),
    http.get(
      "/api/v1/warehouse/putaway/capacity-settings/:locationId",
      ({ params }) =>
        HttpResponse.json(
          state.settings.find(
            (setting) => setting.location_id === params.locationId,
          ) ?? {
            location_id: params.locationId,
            single_product: false,
          },
        ),
    ),
    http.get("/api/v1/warehouse/putaway/occupancy/:locationId", ({ params }) =>
      HttpResponse.json({
        locations: state.cells.filter(
          (entry) => entry.location_id === params.locationId,
        ),
        signals: [],
      }),
    ),
    http.put(
      "/api/v1/warehouse/putaway/capacity/:entryId",
      async ({ params, request }) => {
        const body = (await request.json()) as { max_quantity: string };
        const entry = state.capacity.find((row) => row.id === params.entryId);
        if (!entry) return new HttpResponse(null, { status: 404 });
        entry.max_quantity = body.max_quantity;
        for (const entryCell of state.cells) {
          for (const row of entryCell.entries) {
            if (row.product_template_id === entry.product_template_id) {
              row.max_quantity = body.max_quantity;
              // The backend recomputes the share and the state from the
              // new limit; so does the fixture.
              const share =
                (Number(row.quantity) / Number(body.max_quantity)) * 100;
              row.share = share;
              entryCell.fill = share;
              entryCell.status =
                share >= 100 ? "over" : share >= 90 ? "nearly_full" : "ok";
            }
          }
        }
        return HttpResponse.json(entry);
      },
    ),
    http.get("/api/v1/items/product-templates/:templateId", ({ params }) =>
      HttpResponse.json({
        id: params.templateId,
        name: "Damson Plums",
        sku: null,
        barcode: null,
        brand: null,
        uom_id: null,
        image_url: null,
      }),
    ),
  );
  return state;
}

describe("PutawayRuleEditorDialog on the rule's targets", () => {
  beforeEach(() => {
    // The settings panel writes only for an account the API would accept.
    useAuthStore.setState({
      user: {
        id: "1",
        role: "admin",
        is_superuser: false,
        is_blocked: false,
        is_active: true,
      } as never,
    });
  });

  it("shows the rule's product limit and fill on each target", async () => {
    servePutawayState({
      capacity: [capRow("cap-1", "loc-1", "prod-1", "50")],
      cells: [
        cell({
          location_id: "loc-1",
          entries: [
            {
              product_template_id: "prod-1",
              product_template_name: "Damson Plums",
              quantity: "12",
              max_quantity: "50",
              share: 24,
            },
          ],
          status: "ok",
          fill: 24,
          capped_products: 1,
        }),
        cell({ location_id: "loc-2" }),
      ],
    });
    renderDialog({ rule: ruleFixture() });

    const items = within(await screen.findByRole("list")).getAllByRole(
      "listitem",
    );
    expect(items[0]).toHaveTextContent("12 / 50 kg");
    // A shelf without the product's limit says so — and what may stand there.
    expect(items[1]).toHaveTextContent("No limit · different products");
  });

  it("says a target is almost full and what a delivery larger than what still fits does", async () => {
    servePutawayState({
      capacity: [capRow("cap-1", "loc-1", "prod-1", "50")],
      cells: [
        cell({
          location_id: "loc-1",
          entries: [
            {
              product_template_id: "prod-1",
              product_template_name: "Damson Plums",
              quantity: "46",
              max_quantity: "50",
              share: 92,
            },
          ],
          status: "nearly_full",
          fill: 92,
          capped_products: 1,
        }),
        cell({ location_id: "loc-2" }),
      ],
    });
    renderDialog({ rule: ruleFixture() });

    const items = within(await screen.findByRole("list")).getAllByRole(
      "listitem",
    );
    expect(items[0]).toHaveTextContent("46 / 50 kg — almost full");
    expect(
      screen.getByText(
        /a delivery larger than what still fits goes to the next one/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/the overflow always fits there/i),
    ).toBeInTheDocument();
  });

  it("says the delivery goes to the last target anyway when there is no next one", async () => {
    servePutawayState({
      capacity: [capRow("cap-1", "loc-1", "prod-1", "50")],
      cells: [
        cell({
          location_id: "loc-1",
          entries: [
            {
              product_template_id: "prod-1",
              product_template_name: "Damson Plums",
              quantity: "46",
              max_quantity: "50",
              share: 92,
            },
          ],
          status: "nearly_full",
          fill: 92,
          capped_products: 1,
        }),
      ],
    });
    renderDialog({
      rule: ruleFixture({
        locations: [
          {
            location_id: "loc-1",
            position: 1,
            location_name: "Cold Store",
            active: true,
          },
        ],
        target_location_id: "loc-1",
      }),
    });

    expect(
      await screen.findByText(
        /goes there anyway and is marked over the limit/i,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/the overflow always fits there/i)).toBeNull();
  });

  it("says nothing about the overflow while the first target has room", async () => {
    servePutawayState({
      capacity: [capRow("cap-1", "loc-1", "prod-1", "50")],
      cells: [
        cell({
          location_id: "loc-1",
          entries: [
            {
              product_template_id: "prod-1",
              product_template_name: "Damson Plums",
              quantity: "12",
              max_quantity: "50",
              share: 24,
            },
          ],
          status: "ok",
          fill: 24,
          capped_products: 1,
        }),
        cell({ location_id: "loc-2" }),
      ],
    });
    renderDialog({ rule: ruleFixture() });

    await screen.findByRole("list");
    expect(
      screen.queryByText(/a delivery larger than what still fits/i),
    ).toBeNull();
  });

  it("shows the mixing and the number of limits when the rule matches no product", async () => {
    servePutawayState({
      capacity: [
        capRow("cap-1", "loc-1", "prod-1", "50"),
        capRow("cap-2", "loc-1", "prod-2", "30", "pcs"),
      ],
      cells: [cell({ location_id: "loc-1" }), cell({ location_id: "loc-2" })],
    });
    renderDialog({
      rule: ruleFixture({ product_template_id: null, category_id: "cat-1" }),
    });

    const items = within(await screen.findByRole("list")).getAllByRole(
      "listitem",
    );
    expect(items[0]).toHaveTextContent("2 product limits · different products");
    expect(items[1]).toHaveTextContent("No limit · different products");
  });

  it("says one product only where the target takes one product", async () => {
    servePutawayState({
      capacity: [],
      settings: [{ location_id: "loc-2", single_product: true }],
      cells: [cell({ location_id: "loc-1" }), cell({ location_id: "loc-2" })],
    });
    renderDialog({ rule: ruleFixture() });

    const items = within(await screen.findByRole("list")).getAllByRole(
      "listitem",
    );
    expect(items[1]).toHaveTextContent("No limit · One product only");
  });

  it("does not call a target unlimited while its limits could not be read", async () => {
    servePutawayState({
      capacity: [capRow("cap-1", "loc-1", "prod-1", "22")],
      cells: [cell({ location_id: "loc-1" }), cell({ location_id: "loc-2" })],
    });
    server.use(
      http.get("/api/v1/warehouse/putaway/capacity", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    renderDialog({ rule: ruleFixture() });

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    const list = screen.getByRole("list");
    expect(list).not.toHaveTextContent(/no limit/i);
    expect(
      within(list).queryByRole("button", { name: /set/i }),
    ).not.toBeInTheDocument();
  });

  it("does not show an empty target while what it holds could not be read", async () => {
    servePutawayState({
      capacity: [capRow("cap-1", "loc-1", "prod-1", "22")],
      cells: [cell({ location_id: "loc-1" }), cell({ location_id: "loc-2" })],
    });
    server.use(
      http.get("/api/v1/warehouse/putaway/occupancy/loc-1", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    renderDialog({ rule: ruleFixture() });

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    const items = within(screen.getByRole("list")).getAllByRole("listitem");
    // The second target's own reads arrived and are shown; the first is not
    // presented as holding nothing.
    await waitFor(() =>
      expect(items[1]).toHaveTextContent("No limit · different products"),
    );
    expect(items[0]).not.toHaveTextContent("0 / 22");
  });

  it("opens the location settings of the shelf the link belongs to", async () => {
    servePutawayState({
      capacity: [capRow("cap-1", "loc-1", "prod-1", "50")],
      cells: [cell({ location_id: "loc-1" }), cell({ location_id: "loc-2" })],
    });
    const user = userEvent.setup();
    renderDialog({ rule: ruleFixture() });

    const items = within(await screen.findByRole("list")).getAllByRole(
      "listitem",
    );
    // The shelf that already holds a limit invites an edit with "Set";
    // one that holds none invites the limit with "Set limit".
    expect(
      within(items[0]).getByRole("button", {
        name: "Set the limit for Cold Store",
      }),
    ).toHaveTextContent("Set");
    const setLimit = within(items[1]).getByRole("button", {
      name: "Set the limit for Rack C-2",
    });
    expect(setLimit).toHaveTextContent("Set limit");

    await user.click(setLimit);

    const panel = await screen.findByRole("dialog", {
      name: "Location settings",
    });
    // Over the rule editor, not instead of it.
    expect(screen.getAllByRole("dialog")).toHaveLength(2);
    expect(panel).toBeInTheDocument();
  });

  it("shows a limit saved in the settings without reopening the rule", async () => {
    servePutawayState({
      capacity: [capRow("cap-1", "loc-1", "prod-1", "50")],
      cells: [
        cell({
          location_id: "loc-1",
          entries: [
            {
              product_template_id: "prod-1",
              product_template_name: "Damson Plums",
              quantity: "46",
              max_quantity: "50",
              share: 92,
            },
          ],
          status: "nearly_full",
          fill: 92,
          capped_products: 1,
        }),
        cell({ location_id: "loc-2" }),
      ],
    });
    const user = userEvent.setup();
    renderDialog({ rule: ruleFixture() });

    const items = within(await screen.findByRole("list")).getAllByRole(
      "listitem",
    );
    expect(items[0]).toHaveTextContent("46 / 50 kg — almost full");

    await user.click(
      within(items[0]).getByRole("button", {
        name: "Set the limit for Cold Store",
      }),
    );
    const panel = await screen.findByRole("dialog", {
      name: "Location settings",
    });
    const limitField = within(panel).getByRole("spinbutton", {
      name: "Limit for Damson Plums",
    });
    await user.clear(limitField);
    await user.type(limitField, "100");
    await user.click(
      within(panel).getByRole("button", { name: "Save changes" }),
    );

    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Location settings" }),
      ).not.toBeInTheDocument(),
    );
    // The pair and its state come from the read the save refreshed: 46 of
    // 100 is room again, so the "almost full" gloss is gone with it.
    const refreshed = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(refreshed[0]).toHaveTextContent("46 / 100 kg");
    expect(refreshed[0]).not.toHaveTextContent("almost full");
    expect(
      screen.queryByText(/a delivery larger than what still fits/i),
    ).toBeNull();
  });
});
