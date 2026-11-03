import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";

import DocumentsPage from "@/modules/warehouse/pages/DocumentsPage";
import PurchaseOrdersPage from "@/modules/purchase_orders/pages/PurchaseOrdersPage";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useModules: () => ({
    enabledModules: ["warehouse", "purchase_orders", "partners"],
    isModuleEnabled: () => true,
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

/**
 * The trade modules answer a reader the same way the equipment module does.
 *
 * The backend refused this account all sixteen writes the pass tried, each
 * with a translated message. The screens went on offering "New document",
 * "Add Rule", "Create Order", "Add rule", "Add price", "New correction",
 * "Receive stock", "Request Approval", "Save Profile", "Send to supplier" and
 * eight padlocks over the accounting periods — every one of them refused only
 * after the form had been filled in.
 */
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
      <MemoryRouter initialEntries={[path]}>
        <PageHeaderHost>
          <Routes>
            <Route path={route} element={element} />
          </Routes>
        </PageHeaderHost>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  server.resetHandlers();
  server.use(
    http.get("/api/v1/warehouse/documents", () =>
      HttpResponse.json({ items: [], total: 0, offset: 0, limit: 50 }),
    ),
    // The New document menu reads the organization's own type names.
    http.get("/api/v1/warehouse/profile", () =>
      HttpResponse.json({ type_labels: null }),
    ),
    http.get("/api/v1/purchase-orders", () =>
      HttpResponse.json({ items: [], total: 0, offset: 0, limit: 50 }),
    ),
    http.get("/api/v1/partners", () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
    http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
  );
});

afterEach(() => {
  signOut();
});

describe("Documents and purchase orders — a reader sees no write surface", () => {
  it("hides New document and says why", async () => {
    signInWith(["warehouse:read"]);
    renderAt("/warehouse", "/warehouse", <DocumentsPage />);

    expect(
      await screen.findByText(/you can view this, not change it/i),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByTestId("header-actions")).not.toBeInTheDocument(),
    );
  });

  it("offers New document to an account that may write", async () => {
    signInWith(["warehouse:read", "warehouse:write"]);
    renderAt("/warehouse", "/warehouse", <DocumentsPage />);

    expect(await screen.findByTestId("header-actions")).toBeInTheDocument();
    expect(
      screen.queryByText(/you can view this, not change it/i),
    ).not.toBeInTheDocument();
  });

  it("hides Create Order from a reader", async () => {
    signInWith(["purchase_orders:read"]);
    renderAt("/purchase-orders", "/purchase-orders", <PurchaseOrdersPage />);

    expect(
      await screen.findByText(/you can view this, not change it/i),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByTestId("header-actions")).not.toBeInTheDocument(),
    );
  });

  it("offers Create Order to an account that may write", async () => {
    signInWith(["purchase_orders:read", "purchase_orders:write"]);
    renderAt("/purchase-orders", "/purchase-orders", <PurchaseOrdersPage />);

    expect(await screen.findByTestId("header-actions")).toBeInTheDocument();
  });
});
