import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { withLanguage } from "@/test/mocks/i18n";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { EquipmentDashboardWidget } from "./EquipmentDashboardWidget";

/**
 * The tile names what it counts — warranties ending soon — and inflects it in
 * Polish for one ("1 gwarancja kończy się wkrótce"), a few ("3 gwarancje
 * kończą się wkrótce") and many ("5 gwarancji kończy się wkrótce"), in
 * lower case mid-sentence.
 */
const ALERT = {
  item_id: "item-1",
  item_name: "Dell Laptop",
  warranty_until: "2026-09-01",
  days_remaining: 17,
};

function renderWidget(alerts: number) {
  server.use(
    http.get("/api/v1/modules/my", () => HttpResponse.json(["equipment"])),
    http.get("/api/v1/equipment/dashboard", () =>
      HttpResponse.json({
        total_assets: 10,
        active_assignments: 2,
        in_maintenance: 1,
        retired: 0,
        by_status: {},
        by_category: [],
        recent_activity: [],
        warranty_alerts: Array.from({ length: alerts }, (_, i) => ({
          ...ALERT,
          item_id: `item-${i}`,
        })),
        expired_warranty_alerts: [],
      }),
    ),
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter>
          <EquipmentDashboardWidget />
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
}

describe("the dashboard tile's warranty counter", () => {
  it("inflects for one, for a few and for many, in Polish", async () => {
    await withLanguage("pl", async () => {
      renderWidget(1);
      expect(
        await screen.findByText("1 gwarancja kończy się wkrótce"),
      ).toBeInTheDocument();
    });

    await withLanguage("pl", async () => {
      renderWidget(3);
      expect(
        await screen.findByText("3 gwarancje kończą się wkrótce"),
      ).toBeInTheDocument();
    });

    await withLanguage("pl", async () => {
      renderWidget(5);
      expect(
        await screen.findByText("5 gwarancji kończy się wkrótce"),
      ).toBeInTheDocument();
    });
  });
});
