import React from "react";
import { act, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import EquipmentDashboardPage from "../pages/EquipmentDashboardPage";
import { server } from "@/test/mocks/server";
import { useAuthStore } from "@/store/authStore";
import type { User } from "@/types";
import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

let canWrite = true;
vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => canWrite,
}));

/** Mirrors ModuleShell: keeps header data in state and renders the actions. */
function PageHeaderHost({ children }: { children: React.ReactNode }) {
  const [data, setData] = React.useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      {data.actions ? (
        <div data-testid="header-actions">{data.actions}</div>
      ) : null}
      {children}
    </PageHeaderContext.Provider>
  );
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter>
          <PageHeaderHost>
            <EquipmentDashboardPage />
          </PageHeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
}

const laptops = { id: "cat-laptops", name: "Laptops", code: null, icon: null };
const printers = {
  id: "cat-printers",
  name: "Printers",
  code: null,
  icon: null,
};

function asset(
  id: string,
  category: typeof laptops | null,
  opts: { status?: string; holder?: string; serial?: string } = {},
) {
  return {
    id,
    name: `Asset ${id}`,
    category_id: category?.id ?? null,
    category: category ?? undefined,
    serial_number: opts.serial ?? null,
    metadata: { equipment: { equipment_status: opts.status ?? "AVAILABLE" } },
    location_name: "IT room",
    holder_name: opts.holder ?? null,
    holder_kind: opts.holder ? "person" : null,
  };
}

function warranty(itemId: string, name: string, days: number, extra = {}) {
  return {
    item_id: itemId,
    item_name: name,
    warranty_until: "2026-10-04",
    days_remaining: days,
    serial_number: null,
    assigned_to: null,
    ...extra,
  };
}

function assignment(id: string, serial: string | null, extra = {}) {
  return {
    id: `asg-${id}`,
    item_id: `item-${id}`,
    item_name: "OptiPlex 7010",
    item_serial: serial,
    item_asset_tag: null,
    assignee_partner_id: null,
    partner_name: null,
    assigned_to_name: "John Doe",
    holder_name: "John Doe",
    holder_kind: "person",
    assigned_to_email: null,
    checked_out_at: "2026-09-20T08:00:00Z",
    expected_return_at: null,
    checked_in_at: null,
    checked_out_by: "user-1",
    checked_in_by: null,
    checkout_notes: null,
    checkin_notes: null,
    checkin_condition: null,
    created_at: "2026-09-20T08:00:00Z",
    ...extra,
  };
}

interface Served {
  assets?: object[];
  ending?: object[];
  expired?: object[];
  overdue?: object[];
  assignments?: object[];
  totals?: { total_assets: number; retired: number; active: number };
  valued?: number;
}

function serve({
  assets = [],
  ending = [],
  expired = [],
  overdue = [],
  assignments = [],
  totals = { total_assets: assets.length, retired: 0, active: 0 },
  valued = 0,
}: Served = {}) {
  server.use(
    http.get("/api/v1/equipment/dashboard", () =>
      HttpResponse.json({
        total_assets: totals.total_assets,
        active_assignments: totals.active,
        in_maintenance: 0,
        retired: totals.retired,
        by_status: {},
        by_category: [],
        recent_activity: [],
        warranty_alerts: ending,
        expired_warranty_alerts: expired,
      }),
    ),
    http.get("/api/v1/equipment/assignments/overdue", () =>
      HttpResponse.json({
        items: overdue,
        total: overdue.length,
        limit: 20,
        offset: 0,
        has_more: false,
      }),
    ),
    http.get("/api/v1/equipment/assignments", () =>
      HttpResponse.json({
        items: assignments,
        total: assignments.length,
        limit: 50,
        offset: 0,
        has_more: false,
      }),
    ),
    http.get("/api/v1/equipment/assets", () =>
      HttpResponse.json({
        items: assets,
        total: assets.length,
        limit: 200,
        offset: 0,
        has_more: false,
      }),
    ),
    http.get("/api/v1/equipment/valuation", () =>
      HttpResponse.json({
        total_purchase_value: 1000 * valued,
        total_book_value: 800 * valued,
        total_depreciation: 200 * valued,
        by_category: [],
        asset_count: valued,
        depreciable_count: valued,
        excluded_count: 0,
      }),
    ),
  );
}

async function settle() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 50));
  });
}

/**
 * Only the role matters here. Staying signed out of the modules context
 * (isAuthenticated false) keeps every module enabled without a /modules mock.
 */
function actAs(role: string) {
  useAuthStore.setState({
    user: { id: "u", role, is_superuser: false } as User,
    isAuthenticated: false,
  });
}

