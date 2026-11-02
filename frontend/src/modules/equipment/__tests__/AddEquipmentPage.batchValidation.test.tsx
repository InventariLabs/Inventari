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

import AddEquipmentPage from "../pages/AddEquipmentPage";

/**
 * A batch refused for a missing location says so on the field.
 *
 * The refusal used to be a toast alone: on a phone the Location select sits
 * screens above the Create button, so the message named a field nobody could
 * see and nothing marked or reached it. The single tab marks the field and
 * focuses it; the batch tab goes through the same check now.
 */

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const bulkCreate = vi.fn();

beforeEach(() => {
  bulkCreate.mockReset();
  server.use(
    http.post("/api/v1/equipment/items/bulk", () => {
      bulkCreate();
      return HttpResponse.json({ created: 0, failed: 0, items: [] });
    }),
  );
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

function renderAdd() {
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
}

describe("AddEquipmentPage — batch without a location", () => {
  it("marks the Location field and moves focus to it", async () => {
    renderAdd();

    await userEvent.click(await screen.findByRole("tab", { name: /batch/i }));
    await userEvent.type(
      await screen.findByLabelText(/serial numbers/i),
      "SN-1{Enter}SN-2{Enter}SN-3",
    );
    await userEvent.click(
      await screen.findByRole("button", { name: /create 3 assets/i }),
    );

    const location = await screen.findByRole("combobox", {
      name: /^location/i,
    });
    await waitFor(() => expect(location).toHaveFocus());
    expect(location).toHaveAttribute("aria-invalid", "true");
    expect(bulkCreate).not.toHaveBeenCalled();
  });
});
