import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { server } from "@/test/mocks/server";
import { signInWith } from "@/test/auth";
import { purchaseOrderRow } from "@/test/factories/purchaseOrders";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import PurchaseOrdersPage from "./PurchaseOrdersPage";
import type { PurchaseOrder } from "@/modules/purchase_orders/types/purchase-orders";

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

// The form has its own tests; here it only has to open and close.
vi.mock("@/modules/purchase_orders/components/PurchaseOrderFormModal", () => ({
  default: (props: {
    purchaseOrder?: { number: string };
    onClose: () => void;
    onSuccess: () => void;
  }) => (
    <div role="dialog" aria-label="Order form">
      <span>{props.purchaseOrder?.number ?? "new order"}</span>
      <button onClick={props.onClose}>close form</button>
      <button onClick={props.onSuccess}>save form</button>
    </div>
  ),
}));

const order = {
  id: "po-1",
  organization_id: "org-1",
  number: "PO/2026/001",
  status: "DRAFT",
  partner_id: "partner-1",
  scheduled_date: null,
  notes: null,
  currency: "PLN",
  created_by: "user-1",
  confirmed_by: null,
  confirmed_at: null,
  cancelled_by: null,
  cancelled_at: null,
  created_at: "2026-01-01T10:00:00Z",
  updated_at: "2026-01-01T10:00:00Z",
  lines: [],
} as unknown as PurchaseOrder;

function ShellHeader({ children }: { children: React.ReactNode }) {
  const [header, setHeader] = React.useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data: header, setHeader }}>
      <header aria-label="Page header">{header.actions}</header>
      <main>{children}</main>
    </PageHeaderContext.Provider>
  );
}

function Where() {
  const location = useLocation();
  return <div data-testid="where">{location.pathname + location.search}</div>;
}

function renderPage(entry = "/purchase-orders") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route
            path="/purchase-orders"
            element={
              <ShellHeader>
                <PurchaseOrdersPage />
                <Where />
              </ShellHeader>
            }
          />
          <Route path="/purchase-orders/:id" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * The list's row actions go through the whole order: confirming and
 * cancelling post to that order's own address and close the dialog either
 * way. A handler that posted the wrong action, kept the dialog open after a
 * refusal or toasted a refusal as success fails here.
 */
