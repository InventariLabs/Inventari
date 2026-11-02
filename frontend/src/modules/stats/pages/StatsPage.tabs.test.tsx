import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import StatsPage from "./StatsPage";
import { server } from "@/test/mocks/server";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { onePage } from "@/test/mocks/page";

/**
 * The reconciliation and analytics tabs each have a request of their own and
 * a notice with a retry of their own. A notice whose button asks for the
 * wrong thing, or for nothing, leaves the tab on its failure for good.
 */

const renderAt = (path: string) => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
      <QueryClientProvider client={queryClient}>
        <ModulesProvider>
          <MemoryRouter initialEntries={[path]}>
            <StatsPage />
          </MemoryRouter>
        </ModulesProvider>
      </QueryClientProvider>
    </PageHeaderContext.Provider>,
  );
};

/** A path that answers 500 until `heal` is called, and counts the asks. */
const flaky = (path: string, body: Record<string, unknown>) => {
  const state = { asked: 0, failing: true };
  server.use(
    http.get(path, () => {
      state.asked += 1;
      return state.failing
        ? new HttpResponse(null, { status: 500 })
        : HttpResponse.json(body);
    }),
  );
  return state;
};

const noticeFor = async (message: string) =>
  (await screen.findByText(message)).closest('[role="alert"]') as HTMLElement;

describe("the stats tabs with a request of their own", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/modules/my", () =>
        HttpResponse.json(["core", "stats", "items", "locations"]),
      ),
      http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
      http.get("/api/v1/locations/tree", () => HttpResponse.json([])),
      http.get("/api/v1/location-types", () => HttpResponse.json(onePage([]))),
      http.get("/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "1", currency: "PLN", name: "Test Org" }),
      ),
      http.get("/api/v1/stats/config", () =>
        HttpResponse.json({ enable_analytics: true }),
      ),
      http.get("/api/v1/items/attention-counts", () =>
        HttpResponse.json({
          expired: 0,
          expiring_soon: 0,
          low_stock: 0,
          records: 0,
        }),
      ),
      http.get("/api/v1/stats/overview", () =>
        HttpResponse.json({
          total_items: 10,
          total_value: 30,
          expiring_soon: 0,
          expired: 0,
          currency: "PLN",
        }),
      ),
      http.get("/api/v1/stats/by-location", () =>
        HttpResponse.json(onePage([])),
      ),
      http.get("/api/v1/stats/by-category", () =>
        HttpResponse.json(onePage([])),
      ),
      http.get("/api/v1/stats/expiry-forecast", () => HttpResponse.json([])),
      http.get("/api/v1/stats/cost-analysis", () =>
        HttpResponse.json({
          total_spent: 0,
          total_wasted: 0,
          savings_opportunities: [],
        }),
      ),
    );
  });

  it("reads the reconciliation report on its tab and draws both pairs", async () => {
    server.use(
      http.get("/api/v1/stats/reconciliation", () =>
        HttpResponse.json({
          items_scanned: 11,
          quant_move_drift_count: 7,
          quant_move_drift_total: "12.000",
          layer_quant_drift_count: 1,
          layer_quant_drift_total: "4.000",
        }),
      ),
    );

    renderAt("/inventory/stats/reconciliation");

    expect(await screen.findByText("12")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(3);
  });

  it("asks for the reconciliation again from its notice", async () => {
    const reconciliation = flaky("/api/v1/stats/reconciliation", {
      items_scanned: 3,
      quant_move_drift_count: 0,
      quant_move_drift_total: "0.000",
      layer_quant_drift_count: 0,
      layer_quant_drift_total: "0.000",
    });
    renderAt("/inventory/stats/reconciliation");
    const notice = await noticeFor("Failed to load the stock reconciliation");
    const before = reconciliation.asked;

    reconciliation.failing = false;
    await userEvent.click(
      within(notice).getByRole("button", { name: /try again/i }),
    );

    await waitFor(() => expect(reconciliation.asked).toBeGreaterThan(before));
    await waitFor(() =>
      expect(
        screen.queryByText("Failed to load the stock reconciliation"),
      ).not.toBeInTheDocument(),
    );
  });

  it("asks again for the rotation analysis and for the alerts, each from its own notice", async () => {
    const rotation = flaky("/api/v1/stats/rotation-analysis", {});
    const alerts = flaky("/api/v1/stats/smart-alerts", {});
    server.use(
      http.get(
        "/api/v1/stats/expense-forecast",
        () => new HttpResponse(null, { status: 500 }),
      ),
      http.get(
        "/api/v1/stats/purchase-patterns",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    renderAt("/inventory/stats/analytics");

    const rotationNotice = await noticeFor("Failed to load rotation analysis");
    const alertsNotice = await noticeFor("Failed to load alerts");
    const rotationBefore = rotation.asked;
    const alertsBefore = alerts.asked;

    await userEvent.click(
      within(rotationNotice).getByRole("button", { name: /try again/i }),
    );
    await waitFor(() => expect(rotation.asked).toBeGreaterThan(rotationBefore));
    // The other notice's request was not touched by that press.
    expect(alerts.asked).toBe(alertsBefore);

    await userEvent.click(
      within(alertsNotice).getByRole("button", { name: /try again/i }),
    );
    await waitFor(() => expect(alerts.asked).toBeGreaterThan(alertsBefore));
  });
});
