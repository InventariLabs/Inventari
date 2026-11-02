import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { CheckoutModal } from "@/modules/equipment/components/CheckoutModal";
import type { Item } from "@/types";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const item = {
  id: "item-1",
  name: "Dell Latitude",
  location_id: "loc-1",
  category_id: null,
  quantity: 1,
  metadata: { equipment: {} },
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
} as unknown as Item;

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter>{children}</MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
};

/**
 * "My Assets" matches an assignment to the signed-in reader by email, and
 * attestation mails the holder. Neither works when a checkout carries a name
 * and nothing else — and the form asked for the name, made the address
 * optional, and said nothing about what that costs.
 */
describe("handing an asset to someone", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/organizations/my/members", () =>
        HttpResponse.json({
          items: [
            {
              id: "u-1",
              email: "anna.kowalska@example.com",
              full_name: "Anna Kowalska",
              role: "user",
            },
          ],
          total: 1,
          limit: 10,
          offset: 0,
          has_more: false,
        }),
      ),
      http.get("/api/v1/partners", () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
  });

  it("says what an empty address costs", () => {
    render(<CheckoutModal item={item} onClose={vi.fn()} />, {
      wrapper: createWrapper(),
    });

    expect(
      screen.getByText(/will not show up under the holder's My Assets/),
    ).toBeInTheDocument();
  });

  it("offers accounts of the organization, not only the Partners register", async () => {
    render(<CheckoutModal item={item} onClose={vi.fn()} />, {
      wrapper: createWrapper(),
    });

    fireEvent.focus(screen.getByPlaceholderText(/Search people/i));

    expect(
      await screen.findByText("Accounts in this organization"),
    ).toBeInTheDocument();
    fireEvent.click(await screen.findByText("Anna Kowalska"));

    await waitFor(() =>
      expect(
        screen.getByDisplayValue("anna.kowalska@example.com"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByDisplayValue("Anna Kowalska")).toBeInTheDocument();
  });
});