describe("the equipment overview", () => {
  beforeEach(() => {
    canWrite = true;
    actAs("admin");
  });

  it("leads with what needs attention, most urgent first, each row to its asset", async () => {
    serve({
      assets: [
        asset("hp", printers, { status: "MAINTENANCE", serial: "SN-9001" }),
      ],
      ending: [
        warranty("dell", "Dell U2723QE", 12, { assigned_to: "M. Zielińska" }),
      ],
      expired: [warranty("old", "Old Server", -300)],
      overdue: [
        {
          assignment_id: "asg-mac",
          item_id: "mac",
          item_name: "MacBook Pro 14",
          item_barcode: null,
          item_serial: "C02XYZ",
          item_asset_tag: null,
          holder_name: "K. Nowak",
          holder_kind: "person",
          assigned_to_email: null,
          checked_out_at: "2026-09-01T08:00:00Z",
          expected_return_at: "2026-09-19T08:00:00Z",
          days_overdue: 3,
        },
      ],
      totals: { total_assets: 47, retired: 0, active: 25 },
    });
    renderPage();

    const heading = await screen.findByRole("heading", {
      name: "4 assets need attention",
    });
    expect(screen.getByText("47 assets · 25 checked out")).toBeInTheDocument();

    const card = heading.closest('[class*="bg-amber-50"]') as HTMLElement;
    const rows = within(card).getAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("return overdue by 3 days"),
      expect.stringContaining("warranty ends in 12 days"),
      expect.stringContaining("in maintenance"),
      expect.stringContaining("warranty ended"),
    ]);
    expect(
      within(card).getByRole("link", { name: "MacBook Pro 14 · C02XYZ" }),
    ).toHaveAttribute("href", "/equipment/mac");
    expect(
      within(card).getByRole("link", { name: "Asset hp · SN-9001" }),
    ).toHaveAttribute("href", "/equipment/hp");
    expect(rows[1]).toHaveTextContent("M. Zielińska");
    expect(screen.queryByText("Fleet under control")).toBeNull();
    await settle();
  });

  it("reads a warranty that ends today as today, and one day in the singular", async () => {
    serve({
      ending: [
        warranty("dock", "Docking Station", 0),
        warranty("hub", "USB Hub", 1),
      ],
      totals: { total_assets: 2, retired: 0, active: 0 },
    });
    renderPage();

    expect(await screen.findByText("warranty ends today")).toBeInTheDocument();
    expect(screen.getByText("warranty ends in 1 day")).toBeInTheDocument();
    await settle();
  });

  it("leaves a retired asset's lapsed warranty out of it", async () => {
    // An old fleet has many of these, and none of them is work for today:
    // counted, they would keep the card from ever going quiet.
    serve({
      assets: [asset("old", laptops, { status: "RETIRED" })],
      expired: [warranty("old", "Old Server", -300)],
    });
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "Fleet under control" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Old Server")).toBeNull();
    await settle();
  });

  it("folds to one line on a quiet day, still saying what the fleet holds", async () => {
    serve({
      assets: [asset("a", laptops), asset("b", laptops, { holder: "Ann" })],
      totals: { total_assets: 3, retired: 1, active: 1 },
    });
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "Fleet under control" }),
    ).toBeInTheDocument();
    // Retired assets are out of the fleet in the sentence as in the bars.
    expect(screen.getByText("2 assets · 1 checked out")).toBeInTheDocument();
    await settle();
  });

  it("does not call the day quiet before the answers are in", async () => {
    serve({ assets: [asset("l1", laptops)] });
    let answer: () => void = () => {};
    const held = new Promise<void>((resolve) => (answer = resolve));
    server.use(
      http.get("/api/v1/equipment/assignments/overdue", async () => {
        await held;
        return HttpResponse.json({ items: [], total: 0 });
      }),
    );
    renderPage();

    await settle();
    expect(screen.queryByText("Fleet under control")).toBeNull();

    answer();
    expect(
      await screen.findByRole("heading", { name: "Fleet under control" }),
    ).toBeInTheDocument();
    await settle();
  });

  it("draws the fleet by category, each bar said in words and each name a filter", async () => {
    serve({
      assets: [
        asset("l1", laptops, { holder: "Ann" }),
        asset("l2", laptops),
        asset("l3", laptops),
        asset("p1", printers, { status: "MAINTENANCE" }),
        asset("gone", laptops, { status: "RETIRED" }),
        asset("loose", null),
      ],
      // l1 is held: it counts as checked out, and its warranty is the
      // attention card's business, not the bar's.
      ending: [warranty("l1", "Asset l1", 9), warranty("l2", "Asset l2", 10)],
    });
    renderPage();

    expect(
      await screen.findByRole("img", {
        name: "3 assets: 1 checked out, 1 available, warranty ending",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "1 asset: 1 in maintenance" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Laptops" })).toHaveAttribute(
      "href",
      "/equipment/assets?category=cat-laptops",
    );
    expect(screen.getByText("No category")).toBeInTheDocument();
    await settle();
  });

  it("lists the latest check-outs by unit, and sends the rest to the filtered asset list", async () => {
    serve({
      assignments: [
        assignment("a", "SN-0001"),
        assignment("b", null, { item_asset_tag: "TAG-77" }),
        ...["c", "d", "e", "f"].map((id) => assignment(id, `SN-${id}`)),
      ],
    });
    renderPage();

    expect(await screen.findByText("SN-0001")).toBeInTheDocument();
    expect(screen.getByText("TAG-77")).toBeInTheDocument();
    expect(screen.getAllByText("checked out to John Doe")).toHaveLength(5);
    expect(screen.queryByText("SN-f")).toBeNull();
    expect(
      screen.getByRole("link", { name: /All checked out/ }),
    ).toHaveAttribute("href", "/equipment/assets?checked_out=1");
    await settle();
  });

  it("gives the check-outs the full width when there is nothing to value", async () => {
    serve({ assignments: [assignment("a", "SN-0001")], valued: 0 });
    const { container } = renderPage();
    await screen.findByText("SN-0001");
    await settle();
    const grid = container.querySelector(".grid.gap-6") as HTMLElement;
    expect(grid.className).not.toContain("lg:grid-cols");
  });

  it("stacks on a track that can shrink below lg, not an auto one", async () => {
    serve({ assignments: [assignment("a", "SN-0001")], valued: 3 });
    const { container } = renderPage();
    await screen.findByText("SN-0001");
    await settle();
    const grid = container.querySelector(".grid.gap-6") as HTMLElement;
    // Below lg the single column is implicit `auto`, which sizes to the
    // valuation table's min-content and pushes both cards past a phone
    // screen (the root's overflow-x-hidden then clips them unreachable).
    // Only a zero-min track lets the cards take the viewport's width.
    expect(grid.className).toContain("grid-cols-[minmax(0,1fr)]");
  });

  it("sits the valuation beside the check-outs when the fleet carries value", async () => {
    serve({ assignments: [assignment("a", "SN-0001")], valued: 3 });
    const { container } = renderPage();
    await screen.findByText("SN-0001");
    await screen.findByText(/Fleet Valuation/);
    const grid = container.querySelector(".grid.gap-6") as HTMLElement;
    expect(grid.className).toContain(
      "lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]",
    );
  });

  it("keeps the fleet's purchase prices from a plain member", async () => {
    // The member borrows and returns equipment; the organization's book
    // value is for those who run it. The request is not even made.
    actAs("user");
    serve({ assignments: [assignment("a", "SN-0001")], valued: 3 });
    const { container } = renderPage();
    await screen.findByText("SN-0001");
    await settle();
    expect(screen.queryByText(/Fleet Valuation/)).not.toBeInTheDocument();
    const grid = container.querySelector(".grid.gap-6") as HTMLElement;
    expect(grid.className).not.toContain("lg:grid-cols-");
  });

  it("shows the fleet totals on the equipment overview, not on stock", async () => {
    serve({ totals: { total_assets: 12, retired: 2, active: 4 } });
    renderPage();
    // These four numbers used to sit on the inventory overview, where a
    // stock reader met warranties and check-outs beside the stock.
    expect(await screen.findByText("In the fleet")).toBeInTheDocument();
    expect(screen.getByText("Retired")).toBeInTheDocument();
    await settle();
  });

  it("counts the fleet once: the sentence and the first tile agree", async () => {
    serve({ totals: { total_assets: 80, retired: 1, active: 4 } });
    renderPage();
    // Retired assets are out of the fleet in both places. The sentence said
    // 79 while the tile said 80 on the same screen.
    expect(await screen.findByText(/^79 assets/)).toBeInTheDocument();
    const tile = screen.getByText("In the fleet").previousElementSibling;
    expect(tile).toHaveTextContent("79");
    await settle();
  });

  it("claims no control over a fleet that has no assets yet", async () => {
    serve({ totals: { total_assets: 0, retired: 0, active: 0 } });
    renderPage();
    // "Fleet under control" over zero assets is a claim about nothing.
    expect(await screen.findByText("In the fleet")).toBeInTheDocument();
    expect(screen.queryByText("Fleet under control")).toBeNull();
    await settle();
  });

  it("names what its link opens: the whole asset list, and how long it is", async () => {
    serve({
      assets: [asset("hp", printers, { status: "MAINTENANCE", serial: "S1" })],
      totals: { total_assets: 1, retired: 0, active: 0 },
    });
    renderPage();
    const link = await screen.findByRole("link", { name: "All assets (1)" });
    expect(link).toHaveAttribute("href", "/equipment/assets");
    expect(
      screen.queryByRole("link", { name: "View all" }),
    ).not.toBeInTheDocument();
    await settle();
  });

  it("puts 'Add Asset' in the module header for those who may write", async () => {
    serve();
    renderPage();
    const actions = await screen.findByTestId("header-actions");
    expect(
      within(actions).getByRole("link", { name: /Add Asset/ }),
    ).toHaveAttribute("href", "/equipment/add");
    await settle();
  });

  it("offers no 'Add Asset' to a reader", async () => {
    canWrite = false;
    serve({ assets: [asset("l1", laptops)] });
    renderPage();
    await screen.findByRole("heading", { name: "Fleet under control" });
    expect(screen.queryByTestId("header-actions")).toBeNull();
  });
});
