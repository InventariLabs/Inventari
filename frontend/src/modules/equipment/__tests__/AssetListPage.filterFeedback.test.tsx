import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import AssetListPage from "../pages/AssetListPage";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { ModulesProvider } from "@/contexts/ModulesContext";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({
    setHeader: vi.fn(),
  }),
}));

const mockItem = (i: number, equipmentStatus = "AVAILABLE") => ({
  id: `item-${i}`,
  name: `Asset ${i}`,
  brand: "Dell",
  barcode: `barcode-${i}`,
  status: "ACTIVE",
  category_id: "cat-1",
  location_id: "loc-1",
  context_tag: "equipment",
  created_at: `2024-01-${String(i).padStart(2, "0")}T00:00:00Z`,
  updated_at: `2024-01-${String(i).padStart(2, "0")}T00:00:00Z`,
  metadata: {
    equipment: {
      equipment_status: equipmentStatus,
    },
  },
});

const emptyPageMock = {
  items: [],
  total: 0,
  offset: 0,
  limit: 50,
  has_more: false,
};

const deployedPageMock = {
  items: [mockItem(1, "DEPLOYED")],
  total: 1,
  offset: 0,
  limit: 50,
  has_more: false,
};

const createWrapper = (initialEntries: string[] = ["/"]) => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
};

describe("AssetListPage — filter feedback", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a named empty state for an active status filter and clears it", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/v1/equipment/assets", () =>
        HttpResponse.json(emptyPageMock),
      ),
    );
    render(<AssetListPage />, { wrapper: createWrapper() });

    // No filters → onboarding state.
    expect(
      await screen.findByText(
        "Track IT assets, equipment, and other physical items across your organization.",
      ),
    ).toBeInTheDocument();

    // Activate the status filter chip → named empty state with clear action.
    await user.click(screen.getByRole("button", { name: "Checked Out" }));
    expect(
      await screen.findByText("No assets with status Checked Out"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(
      await screen.findByText(
        "Track IT assets, equipment, and other physical items across your organization.",
      ),
    ).toBeInTheDocument();
  });

  it("shows a clearable status badge in the list header while the filter is active", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/v1/equipment/assets", () =>
        HttpResponse.json(deployedPageMock),
      ),
    );
    render(<AssetListPage />, { wrapper: createWrapper() });

    await screen.findAllByText("Asset 1");
    expect(
      screen.queryByRole("button", { name: "Clear status filter" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Checked Out" }));

    const clearButton = await screen.findByRole("button", {
      name: "Clear status filter",
    });
    await user.click(clearButton);
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Clear status filter" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("shows the checked-out empty state from the dashboard tile link", async () => {
    server.use(
      http.get("/api/v1/equipment/assets", () =>
        HttpResponse.json(emptyPageMock),
      ),
    );
    render(<AssetListPage />, {
      wrapper: createWrapper(["/equipment/assets?checked_out=1"]),
    });

    expect(
      await screen.findByText("No assets are checked out"),
    ).toBeInTheDocument();
  });

  it("shows a clearable checked-out badge in the header", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/v1/equipment/assets", () =>
        HttpResponse.json(deployedPageMock),
      ),
    );
    render(<AssetListPage />, {
      wrapper: createWrapper(["/equipment/assets?checked_out=1"]),
    });

    await screen.findAllByText("Asset 1");
    const clearButton = await screen.findByRole("button", {
      name: "Clear checked-out filter",
    });
    await user.click(clearButton);
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Clear checked-out filter" }),
      ).not.toBeInTheDocument(),
    );
  });
});
