import React from "react";
import { render, screen } from "@testing-library/react";
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

import AddEquipmentPage from "../pages/AddEquipmentPage";

/**
 * Cancel ends the task, so it has to land somewhere that belongs to it.
 *
 * It used to pop the history stack. Entered from the asset list that
 * happened to land right; entered by address, from a scan or from another
 * module, it left the reader wherever they had been before — measured in the
 * app: open /equipment/add by address, click Cancel, land on /apps. Every
 * case below enters the form as the first history entry, where the old
 * `navigate(-1)` has nowhere to go and the form stays on screen.
 */

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const ITEM_ID = "0d0c30b6-5b2f-4d09-9a1e-6f0c1b7bb0f1";

beforeEach(() => {
  signInWith([
    "equipment:read",
    "equipment:write",
    "items:read",
    "locations:read",
    "categories:read",
  ]);
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

function renderAt(entry: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter initialEntries={[entry]}>
          <PageHeaderHost>
            <Routes>
              <Route path="/equipment/add" element={<AddEquipmentPage />} />
              <Route
                path="/equipment/:id/edit"
                element={<AddEquipmentPage />}
              />
              <Route path="/equipment/assets" element={<p>Asset list</p>} />
              <Route path="/equipment/:id" element={<p>Asset detail</p>} />
            </Routes>
          </PageHeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
}

describe("AddEquipmentPage — Cancel", () => {
  it("returns to the asset list from a form entered by address", async () => {
    renderAt("/equipment/add");

    await userEvent.click(
      await screen.findByRole("button", { name: /^cancel$/i }),
    );

    expect(await screen.findByText("Asset list")).toBeInTheDocument();
  });

  it("returns to the asset list from the batch tab", async () => {
    renderAt("/equipment/add");

    await userEvent.click(await screen.findByRole("tab", { name: /batch/i }));
    await userEvent.click(
      await screen.findByRole("button", { name: /^cancel$/i }),
    );

    expect(await screen.findByText("Asset list")).toBeInTheDocument();
  });

  it("returns to the asset being edited, where saving it would land", async () => {
    server.use(
      http.get(`/api/v1/items/${ITEM_ID}`, () =>
        HttpResponse.json({
          id: ITEM_ID,
          name: "HP EliteBook",
          barcode: null,
          category_id: null,
          location_id: "loc-1",
          quantity: 1,
          added_date: "2024-01-01T00:00:00Z",
          created_at: "2024-01-01T00:00:00Z",
          updated_at: "2024-01-01T00:00:00Z",
          metadata: {},
        }),
      ),
    );
    renderAt(`/equipment/${ITEM_ID}/edit`);
    await screen.findByDisplayValue("HP EliteBook");

    await userEvent.click(screen.getByRole("button", { name: /^cancel$/i }));

    expect(await screen.findByText("Asset detail")).toBeInTheDocument();
  });
});
