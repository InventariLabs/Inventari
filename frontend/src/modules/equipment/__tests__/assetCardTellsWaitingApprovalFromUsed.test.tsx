/**
 * The asset card tells an approval waiting to be used from one already used.
 *
 * An approved checkout request used to read the same however often it had
 * already opened the door: the card hid the request button as soon as the
 * status was APPROVED, so a spent approval looked identical to a fresh one
 * and the check-out button sat there with nothing left to authorise it. The
 * card now shows a waiting approval as "Approved for the next checkout" and
 * a spent one as a live "Request Approval" button.
 */
import React, { useState } from "react";
import { render, screen } from "@testing-library/react";
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
import AssetDetailPage from "../pages/AssetDetailPage";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

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

function HeaderHost({ children }: { children: React.ReactNode }) {
  const [data, setData] = useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      <div data-testid="header">{data.actions}</div>
      {children}
    </PageHeaderContext.Provider>
  );
}

const ITEM_ID = "ec6be09a-90ba-449d-a45b-6217ef627d37";

function stubAsset(consumed: boolean) {
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
            equipment_status: "AVAILABLE",
            serial_number: "SN-123",
          },
        },
      }),
    ),
    http.get(`/api/v1/equipment/assignments/item/${ITEM_ID}`, () =>
      HttpResponse.json(onePage([])),
    ),
    http.get(`/api/v1/equipment/${ITEM_ID}/approval-status`, () =>
      HttpResponse.json({
        has_workflow: true,
        request_id: "req-1",
        status: "APPROVED",
        consumed,
      }),
    ),
    http.get(`/api/v1/equipment/${ITEM_ID}/valuation`, () =>
      HttpResponse.json({}),
    ),
    http.get(`/api/v1/equipment/${ITEM_ID}/attachments`, () =>
      HttpResponse.json(onePage([])),
    ),
  );
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter initialEntries={[`/equipment/${ITEM_ID}`]}>
          <HeaderHost>
            <Routes>
              <Route path="/equipment/:id" element={<AssetDetailPage />} />
            </Routes>
          </HeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
}

describe("the asset card tells a waiting approval from a used one", () => {
  it("shows a waiting approval as approved for the next checkout", async () => {
    stubAsset(false);
    renderPage();

    expect(
      await screen.findByText("Approved for the next checkout"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Request Approval" }),
    ).not.toBeInTheDocument();
  });

  it("shows a spent approval as needing a new request", async () => {
    stubAsset(true);
    renderPage();

    expect(
      await screen.findByRole("button", { name: "Request Approval" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Approved for the next checkout"),
    ).not.toBeInTheDocument();
  });
});
