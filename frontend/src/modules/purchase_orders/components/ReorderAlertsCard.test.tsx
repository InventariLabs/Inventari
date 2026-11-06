import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { toast } from "sonner";
import { ReorderAlertsCard } from "./ReorderAlertsCard";
import type { ReplenishmentAlert } from "../api/reorder-rules";

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    loading: vi.fn(),
  },
}));

const ALERT_WITH_SUPPLIER: ReplenishmentAlert = {
  reorder_rule_id: "rule-1",
  product_template_id: "tpl-1",
  product_name: "Latte cups",
  sku: "CUP-01",
  location_id: "loc-1",
  available_quantity: 2,
  min_quantity: 10,
  max_quantity: 20,
  safety_stock: 0,
  shortage: 8,
  suggested_reorder_quantity: 18,
  reserve_available_quantity: 40,
  proposed_move_quantity: 18,
  remaining_to_buy: 0,
  preferred_partner_id: "p-1",
  preferred_partner_name: "ACME",
};

const ALERT_WITHOUT_SUPPLIER: ReplenishmentAlert = {
  ...ALERT_WITH_SUPPLIER,
  reorder_rule_id: "rule-2",
  product_template_id: "tpl-2",
  product_name: "Napkins",
  sku: "NAP-01",
  reserve_available_quantity: 0,
  proposed_move_quantity: 0,
  remaining_to_buy: 18,
  preferred_partner_id: null,
  preferred_partner_name: null,
};

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
};

const locationName = (id: string) => id;

describe("ReorderAlertsCard draft-PO action", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("marks an alert without a supplier instead of counting it as actionable", () => {
    render(
      <ReorderAlertsCard
        alerts={[ALERT_WITH_SUPPLIER, ALERT_WITHOUT_SUPPLIER]}
        locationName={locationName}
        canWrite
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText("No supplier")).toBeInTheDocument();
    expect(screen.getByText(/ACME/)).toBeInTheDocument();
    // Reserve covers the whole shortage: the card says so and offers the move.
    expect(
      screen.getByText("Reserve covers the whole shortage"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Replenish" }),
    ).toBeInTheDocument();
    // one of the two alerts is actionable, so the action exists
    expect(
      screen.getByRole("button", { name: "Create draft POs" }),
    ).toBeInTheDocument();
  });

  it("names the minimum as the threshold when it is the higher one", () => {
    render(
      <ReorderAlertsCard
        alerts={[{ ...ALERT_WITH_SUPPLIER, available_quantity: 2 }]}
        locationName={locationName}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText("available 2 / min 10")).toBeInTheDocument();
  });

  it("names the safety stock as the threshold when it stands above the minimum", () => {
    render(
      <ReorderAlertsCard
        alerts={[
          {
            ...ALERT_WITH_SUPPLIER,
            available_quantity: 19,
            min_quantity: 19,
            safety_stock: 21,
          },
        ]}
        locationName={locationName}
      />,
      { wrapper: createWrapper() },
    );

    expect(
      screen.getByText("available 19 / safety stock 21"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/min 19/)).not.toBeInTheDocument();
  });

  it("hides the create action when no alert has a supplier", () => {
    render(
      <ReorderAlertsCard
        alerts={[ALERT_WITHOUT_SUPPLIER]}
        locationName={locationName}
        canWrite
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText("No supplier")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Create draft POs" }),
    ).not.toBeInTheDocument();
  });

  it("hides the create action from a read-only account", () => {
    render(
      <ReorderAlertsCard
        alerts={[ALERT_WITH_SUPPLIER]}
        locationName={locationName}
        canWrite={false}
      />,
      { wrapper: createWrapper() },
    );

    expect(
      screen.queryByRole("button", { name: "Create draft POs" }),
    ).not.toBeInTheDocument();
  });

  it("sends only the supplier-backed rules and reports both halves", async () => {
    let postedBody: { reorder_rule_ids?: string[] } = {};
    server.use(
      http.post(
        "/api/v1/purchase-orders/replenishment/draft-pos",
        async ({ request }) => {
          postedBody = (await request.json()) as typeof postedBody;
          return HttpResponse.json(
            {
              created: [{ id: "po-1" }],
              skipped: [
                {
                  reorder_rule_id: "rule-2",
                  product_name: "Napkins",
                  reason: "no_supplier",
                },
              ],
            },
            { status: 201 },
          );
        },
      ),
    );

    render(
      <ReorderAlertsCard
        alerts={[ALERT_WITH_SUPPLIER, ALERT_WITHOUT_SUPPLIER]}
        locationName={locationName}
        canWrite
      />,
      { wrapper: createWrapper() },
    );

    fireEvent.click(screen.getByRole("button", { name: "Create draft POs" }));

    await waitFor(() =>
      expect(postedBody.reorder_rule_ids).toEqual(["rule-1"]),
    );
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("1 draft PO created"),
    );
    expect(toast.info).toHaveBeenCalledWith(
      "1 alert skipped (covered by reserve, no supplier, or no shortage)",
    );
  });
});
