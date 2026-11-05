import React from "react";
import {
  act,
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { useAuthStore } from "@/store/authStore";
import InventoryDashboard from "../pages/InventoryDashboard";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

// The header is the shell's; the page only hands it the actions.
const header = vi.hoisted(() => ({ actions: null as React.ReactNode }));
vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({
    setHeader: (data: { actions?: React.ReactNode }) => {
      header.actions = data.actions ?? null;
    },
  }),
}));
vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => true,
}));

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider
    client={
      new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      })
    }
  >
    <ModulesProvider>
      <MemoryRouter>{children}</MemoryRouter>
    </ModulesProvider>
  </QueryClientProvider>
);

const tree = [
  {
    id: "fridge",
    name: "Fridge",
    parent_id: null,
    usage: "internal",
    location_type_id: null,
    short_code: null,
    context_tag: null,
    items_count: 24,
    subtree_items_count: 24,
    children: [],
  },
  {
    id: "freezer",
    name: "Basement freezer",
    parent_id: null,
    usage: "internal",
    location_type_id: null,
    short_code: null,
    context_tag: null,
    items_count: 52,
    subtree_items_count: 52,
    children: [],
  },
];

const record = (id: string, name: string, location: string, extra = {}) => ({
  id,
  name,
  quantity: 1,
  location_id: location,
  template_id: `t-${id}`,
  expiry_date: "2026-09-21",
  ...extra,
});

let shoppingListPosts = 0;

function serve({
  modules = ["core", "items", "locations"],
  expired = [] as object[],
  expiring = [] as object[],
  low = [] as object[],
  total = 76,
} = {}) {
  const lowProducts = new Set(
    low.map(
      (item) =>
        (item as { template_id?: string; id: string }).template_id ??
        (item as { id: string }).id,
    ),
  );
  server.use(
    http.get("/api/v1/modules/my", () => HttpResponse.json(modules)),
    // The heading's number comes from the one count the statistics screen
    // reads too — the seeded rows are what the card lists, and this is what
    // the endpoint answers for them.
    http.get("/api/v1/items/attention-counts", () =>
      HttpResponse.json({
        expired: expired.length,
        expiring_soon: expiring.length,
        low_stock: lowProducts.size,
        records: expired.length + expiring.length + low.length,
      }),
    ),
    // The short products the card lists come from their own endpoint, one row
    // per product, not from the item records the dated groups use.
    http.get("/api/v1/stats/low-stock", () =>
      HttpResponse.json(
        onePage(
          low.map((item) => {
            const r = item as ReturnType<typeof record>;
            return {
              template_id: r.template_id,
              name: r.name,
              on_hand: r.quantity,
              minimum: 5,
              item_id: r.id,
              uom_symbol: null,
            };
          }),
        ),
      ),
    ),
    http.get("*/locations/tree", () => HttpResponse.json(tree)),
    // The places the records stand in are named by id, never read whole.
    http.get("*/locations", ({ request }) => {
      const ids = new URL(request.url).searchParams.getAll("ids");
      const items = tree.filter((place) => ids.includes(place.id));
      return HttpResponse.json({
        items,
        total: items.length,
        limit: 100,
        offset: 0,
        has_more: false,
      });
    }),
    http.get("*/location-types", () => HttpResponse.json(onePage([]))),
    http.get("*/stock-moves", () =>
      HttpResponse.json({
        items: [],
        total: 0,
        offset: 0,
        limit: 5,
        has_more: false,
      }),
    ),
    http.get("*/shopping-lists", () => HttpResponse.json(onePage([]))),
    http.post("*/shopping-lists", () => {
      shoppingListPosts += 1;
      return HttpResponse.json({ id: "new" });
    }),
    http.get("/api/v1/items", ({ request }) => {
      const p = new URL(request.url).searchParams;
      const items = p.get("only_expired")
        ? expired
        : p.get("expiring_days")
          ? expiring
          : p.get("only_low_stock")
            ? low
            : [];
      return HttpResponse.json({
        items,
        total: p.get("limit") === "1" ? total : items.length,
        offset: 0,
        limit: Number(p.get("limit")),
        has_more: false,
      });
    }),
  );
}

async function settle() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 100));
  });
}

