import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import userEvent from "@testing-library/user-event";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { signInWith } from "@/test/auth";
import { toast } from "sonner";
import PurchaseOrdersPage from "./PurchaseOrdersPage";
import type { PurchaseOrder } from "@/modules/purchase_orders/types/purchase-orders";
import { purchaseOrderRow } from "@/test/factories/purchaseOrders";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: ["purchase_orders"],
    isModuleEnabled: (name: string) => name === "purchase_orders",
    isLoading: false,
    refreshModules: vi.fn(),
  }),
  useEnabledModulesOptional: () => ["purchase_orders"],
}));

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({
    setHeader: vi.fn(),
  }),
}));

const mockPO = {
  id: "po-1",
  organization_id: "org-1",
  number: "PO/2026/001",
  status: "DRAFT",
  partner_id: "partner-1",
  scheduled_date: "2026-05-01",
  notes: null,
  created_by: "user-1",
  confirmed_by: null,
  confirmed_at: null,
  cancelled_by: null,
  cancelled_at: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  lines: [
    {
      id: "line-1",
      purchase_order_id: "po-1",
      product_template_id: "pt-1",
      name: "Piwo Tyskie",
      quantity_ordered: 24,
      quantity_received: 0,
      unit_price: "18.50",
      uom_id: null,
      uom_symbol: null,
      tax_rate: null,
      line_number: 1,
      notes: null,
    },
  ],
};

// The list answers with rows (the lines counted and summed, not carried);
// editing and confirming read the whole order from its own address.
const mockRow = purchaseOrderRow(mockPO as unknown as PurchaseOrder);

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

