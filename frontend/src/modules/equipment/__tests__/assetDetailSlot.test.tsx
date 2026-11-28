import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";

import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import {
  moduleRegistry,
  slotComponent,
  type SlotDataMap,
} from "@/lib/moduleRegistry";
import { signInWith, signOut } from "@/test/auth";
import { onePage } from "@/test/mocks/page";
import { server } from "@/test/mocks/server";
import { withModules } from "@/test/moduleList";

import AssetDetailPage from "../pages/AssetDetailPage";

// The asset page is Equipment's screen; what fills the slot is the rentals
// module's, stood in for here so this file tests the mount point and the data
// it hands over.
function AssetHistoryProbe({
  data,
}: {
  data: SlotDataMap["asset_detail_extra"];
}) {
  return (
    <p data-testid="asset-history-slot">
      {data.itemName} ({data.itemId})
    </p>
  );
}

moduleRegistry.register({
  name: "rentals",
  routes: [],
  slots: [
    {
      slot: "asset_detail_extra",
      component: slotComponent(AssetHistoryProbe),
    },
  ],
});

const ITEM_ID = "5b0f4a9e-2c1d-4e8f-9a3b-7d6c5e4f3a21";

const asset = {
  id: ITEM_ID,
  name: "HP EliteBook",
  brand: "HP",
  barcode: null,
  status: "ACTIVE",
  category_id: "cat-1",
  location_id: "loc-1",
  context_tag: "equipment",
  category: { id: "cat-1", name: "Laptops", context_tag: "equipment" },
  quantity: 1,
  is_deleted: false,
  added_date: "2024-01-01T00:00:00Z",
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
  metadata: {
    equipment: {
      equipment_status: "AVAILABLE",
      serial_number: "SN-123",
    },
  },
};

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
  return render(
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter initialEntries={[`/equipment/${ITEM_ID}`]}>
          <PageHeaderHost>
            <Routes>
              <Route path="/equipment/:id" element={<AssetDetailPage />} />
            </Routes>
          </PageHeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
}

describe("AssetDetailPage — asset_detail_extra slot", () => {
  beforeEach(() => {
    signInWith(["equipment:read", "items:read"]);
    withModules("equipment", "rentals");
    server.use(
      http.get(`/api/v1/items/${ITEM_ID}`, () => HttpResponse.json(asset)),
      http.get(`/api/v1/equipment/${ITEM_ID}/approval-status`, () =>
        HttpResponse.json({
          has_workflow: false,
          request_id: null,
          status: null,
        }),
      ),
      http.get(`/api/v1/equipment/assignments/item/${ITEM_ID}`, () =>
        HttpResponse.json(onePage([])),
      ),
      http.get(`/api/v1/equipment/${ITEM_ID}/valuation`, () =>
        HttpResponse.json({}),
      ),
      http.get(`/api/v1/equipment/${ITEM_ID}/attachments`, () =>
        HttpResponse.json(onePage([])),
      ),
      http.get(`/api/v1/equipment/assets/${ITEM_ID}/timeline`, () =>
        HttpResponse.json({ events: [] }),
      ),
    );
  });

  afterEach(() => {
    signOut();
  });

  it("renders a module's component on the timeline tab with the asset it is about", async () => {
    renderPage();

    await userEvent.click(await screen.findByRole("tab", { name: "Timeline" }));

    const slot = await screen.findByTestId("asset-history-slot");
    expect(slot).toHaveTextContent(asset.name);
    expect(slot).toHaveTextContent(asset.id);
  });
});
