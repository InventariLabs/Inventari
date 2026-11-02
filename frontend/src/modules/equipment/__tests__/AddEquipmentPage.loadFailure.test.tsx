import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

import AddEquipmentPage from "../pages/AddEquipmentPage";

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

const ITEM_ID = "0d0c30b6-5b2f-4d09-9a1e-6f0c1b7bb0f1";

/**
 * A failed read used to leave the edit form standing and empty.
 *
 * Measured before the fix: inject a 500 on the asset read, open the edit
 * screen, let the failure pass, type a name and save. The save succeeded —
 * and the record lost its serial number, its purchase price and the whole
 * meta_data block of category fields. The form had nothing to write back
 * because it had never read anything, and nothing on screen said so.
 */
function PageHeaderHost({ children }: { children: React.ReactNode }) {
  const [data, setData] = React.useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      {children}
    </PageHeaderContext.Provider>
  );
}

function renderEditPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter initialEntries={[`/equipment/${ITEM_ID}/edit`]}>
          <PageHeaderHost>
            <Routes>
              <Route path="/equipment/:id/edit" element={children} />
            </Routes>
          </PageHeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
  return render(<AddEquipmentPage />, { wrapper });
}

describe("AddEquipmentPage — the record failed to load", () => {
  beforeEach(() => {
    server.resetHandlers();
  });

  it("shows an error with a retry instead of an empty form", async () => {
    server.use(
      http.get(`/api/v1/items/${ITEM_ID}`, () =>
        HttpResponse.json({ detail: "Internal Server Error" }, { status: 500 }),
      ),
    );

    renderEditPage();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /save asset/i }),
    ).not.toBeInTheDocument();
  });

  it("loads the record when the retry succeeds", async () => {
    let attempt = 0;
    server.use(
      http.get(`/api/v1/items/${ITEM_ID}`, () => {
        attempt += 1;
        if (attempt === 1) {
          return HttpResponse.json({ detail: "boom" }, { status: 500 });
        }
        return HttpResponse.json({
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
        });
      }),
    );

    renderEditPage();
    await screen.findByRole("alert");

    await userEvent.click(screen.getByRole("button", { name: /try again/i }));

    expect(await screen.findByDisplayValue("HP EliteBook")).toBeInTheDocument();
  });

  it("says the asset is gone when the read comes back 404", async () => {
    server.use(
      http.get(`/api/v1/items/${ITEM_ID}`, () =>
        HttpResponse.json({ detail: "Not found" }, { status: 404 }),
      ),
    );

    renderEditPage();

    expect(await screen.findByText(/asset not found/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /save asset/i }),
    ).not.toBeInTheDocument();
    // A record that is gone has nothing to retry — the way out is back.
    expect(
      screen.queryByRole("button", { name: /try again/i }),
    ).not.toBeInTheDocument();
  });
});

describe("AddEquipmentPage — the pickers failed to load", () => {
  it("says so and holds the save instead of offering empty pickers", async () => {
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
      http.get("/api/v1/categories/", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <ModulesProvider>
          <MemoryRouter initialEntries={["/equipment/add"]}>
            <PageHeaderHost>
              <Routes>
                <Route path="/equipment/add" element={<AddEquipmentPage />} />
              </Routes>
            </PageHeaderHost>
          </MemoryRouter>
        </ModulesProvider>
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText(/categories or locations could not be loaded/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save asset/i })).toBeDisabled();
  });
});

describe("AddEquipmentPage — the model list failed to load", () => {
  it("replaces the model picker with a retry instead of an empty one", async () => {
    server.use(
      http.get("/api/v1/modules/my", () =>
        HttpResponse.json([
          "core",
          "items",
          "locations",
          "categories",
          "equipment",
        ]),
      ),
      http.get("/api/v1/equipment/models", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <ModulesProvider>
          <MemoryRouter initialEntries={["/equipment/add"]}>
            <PageHeaderHost>
              <Routes>
                <Route path="/equipment/add" element={<AddEquipmentPage />} />
              </Routes>
            </PageHeaderHost>
          </MemoryRouter>
        </ModulesProvider>
      </QueryClientProvider>,
    );

    expect(
      await screen.findByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: /select model/i }),
    ).not.toBeInTheDocument();
  });
});
