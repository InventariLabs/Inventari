import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import SettingsMyModulesSection from "./SettingsMyModulesSection";
import { onePage } from "@/test/mocks/page";

const profiles = [
  {
    id: "equipment_wms",
    name: "Equipment & Warehouse",
    description: "Track IT assets and equipment.",
    default_modules: ["equipment"],
    seed_profile: "equipment_wms",
    icon: "Box",
  },
];

const organization = {
  id: "org-1",
  name: "Acme",
  timezone: "UTC",
  currency: "PLN",
  can_send_email: false,
  created_at: new Date().toISOString(),
  created_by: null,
  settings: null,
  active_profile_id: "equipment_wms",
  onboarding_completed: true,
};

function mockEndpoints() {
  server.use(
    http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
    http.get("*/api/v1/organizations/my", () =>
      HttpResponse.json(organization),
    ),
    http.get("*/api/v1/modules/my", () =>
      HttpResponse.json(["core", "items", "equipment"]),
    ),
    http.get("*/api/v1/modules/available", () =>
      HttpResponse.json(onePage([])),
    ),
    http.get("*/api/v1/modules/focus", () =>
      HttpResponse.json({ applied: false, focus_module: null }),
    ),
  );
}

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SettingsMyModulesSection />
        </MemoryRouter>
      </QueryClientProvider>
    </PageHeaderContext.Provider>,
  );
}

describe("SettingsMyModulesSection", () => {
  it("sets which modules are visible and which one is shown, on one screen", async () => {
    mockEndpoints();
    renderSection();

    // Module visibility: the module set a profile switches on.
    expect(
      await screen.findByRole("heading", { name: "Modules you see" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: "Equipment & Warehouse" }),
    ).toBeInTheDocument();

    // Focus: one toggle per module that can be shown on its own.
    expect(
      screen.getByRole("heading", { name: "Show just one module" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "Show only Equipment Tracking" }),
    ).toBeInTheDocument();
  });

  it("says it in plain words — never the old jargon", async () => {
    mockEndpoints();
    renderSection();
    await screen.findByRole("heading", { name: "Modules you see" });

    expect(document.body).not.toHaveTextContent(/work mode/i);
    expect(document.body).not.toHaveTextContent(/tryb pracy/i);
  });
});
