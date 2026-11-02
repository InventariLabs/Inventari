import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";

import AssetListPage from "../pages/AssetListPage";
import EquipmentCategoriesPage from "../pages/EquipmentCategoriesPage";
import AddEquipmentPage from "../pages/AddEquipmentPage";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

/**
 * A read-only account is shown what it may do, before it clicks.
 *
 * The backend refused this account every write it attempted — correctly, with
 * a translated message. The screens went on offering the whole write surface
 * anyway: fourteen check-in buttons on the dashboard, Export/Import/Add and
 * eight bulk actions on the list, Edit and Delete beside every category, and
 * every modal opening and filling to the end. The refusal arrived after the
 * submit. The worst of them sent e-mail to every holder of a piece of
 * equipment; the reader had already chosen the recipients.
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

function renderAt(path: string, route: string, element: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter initialEntries={[path]}>
          <PageHeaderHost>
            <Routes>
              <Route path={route} element={element} />
            </Routes>
          </PageHeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
}

const READER = ["equipment:read", "items:read"];
const WRITER = ["equipment:read", "equipment:write", "items:read"];

beforeEach(() => {
  server.resetHandlers();
  server.use(
    http.get("/api/v1/items", () =>
      HttpResponse.json({ items: [], total: 0, offset: 0, limit: 50 }),
    ),
    http.get("/api/v1/categories", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/equipment/models", () => HttpResponse.json([])),
  );
});

afterEach(() => {
  signOut();
});

describe("Equipment — a reader is not offered the write surface", () => {
  it("hides Import and Add on the asset list, and says why", async () => {
    signInWith(READER);
    renderAt("/equipment", "/equipment", <AssetListPage />);

    expect(
      await screen.findByText(/you can view this, not change it/i),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: /import/i }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("link", { name: /add asset/i }),
    ).not.toBeInTheDocument();
  });

  it("still offers them to an account that may write, and says nothing", async () => {
    signInWith(WRITER);
    renderAt("/equipment", "/equipment", <AssetListPage />);

    // The header's Import and the empty state's "Import from file" tile.
    expect(
      await screen.findAllByRole("button", { name: /import/i }),
    ).toHaveLength(2);
    expect(
      screen.queryByText(/you can view this, not change it/i),
    ).not.toBeInTheDocument();
  });

  it("hides the category actions from a reader", async () => {
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json(
          onePage([
            {
              id: "cat-1",
              name: "Laptops",
              context_tag: "equipment",
              icon: null,
              color: null,
              field_definitions: [],
            },
          ]),
        ),
      ),
    );
    signInWith(READER);
    renderAt(
      "/equipment/categories",
      "/equipment/categories",
      <EquipmentCategoriesPage />,
    );

    // The list renders two branches of the same record — the desktop table
    // and the phone card — so the name is on screen twice; what this test
    // pins is that neither of them offers a delete.
    expect((await screen.findAllByText("Laptops")).length).toBeGreaterThan(0);
    expect(
      screen.queryByRole("button", { name: /delete/i }),
    ).not.toBeInTheDocument();
  });

  it("refuses the add form reached straight by its address", async () => {
    signInWith(READER);
    renderAt("/equipment/add", "/equipment/add", <AddEquipmentPage />);

    expect(
      await screen.findByText(/you can view this, not change it/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /save asset/i }),
    ).not.toBeInTheDocument();
  });
});
