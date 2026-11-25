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

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const ITEM_ID = "ec6be09a-90ba-449d-a45b-6217ef627d37";

beforeEach(() => {
  signInWith(["equipment:read", "equipment:write", "items:read"]);
});

afterEach(() => {
  signOut();
});

function PageHeaderHost({ children }: { children: React.ReactNode }) {
  const [data, setData] = React.useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
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

/**
 * The register lists a record under no category when its metadata carries the
 * equipment namespace, and a JSON null is a namespace: the backend's SQL asks
 * whether the key is SQL NULL, which a JSON null is not. The card opens such a
 * record rather than answering "Asset not found" over a row the list showed.
 */
describe("AssetDetailPage — a namespace the register lists", () => {
  beforeEach(() => {
    server.resetHandlers();
    server.use(
      http.get(`/api/v1/items/${ITEM_ID}`, () =>
        HttpResponse.json({
          id: ITEM_ID,
          name: "Spare laptop",
          brand: null,
          barcode: null,
          category_id: null,
          category: null,
          location_id: "loc-1",
          quantity: 1,
          added_date: "2024-01-01T00:00:00Z",
          created_at: "2024-01-01T00:00:00Z",
          updated_at: "2024-01-01T00:00:00Z",
          metadata: { equipment: null },
        }),
      ),
      http.get(`/api/v1/equipment/assignments/item/${ITEM_ID}`, () =>
        HttpResponse.json(onePage([])),
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

  it("opens the record instead of claiming it is not found", async () => {
    renderPage();

    expect(
      await screen.findByRole("tab", { name: "Info" }, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Asset not found")).toBeNull();
  });
});
