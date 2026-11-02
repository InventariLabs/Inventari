import { render, screen } from "@testing-library/react";
import { describe, it, expect, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import StatsPage from "./StatsPage";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { onePage } from "@/test/mocks/page";

const fail = (path: string) =>
  http.get(path, () => new HttpResponse(null, { status: 500 }));

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

/**
 * The tabs over one prefix used to disagree about what a failed request
 * looks like: Analytics said so, Overview said so, and Inventory sat on a
 * spinner with no message, no retry and nothing to read. The inventory tab
 * is gone; the remaining two must keep reporting failure.
 */
describe("the statistics tabs when the numbers do not arrive", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/modules/my", () =>
        HttpResponse.json(["core", "stats", "items", "locations"]),
      ),
      fail("/api/v1/stats/overview"),
      fail("/api/v1/stats/by-location"),
      fail("/api/v1/stats/by-category"),
      fail("/api/v1/stats/expiry-forecast"),
      fail("/api/v1/stats/cost-analysis"),
      fail("/api/v1/stats/rotation-analysis"),
      fail("/api/v1/stats/smart-alerts"),
      fail("/api/v1/stats/expense-forecast"),
      fail("/api/v1/stats/purchase-patterns"),
      http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
      http.get("/api/v1/locations/tree", () => HttpResponse.json([])),
      http.get("/api/v1/location-types", () => HttpResponse.json(onePage([]))),
      http.get("/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "1", currency: "PLN", name: "Test Org" }),
      ),
    );
  });

  it("says the same thing on the analytics tab", async () => {
    renderAt("/inventory/stats/analytics");

    expect(await screen.findByText("An error occurred")).toBeInTheDocument();
    expect(document.querySelector(".animate-spin")).toBeNull();
  });

  it("says the same thing on the overview tab", async () => {
    renderAt("/inventory/stats/overview");

    expect(await screen.findByText("An error occurred")).toBeInTheDocument();
    expect(document.querySelector(".animate-spin")).toBeNull();
  });
});