describe("PurchaseOrdersPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // The write controls are gated on the permission now, so the tests that
    // exercise them sign in the account that holds it.
    signInWith(["purchase_orders:read", "purchase_orders:write"]);
    server.use(
      http.get("/api/v1/purchase-orders", () =>
        HttpResponse.json({ items: [mockRow], total: 1 }),
      ),
      http.get("/api/v1/purchase-orders/po-1", () => HttpResponse.json(mockPO)),
    );
  });

  it("shows empty state when no purchase orders", async () => {
    server.use(
      http.get("/api/v1/purchase-orders", () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
    render(<PurchaseOrdersPage />, { wrapper: createWrapper() });
    expect(await screen.findByText(/no purchase orders/i)).toBeInTheDocument();
  });

  it("shows purchase order list", async () => {
    render(<PurchaseOrdersPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText("PO/2026/001")).toBeInTheDocument();
    });
    expect(screen.getByText(/1 line/i)).toBeInTheDocument();
  });

  it("shows DRAFT badge", async () => {
    render(<PurchaseOrdersPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText("Draft")).toBeInTheDocument();
    });
  });

  it("shows create button in the empty state", async () => {
    server.use(
      http.get("/api/v1/purchase-orders", () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
    render(<PurchaseOrdersPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /create order/i }),
      ).toBeInTheDocument();
    });
  });

  it("opens create modal from the empty state", async () => {
    server.use(
      http.get("/api/v1/purchase-orders", () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
    const user = userEvent.setup();
    render(<PurchaseOrdersPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /create order/i }),
      ).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: /create order/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("New purchase order")).toBeInTheDocument();
  });

  it("filters the list with search and status tabs", async () => {
    const user = userEvent.setup();
    const requests: string[] = [];
    server.use(
      http.get("/api/v1/purchase-orders", ({ request }) => {
        requests.push(request.url);
        return HttpResponse.json({
          items: [mockRow],
          total: 1,
          limit: 50,
          offset: 0,
          has_more: false,
        });
      }),
    );

    render(<PurchaseOrdersPage />, { wrapper: createWrapper() });
    await screen.findByText("PO/2026/001");
    await user.type(screen.getByTestId("list-search-input"), "priority");
    await user.click(screen.getByRole("tab", { name: "Confirmed" }));

    await waitFor(() => {
      expect(requests.some((url) => url.includes("search=priority"))).toBe(
        true,
      );
      expect(requests.some((url) => url.includes("status=CONFIRMED"))).toBe(
        true,
      );
    });
  });

  it("does not render the pager when total fits one page", async () => {
    server.use(
      http.get("/api/v1/purchase-orders", () =>
        HttpResponse.json({ items: [mockRow], total: 1 }),
      ),
    );
    render(<PurchaseOrdersPage />, { wrapper: createWrapper() });
    await screen.findByText("PO/2026/001");
    expect(
      screen.queryByRole("button", { name: /next/i }),
    ).not.toBeInTheDocument();
  });

  it("makes the second page reachable", async () => {
    const user = userEvent.setup();
    const offsets: string[] = [];
    server.use(
      http.get("/api/v1/purchase-orders", ({ request }) => {
        const url = new URL(request.url);
        const offset = url.searchParams.get("offset") ?? "0";
        offsets.push(offset);
        return HttpResponse.json({
          items: [{ ...mockRow, id: `po-${offset}`, number: `PO/${offset}` }],
          total: 51,
          limit: 50,
          offset: Number(offset),
          has_more: offset === "0",
        });
      }),
    );

    render(<PurchaseOrdersPage />, { wrapper: createWrapper() });
    await screen.findByText("PO/0");
    await user.click(screen.getByRole("button", { name: /next/i }));

    expect(await screen.findByText("PO/50")).toBeInTheDocument();
    expect(offsets).toContain("50");
  });

  it("says so when the order to edit could not be read", async () => {
    // The row carries no lines, so Edit reads the whole order first; a
    // read that failed used to leave the press doing nothing at all.
    server.use(
      http.get("/api/v1/purchase-orders/po-1", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    render(<PurchaseOrdersPage />, { wrapper: createWrapper() });
    await screen.findByText("PO/2026/001");

    await user.click(screen.getByRole("button", { name: /edit/i }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("shows edit button for DRAFT PO", async () => {
    render(<PurchaseOrdersPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText("PO/2026/001")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /edit/i })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /confirm/i }),
    ).toBeInTheDocument();
  });

  it("offers no cancel to an account that may write but not manage", async () => {
    render(<PurchaseOrdersPage />, { wrapper: createWrapper() });
    await screen.findByText("PO/2026/001");
    // The endpoint answers 403 to it, so the row does not invite the click.
    expect(
      screen.queryByRole("button", { name: /more actions/i }),
    ).not.toBeInTheDocument();
  });

  it("keeps cancel in the row menu, not on the row", async () => {
    signInWith([
      "purchase_orders:read",
      "purchase_orders:write",
      "purchase_orders:manage",
    ]);
    const user = userEvent.setup();
    render(<PurchaseOrdersPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText("PO/2026/001")).toBeInTheDocument();
    });
    expect(
      screen.queryByRole("button", { name: /cancel/i }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /more actions/i }));
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
  });

  // The list page's confirm dialog is the second address of the same
  // class: it used to pick between two sentences on `approval_required`
  // alone, so the "off" branch handed the reader a condition about their
  // own organization that the branch had already settled.
  it("confirming with no approval and no threshold names no queue", async () => {
    server.use(
      http.get("/api/v1/purchase-orders/settings", () =>
        HttpResponse.json({
          approval_required: false,
          approval_threshold: null,
        }),
      ),
    );
    const user = userEvent.setup();
    render(<PurchaseOrdersPage />, { wrapper: createWrapper() });
    await screen.findByText("PO/2026/001");
    await user.click(screen.getByRole("button", { name: /confirm/i }));

    expect(
      await screen.findByText(/once the order is confirmed/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/If your organization/)).not.toBeInTheDocument();
    expect(screen.queryByText(/approval queue/)).not.toBeInTheDocument();
  });

  it("confirming under a threshold names the threshold", async () => {
    server.use(
      http.get("/api/v1/purchase-orders/settings", () =>
        HttpResponse.json({
          approval_required: false,
          approval_threshold: "1000.00",
        }),
      ),
    );
    const user = userEvent.setup();
    render(<PurchaseOrdersPage />, { wrapper: createWrapper() });
    await screen.findByText("PO/2026/001");
    await user.click(screen.getByRole("button", { name: /confirm/i }));

    expect(await screen.findByText(/1,000\.00/)).toBeInTheDocument();
    expect(screen.queryByText(/If your organization/)).not.toBeInTheDocument();
  });
});

describe("PurchaseOrdersPage — a read-only account", () => {
  beforeEach(() => {
    signInWith(["purchase_orders:read"]);
    server.use(
      http.get("/api/v1/purchase-orders", () =>
        HttpResponse.json({ items: [mockRow], total: 1 }),
      ),
    );
  });

  it("offers no Create order in the empty state", async () => {
    server.use(
      http.get("/api/v1/purchase-orders", () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
    render(<PurchaseOrdersPage />, { wrapper: createWrapper() });

    expect(await screen.findByText(/no purchase orders/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /create order/i }),
    ).not.toBeInTheDocument();
    // The line under the heading must not tell a reader to create one.
    expect(screen.queryByText(/create your first/i)).not.toBeInTheDocument();
    expect(
      screen.getByText(/will appear here once they are created/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/you can view this, not change it/i),
    ).toBeInTheDocument();
  });

  it("hides Edit, Confirm and Cancel on a draft row", async () => {
    render(<PurchaseOrdersPage />, { wrapper: createWrapper() });

    await screen.findByText("PO/2026/001");
    expect(
      screen.queryByRole("button", { name: /edit/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /confirm/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /cancel/i }),
    ).not.toBeInTheDocument();
  });
});
