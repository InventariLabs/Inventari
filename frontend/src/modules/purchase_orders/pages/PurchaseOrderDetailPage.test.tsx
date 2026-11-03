import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import PurchaseOrderDetailPage from "./PurchaseOrderDetailPage";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import { onePage } from "@/test/mocks/page";
// The approval card is the approvals module's slot; registering the module
// puts the real card on the page, so "offered once" counts both places.
import "@/modules/approvals/module";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const enabledModulesMock = { value: ["purchase_orders"] };

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: enabledModulesMock.value,
    isModuleEnabled: (name: string) => enabledModulesMock.value.includes(name),
    isLoading: false,
    refreshModules: vi.fn(),
  }),
  // The approval-signal hook reads the list without a provider's help — the
  // same list the page reads, so the two cannot disagree about "module on".
  useEnabledModulesOptional: () => enabledModulesMock.value,
}));

vi.mock("@/utils/helpers", () => ({
  downloadBlob: vi.fn(),
}));

vi.mock("@/hooks/usePartners", () => ({
  usePartners: vi.fn(() => ({
    data: {
      items: [
        { id: "partner-1", name: "ACME Supplies", email: "acme@test.com" },
      ],
      total: 1,
    },
  })),
  // The detail page reads the supplier by id now: the active-partner page it
  // used to search kept deactivated and off-page suppliers out.
  usePartner: vi.fn(() => ({
    data: { id: "partner-1", name: "ACME Supplies", email: "acme@test.com" },
  })),
}));

// The action bar asks for the permissions the API checks, not for role
// names: the backend guards cancel with purchase_orders:manage, so a custom
// role holding that key must be offered the same actions.
const mockAuthState: {
  user: {
    role: string;
    is_superuser: boolean;
    id?: string;
    permissions?: string[];
  } | null;
} = {
  user: {
    role: "user",
    is_superuser: false,
    permissions: [
      "purchase_orders:read",
      "purchase_orders:write",
      "purchase_orders:manage",
    ],
  },
};

vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector?: (s: typeof mockAuthState) => unknown) =>
    selector ? selector(mockAuthState) : mockAuthState,
}));

const mockPO = {
  id: "po-1",
  organization_id: "org-1",
  number: "PO/2026/001",
  status: "DRAFT",
  partner_id: "partner-1",
  partner_name: "ACME Supplies",
  scheduled_date: "2026-05-01",
  notes: "Test order",
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

const confirmedPO = {
  ...mockPO,
  status: "CONFIRMED",
  confirmed_by: "user-1",
  confirmed_at: new Date().toISOString(),
  lines: [
    {
      ...mockPO.lines[0],
      quantity_received: 10,
    },
  ],
};

const mockReceipt = {
  id: "doc-1",
  number: "IN/2026/001",
  type: "IN",
  status: "CONFIRMED",
  created_at: new Date().toISOString(),
};

/**
 * The module shell's header, reduced to what this page hands it: the page
 * puts its title, status and actions there, and the tests read them where a
 * reader finds them — above the page, not inside it.
 */
function ShellHeader({ children }: { children: React.ReactNode }) {
  const [header, setHeader] = React.useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data: header, setHeader }}>
      <header aria-label="Page header">
        <h1>{header.title}</h1>
        {header.statusBadge}
        {header.subtitle && <p>{header.subtitle}</p>}
        {header.actions}
      </header>
      <main aria-label="Page body">{children}</main>
    </PageHeaderContext.Provider>
  );
}

const pageHeader = () => screen.getByRole("banner", { name: "Page header" });
const pageBody = () => screen.getByRole("main", { name: "Page body" });

/** Where the order's Receive delivery lands, and what it was told. */
function ReceiveStub() {
  const location = useLocation();
  const state = location.state as { backTo?: string } | null;
  return (
    <div>
      Receive screen
      <span data-testid="receive-search">{location.search}</span>
      <span data-testid="receive-back">{state?.backTo}</span>
    </div>
  );
}

const createWrapper = (initialEntries = ["/purchase-orders/po-1"]) => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <Routes>
          <Route
            path="/purchase-orders/:id"
            element={<ShellHeader>{children}</ShellHeader>}
          />
          <Route path="/warehouse/receive" element={<ReceiveStub />} />
          <Route
            path="/warehouse/documents/:id"
            element={<div>Document page</div>}
          />
          <Route path="/purchase-orders" element={<div>PO list</div>} />
          <Route
            path="/purchase-orders/:id/linked-receipts"
            element={<div>Linked receipts</div>}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
};