describe("the inventory overview", () => {
  beforeEach(() => {
    header.actions = null;
    shoppingListPosts = 0;
    // Signed in, so the module list comes from /modules/my; signed out, the
    // provider falls back to the default install's list.
    useAuthStore.setState({ isAuthenticated: true });
    // Probes for what the shopping lists contribute while they are on: the
    // door, the modal behind it and the card beside the journal. What the
    // door shows and when is the shopping lists' business, tested with
    // their slots; what matters here is where the dashboard puts each one,
    // that the door opens the modal, and that nothing is written on the way.
    const shoppingSlots: Record<string, unknown> = {
      dashboard_replenish_action: ({
        data,
      }: {
        data: { onOpen: () => void };
      }) => (
        <button type="button" onClick={data.onOpen}>
          Replenish all
        </button>
      ),
      dashboard_activity_aside: () => <p>Shopping list</p>,
      dashboard_replenish_modal: ({ data }: { data: { isOpen: boolean } }) =>
        data.isOpen ? <div data-testid="replenish-open" /> : null,
    };
    vi.spyOn(moduleRegistry, "getSlotComponents").mockImplementation(
      (name: string, enabledModules: string[]) =>
        enabledModules.includes("shopping_lists") && shoppingSlots[name]
          ? [shoppingSlots[name] as never]
          : [],
    );
  });

  afterEach(() => {
    // Unmount first. Signing out under a mounted tree updates ModulesProvider
    // outside act(), and the re-render then draws the real slots the restored
    // spy no longer stands in for.
    cleanup();
    vi.restoreAllMocks();
    useAuthStore.setState({ isAuthenticated: false });
  });

  it("leads with what needs attention, most urgent first, and where it is", async () => {
    serve({
      expired: [record("milk", "UHT milk", "fridge")],
      low: [record("peas", "Frozen peas", "freezer", { expiry_date: null })],
    });
    render(<InventoryDashboard />, { wrapper });

    expect(
      await screen.findByRole("heading", { name: "2 records need attention" }),
    ).toBeInTheDocument();
    const rows = screen
      .getAllByRole("listitem")
      .filter((li) => within(li).queryByRole("link"));
    expect(rows[0]).toHaveTextContent("UHT milk");
    // Where it is arrives with the places the records stand in.
    await waitFor(() => {
      const [first] = screen
        .getAllByRole("listitem")
        .filter((li) => within(li).queryByRole("link"));
      expect(first).toHaveTextContent("Fridge");
    });
    expect(rows[1]).toHaveTextContent("Frozen peas");
    expect(screen.queryByText("All under control")).toBeNull();
    await settle();
  });

  it("folds to one line on a quiet day, still saying what it holds", async () => {
    serve({ total: 76 });
    render(<InventoryDashboard />, { wrapper });

    expect(
      await screen.findByRole("heading", { name: "All under control" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("In all: 76 records in 2 locations"),
    ).toBeInTheDocument();
    await settle();
  });

  it("does not call the day quiet before the lists have answered", async () => {
    serve({ total: 76 });
    let answer: () => void = () => {};
    const held = new Promise<void>((resolve) => (answer = resolve));
    server.use(
      http.get("/api/v1/items", async ({ request }) => {
        const p = new URL(request.url).searchParams;
        if (p.get("only_expired")) await held;
        return HttpResponse.json({
          items: [],
          total: p.get("limit") === "1" ? 76 : 0,
          offset: 0,
          limit: Number(p.get("limit")),
          has_more: false,
        });
      }),
    );
    render(<InventoryDashboard />, { wrapper });

    await settle();
    expect(screen.queryByText("All under control")).toBeNull();

    answer();
    expect(
      await screen.findByRole("heading", { name: "All under control" }),
    ).toBeInTheDocument();
    await settle();
  });

  it("colours the storage bars from the same records", async () => {
    serve({ expired: [record("milk", "UHT milk", "fridge")] });
    render(<InventoryDashboard />, { wrapper });

    const bar = await screen.findByRole("img", {
      name: /24 records: 1 expired/,
    });
    expect(bar).toBeInTheDocument();
    await settle();
  });

  it("opens the replenish preview without creating a shopping list", async () => {
    serve({
      modules: ["core", "items", "locations", "shopping_lists"],
      low: [record("peas", "Frozen peas", "freezer")],
    });
    render(<InventoryDashboard />, { wrapper });

    await userEvent.click(
      await screen.findByRole("button", { name: /replenish all/i }),
    );
    expect(screen.getByTestId("replenish-open")).toBeInTheDocument();
    expect(shoppingListPosts).toBe(0);
    await settle();
  });

  it("gives the journal the full width when shopping lists are off", async () => {
    serve({ low: [record("peas", "Frozen peas", "freezer")] });
    render(<InventoryDashboard />, { wrapper });

    const journal = await screen.findByRole("heading", {
      name: "Recent moves",
    });
    await settle();
    expect(screen.queryByText("Shopping list")).toBeNull();
    // Nothing to put the suggestions into, so nothing offers them.
    expect(screen.queryByRole("button", { name: /replenish all/i })).toBeNull();
    const grid = journal.closest(".grid") as HTMLElement;
    expect(grid.className).not.toMatch(/lg:grid-cols/);
  });

  it("sits the shopping list beside the journal when the module is on", async () => {
    serve({ modules: ["core", "items", "locations", "shopping_lists"] });
    render(<InventoryDashboard />, { wrapper });

    expect(await screen.findByText("Shopping list")).toBeInTheDocument();
    const journal = screen.getByRole("heading", { name: "Recent moves" });
    expect((journal.closest(".grid") as HTMLElement).className).toMatch(
      /lg:grid-cols-\[7fr_5fr\]/,
    );
    await settle();
  });

  it("puts 'Add product' in the module header", async () => {
    serve();
    render(<InventoryDashboard />, { wrapper });
    await screen.findByRole("heading", { name: "All under control" });

    render(<MemoryRouter>{header.actions}</MemoryRouter>);
    expect(
      screen.getByRole("button", { name: "Add product" }),
    ).toBeInTheDocument();
    await settle();
  });
});