describe("PurchaseOrdersPage — row actions post to the order they name", () => {
  let posted: string[];

  beforeEach(() => {
    vi.clearAllMocks();
    posted = [];
    signInWith([
      "purchase_orders:read",
      "purchase_orders:write",
      "purchase_orders:manage",
    ]);
    server.use(
      http.get("/api/v1/purchase-orders", () =>
        HttpResponse.json({ items: [purchaseOrderRow(order)], total: 1 }),
      ),
      http.get("/api/v1/purchase-orders/settings", () =>
        HttpResponse.json({
          approval_required: false,
          approval_threshold: null,
        }),
      ),
      http.get("/api/v1/purchase-orders/po-1", () => HttpResponse.json(order)),
      http.post("/api/v1/purchase-orders/po-1/confirm", () => {
        posted.push("confirm");
        return HttpResponse.json({ ...order, status: "CONFIRMED" });
      }),
      http.post("/api/v1/purchase-orders/po-1/cancel", () => {
        posted.push("cancel");
        return HttpResponse.json({ ...order, status: "CANCELLED" });
      }),
    );
  });

  it("confirms the order and closes the dialog", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("PO/2026/001");
    await user.click(screen.getByRole("button", { name: /confirm/i }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Purchase order confirmed"),
    );
    expect(posted).toEqual(["confirm"]);
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
  });

  it("says the order went for approval when confirming parked it", async () => {
    server.use(
      http.post("/api/v1/purchase-orders/po-1/confirm", () =>
        HttpResponse.json({ ...order, status: "PENDING_APPROVAL" }),
      ),
    );
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("PO/2026/001");
    await user.click(screen.getByRole("button", { name: /confirm/i }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "Purchase order sent for approval",
      ),
    );
  });

  it("cancels the order from the row menu", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("PO/2026/001");
    await user.click(screen.getByRole("button", { name: /more actions/i }));
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    const dialog = await screen.findByRole("alertdialog", {
      name: /cancel order PO\/2026\/001/i,
    });
    await user.click(
      within(dialog).getByRole("button", { name: "Cancel order" }),
    );
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Purchase order cancelled"),
    );
    expect(posted).toEqual(["cancel"]);
  });

  it("toasts a refused confirm as an error and closes the dialog", async () => {
    server.use(
      http.post("/api/v1/purchase-orders/po-1/confirm", () =>
        HttpResponse.json({ detail: "Order has no supplier" }, { status: 409 }),
      ),
    );
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("PO/2026/001");
    await user.click(screen.getByRole("button", { name: /confirm/i }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Order has no supplier"),
    );
    expect(toast.success).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
  });

  it("closes the dialog on Cancel without posting", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("PO/2026/001");
    await user.click(screen.getByRole("button", { name: /confirm/i }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(posted).toEqual([]);
  });

  it("says so when the order to confirm could not be read", async () => {
    server.use(
      http.get("/api/v1/purchase-orders/po-1", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("PO/2026/001");
    await user.click(screen.getByRole("button", { name: /confirm/i }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("opens the whole order in the edit form and closes it again", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("PO/2026/001");
    await user.click(screen.getByRole("button", { name: /edit/i }));
    const form = await screen.findByRole("dialog", { name: "Order form" });
    expect(form).toHaveTextContent("PO/2026/001");
    await user.click(within(form).getByRole("button", { name: "close form" }));
    expect(
      screen.queryByRole("dialog", { name: "Order form" }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /edit/i }));
    await user.click(await screen.findByRole("button", { name: "save form" }));
    expect(
      screen.queryByRole("dialog", { name: "Order form" }),
    ).not.toBeInTheDocument();
  });

  it("creates a new order from the header button", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("PO/2026/001");
    await user.click(
      within(screen.getByRole("banner", { name: "Page header" })).getByRole(
        "button",
        { name: /create/i },
      ),
    );
    const form = screen.getByRole("dialog", { name: "Order form" });
    expect(form).toHaveTextContent("new order");
    await user.click(within(form).getByRole("button", { name: "save form" }));
    expect(
      screen.queryByRole("dialog", { name: "Order form" }),
    ).not.toBeInTheDocument();
  });

  it("opens an order's page from its row", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByText("PO/2026/001"));
    await waitFor(() =>
      expect(screen.getByTestId("where")).toHaveTextContent(
        "/purchase-orders/po-1",
      ),
    );
  });

  it("drops the supplier filter from the address on Show all", async () => {
    server.use(
      http.get("/api/v1/partners/partner-1", () =>
        HttpResponse.json({ id: "partner-1", name: "ACME Supplies" }),
      ),
    );
    const user = userEvent.setup();
    renderPage("/purchase-orders?partner_id=partner-1");
    await user.click(await screen.findByRole("button", { name: "Show all" }));
    await waitFor(() =>
      expect(screen.getByTestId("where")).toHaveTextContent(
        /^\/purchase-orders$/,
      ),
    );
  });

  it("pages back after paging forward", async () => {
    const offsets: string[] = [];
    server.use(
      http.get("/api/v1/purchase-orders", ({ request }) => {
        offsets.push(new URL(request.url).searchParams.get("offset") ?? "");
        return HttpResponse.json({
          items: [purchaseOrderRow(order)],
          total: 120,
        });
      }),
    );
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("PO/2026/001");
    await user.click(screen.getByRole("button", { name: /next/i }));
    await waitFor(() => expect(offsets).toContain("50"));
    await user.click(screen.getByRole("button", { name: /previous|prev/i }));
    await waitFor(() => expect(offsets.at(-1)).toBe("0"));
  });

  it("retries a list that failed to load", async () => {
    let calls = 0;
    server.use(
      http.get("/api/v1/purchase-orders", () => {
        calls += 1;
        return calls === 1
          ? HttpResponse.json({ detail: "boom" }, { status: 500 })
          : HttpResponse.json({ items: [purchaseOrderRow(order)], total: 1 });
      }),
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Try again" }));
    expect(await screen.findByText("PO/2026/001")).toBeInTheDocument();
  });
});
