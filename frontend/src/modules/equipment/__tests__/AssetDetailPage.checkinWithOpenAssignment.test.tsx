import React from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { http, HttpResponse } from "msw";
import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";

import AssetDetailPage from "../pages/AssetDetailPage";
import { onePage } from "@/test/mocks/page";

// These pages hide their write actions from an account that cannot write,
// so a spec about the actions has to say who is looking at them.
beforeEach(() => {
  signInWith([
    "equipment:read",
    "equipment:write",
    "items:read",
    "locations:read",
    "locations:write",
    "categories:read",
    "categories:write",
  ]);
});

afterEach(() => {
  signOut();
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const ITEM_ID = "ec6be09a-90ba-449d-a45b-6217ef627d37";

/**
 * An asset with an OPEN assignment must always show the
 * check-in action — even when its status is MAINTENANCE. Before the fix the
 * button required `status === "DEPLOYED"`, so a maintenance entry on a
 * checked-out asset removed the only way back from the detail page.
 */

/**
 * Mirrors ModuleShell: keeps the page-header data in state and renders the
 * actions so header buttons (check-in/check-out/retire) are in the DOM.
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

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter initialEntries={[`/equipment/${ITEM_ID}`]}>
          <PageHeaderHost>
            <Routes>
              <Route path="/equipment/:id" element={children} />
            </Routes>
          </PageHeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
  return render(<AssetDetailPage />, { wrapper });
}

describe("AssetDetailPage — check-in with open assignment", () => {
  beforeEach(() => {
    server.resetHandlers();
    server.use(
      http.get(`/api/v1/items/${ITEM_ID}`, () =>
        HttpResponse.json({
          id: ITEM_ID,
          name: "HP EliteBook",
          brand: "HP",
          barcode: null,
          status: "ACTIVE",
          category_id: "cat-1",
          location_id: "loc-1",
          context_tag: "equipment",
          quantity: 1,
          added_date: "2024-01-01T00:00:00Z",
          created_at: "2024-01-01T00:00:00Z",
          updated_at: "2024-01-01T00:00:00Z",
          metadata: {
            equipment: {
              equipment_status: "MAINTENANCE",
              serial_number: "SN-123",
            },
          },
        }),
      ),
      http.get(`/api/v1/equipment/assignments/item/${ITEM_ID}`, () =>
        HttpResponse.json(
          onePage([
            {
              id: "a1",
              item_id: ITEM_ID,
              assigned_to_name: "Marta Zielinska",
              assigned_to_email: "marta@example.com",
              checked_out_at: "2026-08-01T09:00:00Z",
              checked_in_at: null,
              expected_return_at: null,
            },
          ]),
        ),
      ),
      http.get(`/api/v1/equipment/${ITEM_ID}/approval-status`, () =>
        HttpResponse.json({
          has_workflow: false,
          request_id: null,
          status: null,
        }),
      ),
      http.get(`/api/v1/equipment/${ITEM_ID}/valuation`, () =>
        HttpResponse.json({}),
      ),
      http.get(`/api/v1/equipment/${ITEM_ID}/attachments`, () =>
        HttpResponse.json(onePage([])),
      ),
    );
  });

  it("shows the check-in button when an open assignment exists and status is MAINTENANCE", async () => {
    renderPage();
    // The Info tab renders once the item query resolved.
    await screen.findByText("Serial Number", {}, { timeout: 5000 });
    // The check-in action must be present despite MAINTENANCE status.
    expect(
      await screen.findByRole("button", { name: /^return$/i }),
    ).toBeInTheDocument();
  });

  it("shows no check-in button without an open assignment", async () => {
    server.use(
      http.get(`/api/v1/equipment/assignments/item/${ITEM_ID}`, () =>
        HttpResponse.json(onePage([])),
      ),
    );
    renderPage();
    await screen.findByText("Serial Number", {}, { timeout: 5000 });
    // Give the assignments query a beat to settle before asserting absence.
    await new Promise((r) => setTimeout(r, 100));
    expect(
      screen.queryByRole("button", { name: /^return$/i }),
    ).not.toBeInTheDocument();
  });
});
