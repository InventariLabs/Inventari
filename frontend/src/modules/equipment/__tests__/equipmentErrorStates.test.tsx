import React from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { withModules } from "@/test/moduleList";
import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";

import AssetListPage from "../pages/AssetListPage";
import MyAssetsPage from "../pages/MyAssetsPage";
import AuditCampaignsPage from "../pages/AuditCampaignsPage";
import EquipmentCategoriesPage from "../pages/EquipmentCategoriesPage";
import EquipmentLocationsPage from "../pages/EquipmentLocationsPage";
import TemplatesPage from "../pages/TemplatesPage";
import EquipmentDashboardPage from "../pages/EquipmentDashboardPage";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

/**
 * "Nothing here yet" is a claim about the data, and a failed request cannot
 * make it.
 *
 * Every one of these screens destructured `data: x = []` and never looked at
 * `isError`, so the default empty array carried the failure straight into the
 * empty state. The reader was told there were no assets while sixty-one sat in
 * the register, no categories while eight did, no locations while thirty-seven
 * did — and categories and locations are dictionaries the whole register reads,
 * so the duplicate the reader then creates spreads past this module.
 */

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

function renderAt(path: string, element: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter initialEntries={[path]}>
          <PageHeaderHost>
            <Routes>
              <Route path={path} element={element} />
            </Routes>
          </PageHeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
}

const ACCOUNT = [
  "equipment:read",
  "equipment:write",
  "items:read",
  "items:write",
  "categories:read",
  "categories:write",
  "locations:read",
  "locations:write",
];

const fails = (path: string) =>
  http.get(path, () => new HttpResponse(null, { status: 500 }));

beforeEach(() => {
  server.resetHandlers();
  withModules("equipment");
  server.use(
    http.get("/api/v1/equipment/assets", () =>
      HttpResponse.json({ items: [], total: 0, offset: 0, limit: 50 }),
    ),
    http.get("/api/v1/items/archived", () =>
      HttpResponse.json({ items: [], total: 0, offset: 0, limit: 50 }),
    ),
    http.get("/api/v1/categories", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/equipment/models", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/equipment/templates", () => HttpResponse.json([])),
  );
  signInWith(ACCOUNT);
});

afterEach(() => {
  signOut();
});

/** The retry button is the part the reader acts on; assert on that. */
async function expectFailureShown() {
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(
    await screen.findByRole("button", { name: /try again|retry/i }),
  ).toBeInTheDocument();
}

describe("Equipment — a failed list is a failure, not an empty list", () => {
  it("says the asset list could not be read, instead of offering onboarding", async () => {
    server.use(fails("/api/v1/equipment/assets"));
    renderAt("/equipment/assets", <AssetListPage />);

    await expectFailureShown();
    expect(
      screen.queryByRole("link", { name: /add your first asset/i }),
    ).not.toBeInTheDocument();
  });

  it("still shows onboarding when the list is genuinely empty", async () => {
    renderAt("/equipment/assets", <AssetListPage />);

    expect(
      await screen.findByRole("link", { name: /add your first asset/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("says the assets assigned to me could not be read", async () => {
    server.use(fails("/api/v1/equipment/my-assets"));
    renderAt("/equipment/my", <MyAssetsPage />);

    await expectFailureShown();
    expect(
      screen.queryByText(/no assets assigned to you/i),
    ).not.toBeInTheDocument();
  });

  it("says the campaigns could not be read", async () => {
    server.use(fails("/api/v1/equipment/campaigns"));
    renderAt("/equipment/campaigns", <AuditCampaignsPage />);

    await expectFailureShown();
    expect(
      screen.queryByText(/no audit campaigns yet/i),
    ).not.toBeInTheDocument();
  });

  it("still shows the campaign empty state when there are none", async () => {
    server.use(
      http.get("/api/v1/equipment/campaigns", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    renderAt("/equipment/campaigns", <AuditCampaignsPage />);

    expect(await screen.findByText(/no attestations yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("says the equipment categories could not be read", async () => {
    server.use(fails("/api/v1/categories"));
    renderAt("/equipment/categories", <EquipmentCategoriesPage />);

    await expectFailureShown();
    expect(
      screen.queryByText(/no equipment categories yet/i),
    ).not.toBeInTheDocument();
  });

  it("says the locations could not be read", async () => {
    server.use(fails("/api/v1/locations"));
    renderAt("/equipment/locations", <EquipmentLocationsPage />);

    await expectFailureShown();
    expect(screen.queryByText(/no locations yet/i)).not.toBeInTheDocument();
  });

  it("does not promise the built-in template will be used when it cannot read the templates", async () => {
    server.use(fails("/api/v1/equipment/templates"));
    renderAt("/equipment/templates", <TemplatesPage />);

    await expectFailureShown();
    expect(
      screen.queryByText(/no custom templates yet/i),
    ).not.toBeInTheDocument();
  });

  it("puts an error where the dashboard counters were, instead of dropping them", async () => {
    server.use(fails("/api/v1/equipment/dashboard"));
    renderAt("/equipment", <EquipmentDashboardPage />);

    await expectFailureShown();
  });
});