describe("PurchaseOrderDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    enabledModulesMock.value = ["purchase_orders"];
    mockAuthState.user = {
      role: "user",
      is_superuser: false,
      permissions: [
        "purchase_orders:read",
        "purchase_orders:write",
        "purchase_orders:manage",
        // Deciding is `approvals:approve` on the API, not manage.
        "approvals:approve",
      ],
    };
    server.use(
      http.get("/api/v1/purchase-orders/po-1", () => HttpResponse.json(mockPO)),
      http.get("/api/v1/purchase-orders/po-1/linked-receipts", () =>
        HttpResponse.json(onePage([])),
      ),
      http.get("/api/v1/partners", () =>
        HttpResponse.json({
          items: [
            { id: "partner-1", name: "ACME Supplies", email: "acme@test.com" },
          ],
          total: 1,
        }),
      ),
      http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
    );
  });

  it("shows PO number", async () => {
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText("PO/2026/001")).toBeInTheDocument();
    });
  });

  it("says the approval requests could not be read instead of reporting none", async () => {
    enabledModulesMock.value = ["purchase_orders", "approvals"];
    server.use(
      http.get(
        "/api/v1/approvals/requests",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });

    expect(await within(pageBody()).findByRole("alert")).toBeInTheDocument();
    expect(
      within(pageBody()).getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it("shows DRAFT status badge", async () => {
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });
    // The badge, plus the first step of the status axis the detail gained
    // alongside the document's.
    await waitFor(() => {
      expect(screen.getAllByText("Draft").length).toBeGreaterThanOrEqual(1);
    });
  });

  it("shows the status axis, like the document detail does", async () => {
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });
    const axis = await screen.findByRole("list", { name: /status progress/i });
    expect(within(axis).getByText("Draft")).toBeInTheDocument();
    expect(within(axis).getByText("Confirmed")).toBeInTheDocument();
    expect(within(axis).getByText("Completed")).toBeInTheDocument();
  });

  it("shows scheduled date, formatted", async () => {
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });
    const dates = await screen.findAllByText(/May 1, 2026/);
    expect(dates.length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("2026-05-01")).not.toBeInTheDocument();
  });

  it("shows partner name in details", async () => {
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText("ACME Supplies")).toBeInTheDocument();
    });
  });

  it("shows notes in details", async () => {
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText("Test order")).toBeInTheDocument();
    });
  });

  it("puts the order's actions in the page header, beside its number", async () => {
    // They used to stand in a row of their own under the title, with
    // "Scheduled: …" at its other end — the document detail keeps its actions
    // in the header, on the line of the number.
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });

    expect(
      await within(pageHeader()).findByRole("button", { name: /^confirm/i }),
    ).toBeInTheDocument();
    expect(
      within(pageHeader()).getByRole("button", { name: /^edit/i }),
    ).toBeInTheDocument();
    expect(
      within(pageBody()).queryByRole("button", { name: /^confirm/i }),
    ).not.toBeInTheDocument();
    expect(
      within(pageBody()).queryByText(/^Scheduled:/),
    ).not.toBeInTheDocument();
  });

  it("names the supplier under the number", async () => {
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });

    expect(
      await within(pageHeader()).findByText("ACME Supplies"),
    ).toBeInTheDocument();
  });

  it("lays the details out label over value, as the document detail does", async () => {
    // A label at the left edge and its value at the right one, 1300 px
    // apart at 1440: jsdom has no layout to measure, so this holds the grid
    // the browser check measured.
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });

    const supplier = await screen.findByText("Supplier", { selector: "dt" });
    expect(supplier.closest("dl")).toHaveClass(
      "grid",
      "grid-cols-2",
      "sm:grid-cols-4",
    );
    expect(supplier.parentElement).toHaveTextContent("ACME Supplies");
  });

  it("shows edit button for DRAFT", async () => {
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /edit/i })).toBeInTheDocument();
    });
  });

  it("shows confirm button for DRAFT", async () => {
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /confirm/i }),
      ).toBeInTheDocument();
    });
  });

  it("keeps cancel in the page menu for DRAFT", async () => {
    const user = userEvent.setup();
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });
    await user.click(
      await screen.findByRole("button", { name: /more actions/i }),
    );
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
  });

  it("hides cancel without purchase_orders:manage", async () => {
    mockAuthState.user = {
      role: "user",
      is_superuser: false,
      permissions: ["purchase_orders:read", "purchase_orders:write"],
    };
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText("PO/2026/001")).toBeInTheDocument();
    });
    expect(
      screen.queryByRole("button", { name: /more actions/i }),
    ).not.toBeInTheDocument();
  });

  it("shows cancel to an account holding purchase_orders:manage", async () => {
    mockAuthState.user = {
      role: "user",
      is_superuser: false,
      permissions: [
        "purchase_orders:read",
        "purchase_orders:write",
        "purchase_orders:manage",
      ],
    };
    const user = userEvent.setup();
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });
    await user.click(
      await screen.findByRole("button", { name: /more actions/i }),
    );
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
  });

  it("shows line details", async () => {
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText("Piwo Tyskie")).toBeInTheDocument();
    });
  });

  it("shows no receipts yet for PO without received quantities", async () => {
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText(/no receipts/i)).toBeInTheDocument();
    });
  });

  it("shows linked receipts section for confirmed PO with received quantities", async () => {
    server.use(
      http.get("/api/v1/purchase-orders/po-1", () =>
        HttpResponse.json(confirmedPO),
      ),
      http.get("/api/v1/purchase-orders/po-1/linked-receipts", () =>
        HttpResponse.json(onePage([mockReceipt])),
      ),
    );
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText(/view receipts/i)).toBeInTheDocument();
    });
  });

  it("shows linked receipts section when an in-progress receipt exists without received quantities", async () => {
    // quantity_received stays 0 until a receipt is completed, so the card must
    // look at the linked documents, not the line totals.
    server.use(
      http.get("/api/v1/purchase-orders/po-1", () => HttpResponse.json(mockPO)),
      http.get("/api/v1/purchase-orders/po-1/linked-receipts", () =>
        HttpResponse.json(onePage([mockReceipt])),
      ),
    );
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText(/view receipts/i)).toBeInTheDocument();
    });
  });

  it("shows download PDF button for confirmed PO", async () => {
    server.use(
      http.get("/api/v1/purchase-orders/po-1", () =>
        HttpResponse.json(confirmedPO),
      ),
    );
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /download pdf/i }),
      ).toBeInTheDocument();
    });
  });

  it("receives a confirmed order on the receive screen, which loads its lines", async () => {
    // The order used to build a confirmed receipt in a panel of its own and
    // jump to the documents, where the goods still waited for a second
    // press. The receive screen takes the order's lines and posts them.
    server.use(
      http.get("/api/v1/purchase-orders/po-1", () =>
        HttpResponse.json(confirmedPO),
      ),
    );
    const user = userEvent.setup();
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });

    await user.click(
      await screen.findByRole("button", { name: "Receive delivery" }),
    );

    expect(await screen.findByText("Receive screen")).toBeInTheDocument();
    expect(screen.getByTestId("receive-search")).toHaveTextContent(
      "?order=po-1",
    );
    // Back from there is back to this order.
    expect(screen.getByTestId("receive-back")).toHaveTextContent(
      "/purchase-orders/po-1",
    );
  });

  it("shows send to supplier button for confirmed PO", async () => {
    server.use(
      http.get("/api/v1/purchase-orders/po-1", () =>
        HttpResponse.json(confirmedPO),
      ),
    );
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /send to supplier/i }),
      ).toBeInTheDocument();
    });
  });

  it("hides edit and confirm buttons for confirmed PO", async () => {
    server.use(
      http.get("/api/v1/purchase-orders/po-1", () =>
        HttpResponse.json(confirmedPO),
      ),
    );
    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });
    // The badge, the "Confirmed" metadata row and the axis step all say it
    // since the detail gained a status axis.
    await waitFor(() => {
      expect(screen.getAllByText("Confirmed").length).toBeGreaterThanOrEqual(1);
    });
    expect(
      screen.queryByRole("button", { name: /edit/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /confirm/i }),
    ).not.toBeInTheDocument();
  });

  it("offers a way forward on an order whose approval request was withdrawn", async () => {
    // Withdrawing leaves the PO in PENDING_APPROVAL with nothing pending, and
    // all three offered actions answered 409 — approve and reject found no
    // request, and asking again insisted on DRAFT. The header and the
    // approval slot now read the same requests list.
    enabledModulesMock.value = ["purchase_orders", "approvals"];
    server.use(
      http.get("/api/v1/purchase-orders/po-1", () =>
        HttpResponse.json({ ...mockPO, status: "PENDING_APPROVAL" }),
      ),
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json({
          items: [
            {
              id: "req-1",
              organization_id: "org-1",
              workflow_id: "wf-1",
              target_type: "purchase_order",
              target_id: "po-1",
              status: "CANCELLED",
              current_stage: 1,
              total_stages: 1,
              created_by: "user-1",
              created_by_name: "Alice",
              meta_data: null,
              workflow_stages: [],
              decisions: [],
              created_at: "2026-01-01T00:00:00Z",
            },
          ],
          total: 1,
          limit: 100,
          offset: 0,
          has_more: false,
        }),
      ),
    );

    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });

    expect(
      await within(pageBody()).findByRole("button", {
        name: /request approval/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: /request approval/i }),
    ).toHaveLength(1);
    await userEvent
      .setup()
      .click(
        within(pageHeader()).getByRole("button", { name: /more actions/i }),
      );
    expect(
      screen.getByRole("button", { name: /^cancel/i }),
    ).toBeInTheDocument();
    // Deciding needs a request to decide on.
    expect(
      screen.queryByRole("button", { name: /^approve/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^reject/i }),
    ).not.toBeInTheDocument();
  });

  it("offers no request approval when the engine has no workflow for it", async () => {
    // The header offered the request whenever the module was on; the proxy
    // endpoint then refused with 409 — after the click. The one bit comes
    // from the server, and is readable without `approvals:read`, which this
    // role does not hold: the workflow list answers it nothing at all.
    enabledModulesMock.value = ["purchase_orders", "approvals"];
    server.use(
      http.get("/api/v1/approvals/workflows/configured", () =>
        HttpResponse.json({ configured: false }),
      ),
    );

    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });

    await screen.findByRole("button", { name: /^confirm/i });
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: /request approval/i }),
      ).not.toBeInTheDocument(),
    );
  });

  it("offers the decision while a request is actually pending", async () => {
    enabledModulesMock.value = ["purchase_orders", "approvals"];
    server.use(
      http.get("/api/v1/purchase-orders/po-1", () =>
        HttpResponse.json({ ...mockPO, status: "PENDING_APPROVAL" }),
      ),
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json({
          items: [
            {
              id: "req-1",
              organization_id: "org-1",
              workflow_id: "wf-1",
              target_type: "purchase_order",
              target_id: "po-1",
              status: "PENDING",
              current_stage: 1,
              total_stages: 1,
              created_by: "user-1",
              created_by_name: "Alice",
              meta_data: null,
              workflow_stages: [],
              decisions: [],
              created_at: "2026-01-01T00:00:00Z",
            },
          ],
          total: 1,
          limit: 100,
          offset: 0,
          has_more: false,
        }),
      ),
    );

    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });

    // Once, in the approval card beside the stage it decides — the header
    // offered the same pair a second time.
    expect(
      await within(pageBody()).findByRole("button", { name: /^approve/i }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^approve/i })).toHaveLength(
      1,
    );
    expect(screen.getAllByRole("button", { name: /^reject/i })).toHaveLength(1);
    expect(
      screen.queryByRole("button", { name: /request approval/i }),
    ).not.toBeInTheDocument();
  });

  it("offers the requester no Approve/Reject, in header or slot", async () => {
    // A requester who is also a manager: `canManage` is true, but their own
    // request carries `viewer_can_decide: false`. The header and the slot must
    // agree on hiding the decision the server would answer with 409.
    mockAuthState.user = {
      role: "admin",
      is_superuser: false,
      id: "user-1",
    };
    enabledModulesMock.value = ["purchase_orders", "approvals"];
    server.use(
      http.get("/api/v1/purchase-orders/po-1", () =>
        HttpResponse.json({ ...mockPO, status: "PENDING_APPROVAL" }),
      ),
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json({
          items: [
            {
              id: "req-1",
              organization_id: "org-1",
              workflow_id: "wf-1",
              target_type: "purchase_order",
              target_id: "po-1",
              status: "PENDING",
              current_stage: 1,
              total_stages: 1,
              created_by: "user-1",
              created_by_name: "Alice",
              meta_data: null,
              workflow_stages: [],
              decisions: [],
              created_at: "2026-01-01T00:00:00Z",
              viewer_can_decide: false,
            },
          ],
          total: 1,
          limit: 100,
          offset: 0,
          has_more: false,
        }),
      ),
    );

    render(<PurchaseOrderDetailPage />, { wrapper: createWrapper() });

    await screen.findByText("PO/2026/001");

    // Neither the header nor the slot offers a decision to a viewer who cannot
    // make one. The requester can still withdraw their own request (in the slot).
    expect(
      screen.queryByRole("button", { name: /^approve/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^reject/i }),
    ).not.toBeInTheDocument();
  });
});
