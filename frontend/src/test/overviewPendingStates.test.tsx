import "@/modules/shopping_lists/module";
import "@/modules/nutrition/module";
import "@/modules/announcements/module";
import React from "react";
import { act, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { delay, http, HttpResponse } from "msw";
import i18next from "i18next";
import { server } from "@/test/mocks/server";
import { signInWith } from "@/test/auth";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { useAuthStore } from "@/store/authStore";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import InventoryDashboard from "@/modules/inventory/pages/InventoryDashboard";
import EquipmentDashboardPage from "@/modules/equipment/pages/EquipmentDashboardPage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

/**
 * What a module's overview may not say while the answer is still on its way.
 *
 * An empty state ("No locations yet"), a quiet line ("Fleet under control")
 * and a counted heading ("8 assets need attention") are all claims about the
 * organization's data, so none of them is drawn before the data has arrived.
 * Each overview is mounted with its requests held open (and, in the second scenario, with the
 * module list itself still pending, which keeps every module query disabled)
 * and the page must not state any of these.
 *
 * Every card of an overview is in the set below: a new card that draws an
 * empty state or a count from a query belongs in `claims`.
 */

const t = (key: string, options?: Record<string, unknown>) =>
  i18next.t(key, options) as string;

/** The sentences a card may draw only from an answer, per overview. */
const claims = {
  inventory: [
    // My locations: the empty state with its call to action.
    () => t("locations:required.title"),
    () => t("locations:required.action"),
    // Needs attention: the all-clear line.
    () => t("common:dashboard.attention.quiet"),
    // Recent moves: the empty journal.
    () => t("common:dashboard.journal.empty"),
  ],
  equipment: [
    // Needs attention: the all-clear line.
    () => t("equipment:dashboard.attention.quiet"),
    // Fleet by category: the empty fleet.
    () => t("equipment:dashboard.fleet.empty"),
    // Recent check-outs: the empty journal.
    () => t("equipment:assignments.no_active"),
  ],
};

/** A count of what needs attention, in any number. */
const ATTENTION_HEADING = /\d+ (records? needs?|assets? needs?) attention/;

function mount(page: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ModulesProvider>
        <MemoryRouter>
          <PageHeaderContext.Provider
            value={{ data: {}, setHeader: () => undefined }}
          >
            {page}
          </PageHeaderContext.Provider>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
}

/** Every request waits: nothing has answered yet. */
const holdEverything = () =>
  http.all("*/api/*", async () => {
    await delay("infinite");
    return HttpResponse.json({});
  });

async function flush() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 50));
  });
}

function expectNoClaims(list: ReadonlyArray<() => string>) {
  for (const claim of list) {
    expect(screen.queryByText(claim())).not.toBeInTheDocument();
  }
  expect(screen.queryByText(ATTENTION_HEADING)).not.toBeInTheDocument();
}

describe("overview cards while their queries are pending", () => {
  afterEach(() => {
    act(() => {
      useAuthStore.setState({ user: null, isAuthenticated: false });
    });
  });

  const overviews = [
    { name: "inventory", page: <InventoryDashboard />, modules: [] },
    {
      name: "equipment",
      page: <EquipmentDashboardPage />,
      modules: ["equipment"],
    },
  ] as const;

  for (const { name, page, modules } of overviews) {
    it(`${name}: the organization's data has not arrived`, async () => {
      signInWith([], { role: "admin" });
      server.use(
        http.get("/api/v1/modules/my", () =>
          HttpResponse.json(["core", "items", "locations", ...modules]),
        ),
        holdEverything(),
      );
      mount(page);
      await flush();
      expectNoClaims(claims[name]);
    });

    it(`${name}: the module list has not arrived either`, async () => {
      signInWith([], { role: "admin" });
      server.use(
        http.get("/api/v1/modules/my", async () => {
          await delay("infinite");
          return HttpResponse.json([]);
        }),
        holdEverything(),
      );
      mount(page);
      await flush();
      expectNoClaims(claims[name]);
    });
  }

  it("equipment: the heading waits for every list it adds up", async () => {
    signInWith([], { role: "admin" });
    const ending = ["a", "b", "c", "d"].map((id) => ({
      item_id: id,
      item_name: `Laptop ${id}`,
      warranty_until: new Date(Date.now() + 10 * 86_400_000)
        .toISOString()
        .slice(0, 10),
      days_remaining: 10,
      serial_number: null,
      assigned_to: null,
    }));
    server.use(
      http.get("/api/v1/modules/my", () =>
        HttpResponse.json(["core", "items", "locations", "equipment"]),
      ),
      http.get("/api/v1/equipment/dashboard", () =>
        HttpResponse.json({
          total_assets: 9,
          active_assignments: 0,
          in_maintenance: 1,
          retired: 0,
          by_status: {},
          by_category: [],
          recent_activity: [],
          warranty_alerts: ending,
          expired_warranty_alerts: [],
        }),
      ),
      http.get("/api/v1/equipment/assignments/overdue", () =>
        HttpResponse.json({
          items: [],
          total: 0,
          limit: 50,
          offset: 0,
          has_more: false,
        }),
      ),
      // The fleet is the slow one: the maintenance row comes from it.
      http.get("/api/v1/equipment/assets", async () => {
        await delay("infinite");
        return HttpResponse.json({});
      }),
      holdEverything(),
    );
    mount(<EquipmentDashboardPage />);
    // The totals strip draws once the dashboard has answered: from here on
    // the four warranties are known and the fleet still is not.
    await screen.findByText(t("equipment:dashboard.in_maintenance"));
    await flush();
    expect(screen.queryByText(ATTENTION_HEADING)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /show all/i })).toBeNull();
  });
});
