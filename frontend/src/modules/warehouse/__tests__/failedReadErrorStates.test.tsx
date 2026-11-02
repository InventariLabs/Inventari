import React from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";

import ReorderRulesPage from "@/modules/purchase_orders/pages/ReorderRulesPage";
import LinkedReceiptsPage from "@/modules/purchase_orders/pages/LinkedReceiptsPage";
import DocumentApprovalsPage from "@/modules/warehouse/pages/DocumentApprovalsPage";
import ApprovalsDashboard from "@/modules/approvals/pages/ApprovalsDashboard";
import { MakerSettingsPanel } from "@/modules/maker/components/MakerSettingsPanel";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useModules: () => ({
    enabledModules: ["warehouse", "purchase_orders", "approvals", "maker"],
    isModuleEnabled: () => true,
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

/**
 * Four ways a screen described a failed or refused read as something else.
 *
 * These are not the `data = []` shape three modules already lost — each one
 * fails differently, which is why the earlier fix did not reach them. The
 * replenishment page printed "0 rules" beside "11 products below minimum
 * stock", the two halves having been fetched separately and only one of them
 * having failed. The linked-receipts route answered a 500 with "Purchase
 * order not found" — a claim about the reader's data where the truth was
 * about the server, and on one of two routes to the same record. The
 * production settings panel used `!settings` as a stand-in for "still
 * loading", so a failed read left the loading card on screen for ever. And
 * both approval queues promised an account with no `approvals:approve` that
 * things it may approve would appear here, which the server guarantees they
 * never will.
 */
function PageHeaderHost({ children }: { children: React.ReactNode }) {
  const [data, setData] = React.useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      {children}
    </PageHeaderContext.Provider>
  );
}

function renderAt(path: string, route: string, element: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <PageHeaderHost>
          <Routes>
            <Route path={route} element={element} />
          </Routes>
        </PageHeaderHost>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const DECIDER = [
  "warehouse:read",
  "warehouse:write",
  "purchase_orders:read",
  "purchase_orders:write",
  "partners:read",
  "locations:read",
  "maker:read",
  "maker:write",
  // Module settings are the manager's configuration, so the panel — and its
  // failed-read state — sit behind maker:manage.
  "maker:manage",
  "approvals:read",
  "approvals:approve",
];

const READER = DECIDER.filter((p) => p !== "approvals:approve");

const fails = (path: string, status = 500) =>
  http.get(path, () => new HttpResponse(null, { status }));

beforeEach(() => {
  server.resetHandlers();
  server.use(
    http.get("/api/v1/purchase-orders/reorder-rules", () =>
      HttpResponse.json([]),
    ),
    http.get("/api/v1/purchase-orders/replenishment/alerts", () =>
      HttpResponse.json(onePage([])),
    ),
    http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/partners", () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
    http.get("/api/v1/items/product-templates/count", () =>
      HttpResponse.json({ count: 3 }),
    ),
    http.get("/api/v1/warehouse/awaiting-my-approval", () =>
      HttpResponse.json({ documents: [], total: 0 }),
    ),
    http.get("/api/v1/approvals/requests", () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
    http.get("/api/v1/maker/settings", () =>
      HttpResponse.json({
        reference_direction: "SAVINGS",
        allow_overproduction: true,
        availability_check_scope: "GLOBAL",
        create_on_shortage_strategy: "ALLOW",
      }),
    ),
  );
});

afterEach(() => {
  signOut();
});

describe("replenishment rules — one half failing does not speak for the whole", () => {
  const ALERTS = [
    {
      reorder_rule_id: "rule-1",
      product_template_id: "tpl-1",
      product_name: "Flour",
      sku: "ING-1",
      location_id: "loc-1",
      available_quantity: 2,
      min_quantity: 10,
      max_quantity: 40,
      safety_stock: 5,
      shortage: 8,
      suggested_reorder_quantity: 38,
      reserve_available_quantity: 38,
      proposed_move_quantity: 38,
      remaining_to_buy: 0,
    },
  ];

  it("withholds the rule count when the rules could not be read", async () => {
    signInWith(DECIDER);
    server.use(
      fails("/api/v1/purchase-orders/reorder-rules"),
      http.get("/api/v1/purchase-orders/replenishment/alerts", () =>
        HttpResponse.json(onePage(ALERTS)),
      ),
    );
    renderAt(
      "/purchase-orders/reorder-rules",
      "/purchase-orders/reorder-rules",
      <ReorderRulesPage />,
    );

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    // "0 rules" beside a live alert count is the contradiction; the count of
    // a list nobody read is what has to go.
    expect(screen.queryByText(/\b0\b/)).not.toBeInTheDocument();
  });

  it("keeps the alerts, which came back on their own request", async () => {
    signInWith(DECIDER);
    server.use(
      fails("/api/v1/purchase-orders/reorder-rules"),
      http.get("/api/v1/purchase-orders/replenishment/alerts", () =>
        HttpResponse.json(onePage(ALERTS)),
      ),
    );
    renderAt(
      "/purchase-orders/reorder-rules",
      "/purchase-orders/reorder-rules",
      <ReorderRulesPage />,
    );

    expect(await screen.findByText(/flour/i)).toBeInTheDocument();
  });
});

describe("linked receipts — a failed read is not a missing order", () => {
  const PO = {
    id: "po-1",
    number: "PO/2026/1",
    status: "CONFIRMED",
    lines: [],
    partner_id: null,
  };

  it("offers a retry when the order could not be read", async () => {
    signInWith(DECIDER);
    server.use(
      fails("/api/v1/purchase-orders/po-1"),
      http.get("/api/v1/purchase-orders/po-1/linked-receipts", () =>
        HttpResponse.json([]),
      ),
    );
    renderAt(
      "/purchase-orders/po-1/linked-receipts",
      "/purchase-orders/:id/linked-receipts",
      <LinkedReceiptsPage />,
    );

    expect(
      await screen.findByRole("button", { name: /try again|retry/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/not found/i)).not.toBeInTheDocument();
  });

  it("says the order is not there, with a way back, on a real 404", async () => {
    signInWith(DECIDER);
    server.use(
      fails("/api/v1/purchase-orders/po-1", 404),
      http.get("/api/v1/purchase-orders/po-1/linked-receipts", () =>
        HttpResponse.json([]),
      ),
    );
    renderAt(
      "/purchase-orders/po-1/linked-receipts",
      "/purchase-orders/:id/linked-receipts",
      <LinkedReceiptsPage />,
    );

    expect(await screen.findByText(/not found/i)).toBeInTheDocument();
    // Retrying a 404 walks the reader back into the same wall.
    expect(
      screen.queryByRole("button", { name: /try again|retry/i }),
    ).not.toBeInTheDocument();
  });

  it("renders the receipts when everything is fine", async () => {
    signInWith(DECIDER);
    server.use(
      http.get("/api/v1/purchase-orders/po-1", () => HttpResponse.json(PO)),
      http.get("/api/v1/purchase-orders/po-1/linked-receipts", () =>
        HttpResponse.json([]),
      ),
    );
    renderAt(
      "/purchase-orders/po-1/linked-receipts",
      "/purchase-orders/:id/linked-receipts",
      <LinkedReceiptsPage />,
    );

    expect((await screen.findAllByText(/PO\/2026\/1/)).length).toBeGreaterThan(
      0,
    );
  });
});

describe("production settings — a failed read is not a slow one", () => {
  it("stops waiting and says what happened", async () => {
    signInWith(DECIDER);
    server.use(fails("/api/v1/maker/settings"));
    renderAt("/maker/settings", "/maker/settings", <MakerSettingsPanel />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: /try again|retry/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/loading order/i)).not.toBeInTheDocument();
  });
});

describe("approval queues — an empty state that can never fill", () => {
  it("tells an account that cannot approve why the documents queue is empty", async () => {
    signInWith(READER);
    renderAt(
      "/warehouse/approvals",
      "/warehouse/approvals",
      <DocumentApprovalsPage />,
    );

    expect(
      await screen.findByText(/cannot|not something/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/warehouse you can approve or reject appear here/i),
    ).not.toBeInTheDocument();
  });

  it("keeps the ordinary empty state for an account that can approve", async () => {
    signInWith(DECIDER);
    renderAt(
      "/warehouse/approvals",
      "/warehouse/approvals",
      <DocumentApprovalsPage />,
    );

    expect(
      await screen.findByText(/no documents awaiting your approval/i),
    ).toBeInTheDocument();
  });

  it("does not promise other people's requests on the approvals dashboard", async () => {
    signInWith(READER);
    renderAt("/approvals", "/approvals", <ApprovalsDashboard />);

    expect(
      await screen.findByText(/nothing of yours is waiting/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/will appear here when users request approval/i),
    ).not.toBeInTheDocument();
  });
});
