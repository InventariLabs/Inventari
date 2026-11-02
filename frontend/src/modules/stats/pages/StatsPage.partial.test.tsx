import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import StatsPage from "./StatsPage";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { onePage } from "@/test/mocks/page";

/**
 * One failing request used to take the whole overview with it.
 *
 * The tab rendered only when both the overview *and* the cost analysis had
 * arrived, so a 500 on `/stats/cost-analysis` left a header, two tabs and
 * nothing else: no message, no retry, and no sign of the four sections that
 * had arrived. Three of the five queries defended themselves (`?? []`); the
 * fourth gated the render instead, and the page's only error branch knew
 * about the fifth.
 */

const OK = {
  "/api/v1/stats/overview": {
    total_items: 10,
    total_value: 30.0,
    expiring_soon: 2,
    expired: 1,
    currency: "PLN",
  },
  "/api/v1/stats/by-location": onePage([
    { location_name: "Fridge", items_count: 5, total_value: 50.0 },
  ]),
  "/api/v1/stats/by-category": onePage([
    { category_name: "Dairy", items_count: 3, total_value: 30.0 },
  ]),
  "/api/v1/stats/expiry-forecast": [],
  "/api/v1/stats/cost-analysis": {
    total_spent: 500,
    total_wasted: 50,
    waste_event_rate: 10,
    savings_opportunities: [],
  },
} as const;

/** Every stats query answers, except the ones named. */
const allButFailing = (...failing: (keyof typeof OK)[]) =>
  Object.entries(OK).map(([path, body]) =>
    http.get(path, () =>
      failing.includes(path as keyof typeof OK)
        ? new HttpResponse(null, { status: 500 })
        : HttpResponse.json(body),
    ),
  );

const renderPage = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
      <QueryClientProvider client={queryClient}>
        <ModulesProvider>
          <MemoryRouter initialEntries={["/inventory/stats"]}>
            <StatsPage />
          </MemoryRouter>
        </ModulesProvider>
      </QueryClientProvider>
    </PageHeaderContext.Provider>,
  );
};

/** The health card is up: its toggle is the last thing the tab renders. */
const settled = () => screen.findByText("Show detailed stats");

const openDetails = async () => {
  await userEvent.click(await settled());
};

describe("the overview tab when one of its queries fails", () => {
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
      // The health card's count, from the one endpoint both screens read.
      // Without it the item-detail catch-all answers and the card would
      // count a record's fields.
      http.get("/api/v1/items/attention-counts", () =>
        HttpResponse.json({
          expired: 1,
          expiring_soon: 2,
          low_stock: 4,
          records: 7,
        }),
      ),
    );
  });

  it("still shows what did arrive when the cost analysis fails", async () => {
    server.use(...allButFailing("/api/v1/stats/cost-analysis"));

    renderPage();

    expect(await settled()).toBeInTheDocument();
    expect(await screen.findByText("PLN 30.00")).toBeInTheDocument();
  });

  it("names the cost analysis and offers to ask again", async () => {
    server.use(...allButFailing("/api/v1/stats/cost-analysis"));

    renderPage();
    await openDetails();

    expect(
      await screen.findByText("Failed to load the cost analysis"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it("asks again for the section that failed, and shows it once it answers", async () => {
    // A retry button that re-ran the wrong query, or none, would leave the
    // reader with a failure notice that no press can clear.
    let asked = 0;
    let failing = true;
    // The first handler named wins, so the flaky one goes first.
    server.use(
      http.get("/api/v1/stats/cost-analysis", () => {
        asked += 1;
        return failing
          ? new HttpResponse(null, { status: 500 })
          : HttpResponse.json(OK["/api/v1/stats/cost-analysis"]);
      }),
      ...allButFailing(),
    );

    renderPage();
    await openDetails();
    const notice = (
      await screen.findByText("Failed to load the cost analysis")
    ).closest('[role="alert"]') as HTMLElement;
    const before = asked;

    failing = false;
    await userEvent.click(
      within(notice).getByRole("button", { name: /try again/i }),
    );

    await waitFor(() => expect(asked).toBeGreaterThan(before));
    await waitFor(() =>
      expect(
        screen.queryByText("Failed to load the cost analysis"),
      ).not.toBeInTheDocument(),
    );
  });

  it("names the distribution by category, and keeps the other sections", async () => {
    server.use(...allButFailing("/api/v1/stats/by-category"));

    renderPage();
    await openDetails();

    expect(
      await screen.findByText("Failed to load the distribution by category"),
    ).toBeInTheDocument();
    // The storage half of the same grid arrived and is on the page.
    expect(screen.getByText("Fridge")).toBeInTheDocument();
  });

  it("says how many records the value could not count", async () => {
    // The count travelled from the domain layer to the response model and
    // was cut off there: the tile could only say "$0.00 across all items"
    // over a warehouse it had, correctly, refused to add up.
    server.use(
      http.get("/api/v1/stats/overview", () =>
        HttpResponse.json({
          ...OK["/api/v1/stats/overview"],
          total_value: 0,
          value_source: "purchase_price",
          value_scope: "locations",
          excluded_other_currency_count: 60,
        }),
      ),
    );

    renderPage();

    expect(await settled()).toBeInTheDocument();
    expect(
      screen.getByText(
        "60 products are priced in another currency and are not counted here.",
      ),
    ).toBeInTheDocument();
  });

  it("says nothing when every query answers", async () => {
    server.use(...allButFailing());

    renderPage();
    await openDetails();

    expect(screen.getByText("Fridge")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
