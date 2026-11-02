import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

import AssetDetailPage from "@/modules/equipment/pages/AssetDetailPage";
import { toast } from "sonner";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

/**
 * The status menu offers "Available" and "Maintenance"; the confirmation that
 * followed a change answered with the code the database stores.
 *
 * "Status changed to MAINTENANCE" is the enum, and the reader has no way to
 * know it means the row they just picked two rows above — the menu beside it
 * said "Maintenance". Every other surface of the module (badge, list, filters,
 * timeline) already translates the value through `status.<value>`; this toast
 * was the one that did not.
 */
const ITEM_ID = "ec6be09a-90ba-449d-a45b-6217ef627d37";

beforeEach(() => {
  vi.clearAllMocks();
  signInWith([
    "equipment:read",
    "equipment:write",
    "items:read",
    "items:write",
    "locations:read",
    "categories:read",
  ]);
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
    http.patch("/api/v1/equipment/assets/bulk", () =>
      HttpResponse.json({ updated: 1, errors: [] }),
    ),
  );
});

afterEach(() => {
  signOut();
});

/** Mirrors ModuleShell: the header actions have to be in the DOM to be clicked. */
function PageHeaderHost({ children }: { children: React.ReactNode }) {
  const [data, setData] = React.useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      {data.actions ? <div>{data.actions}</div> : null}
      {children}
    </PageHeaderContext.Provider>
  );
}

function renderDetail() {
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

describe("the status toast speaks the menu's language", () => {
  it("confirms a status change with the label, not the enum", async () => {
    const user = userEvent.setup();
    renderDetail();
    await screen.findByText("Serial Number", {}, { timeout: 5000 });

    await user.click(
      await screen.findByRole("button", { name: "Change status" }),
    );
    await user.click(
      await screen.findByRole("menuitemradio", { name: "Maintenance" }),
    );

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    const said = String(vi.mocked(toast.success).mock.calls[0][0]);
    expect(said).toBe("Status changed to Maintenance");
    expect(said).not.toContain("MAINTENANCE");
  });
});
