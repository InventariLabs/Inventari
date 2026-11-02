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

import InventoryPeriodPanel from "@/modules/warehouse/components/InventoryPeriodPanel";
import PutawayRulesPage from "@/modules/warehouse/pages/PutawayRulesPage";
import DocumentsTemplatesPage from "@/modules/warehouse/pages/DocumentsTemplatesPage";
import PricelistPage from "@/modules/purchase_orders/pages/PricelistPage";
import WorkflowSettingsPage from "@/modules/approvals/pages/WorkflowSettingsPage";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useModules: () => ({
    enabledModules: ["warehouse", "purchase_orders", "partners", "approvals"],
    isModuleEnabled: () => true,
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

/**
 * A screen has three different things to say, and these five said one.
 *
 * "Nothing here yet" answers a question about the data. A failed request and a
 * refused one answer questions about the request, and neither of them knows
 * whether anything is there. Rendering all three as the empty state told the
 * accountant no month was closed while eight were, offered to create the ninth
 * putaway rule as if it were the first, and invited a choice of supplier from a
 * list that never arrived.
 *
 * The approvals screen was the worst of them: 403 and 500 both produced "No
 * workflow has been configured yet. Ask someone who can configure workflows to
 * add one." — an instruction whose only possible outcome is a duplicate of one
 * of the two workflows already there.
 */
function PageHeaderHost({ children }: { children: React.ReactNode }) {
  const [data, setData] = React.useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      {data.actions ? (
        <div data-testid="header-actions">{data.actions}</div>
      ) : null}
      {children}
    </PageHeaderContext.Provider>
  );
}

function renderAt(path: string, element: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <PageHeaderHost>
          <Routes>
            <Route path={path} element={element} />
          </Routes>
        </PageHeaderHost>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const ACCOUNT = [
  "warehouse:read",
  "warehouse:write",
  "warehouse:manage",
  "purchase_orders:read",
  "purchase_orders:write",
  "partners:read",
  "approvals:read",
  "approvals:write",
  "locations:read",
];

const answers = (path: string, status: number) =>
  http.get(path, () => new HttpResponse(null, { status }));

interface Surface {
  name: string;
  path: string;
  element: React.ReactNode;
  /** The endpoint whose failure the pass observed. */
  endpoint: string;
  /** What the endpoint returns when there is genuinely nothing. */
  emptyBody: object;
  /** Something only the empty state renders. */
  emptyText: RegExp;
}

const SURFACES: Surface[] = [
  {
    name: "accounting periods",
    path: "/warehouse/periods",
    element: <InventoryPeriodPanel />,
    endpoint: "/api/v1/warehouse/periods",
    emptyBody: onePage([]),
    // The grid itself is the "nothing is closed" picture, so the month names
    // are what must not appear when the year could not be read.
    emptyText: /january/i,
  },
  {
    name: "putaway rules",
    path: "/warehouse/putaway-rules",
    element: <PutawayRulesPage />,
    endpoint: "/api/v1/warehouse/putaway-rules",
    emptyBody: onePage([]),
    emptyText: /no putaway rules yet/i,
  },
  {
    name: "document templates",
    path: "/warehouse/templates",
    element: <DocumentsTemplatesPage />,
    endpoint: "/api/v1/warehouse/templates",
    emptyBody: onePage([]),
    emptyText: /copy one to change how it looks/i,
  },
  {
    name: "supplier price list",
    path: "/purchase-orders/pricelist",
    element: <PricelistPage />,
    endpoint: "/api/v1/partners",
    emptyBody: { items: [], total: 0 },
    emptyText: /pick a supplier/i,
  },
  {
    name: "approval workflows",
    path: "/approvals/workflows",
    element: <WorkflowSettingsPage />,
    endpoint: "/api/v1/approvals/workflows",
    emptyBody: onePage([]),
    emptyText: /no workflows configured/i,
  },
];

beforeEach(() => {
  server.resetHandlers();
  server.use(
    http.get("/api/v1/warehouse/periods", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/warehouse/putaway-rules", () =>
      HttpResponse.json(onePage([])),
    ),
    http.get("/api/v1/warehouse/putaway/home-shelf/silenced", () =>
      HttpResponse.json(onePage([])),
    ),
    http.get("/api/v1/warehouse/templates", () =>
      HttpResponse.json(onePage([])),
    ),
    http.get("/api/v1/warehouse/templates/built-in", () =>
      HttpResponse.json([]),
    ),
    http.get("/api/v1/approvals/workflows", () =>
      HttpResponse.json(onePage([])),
    ),
    http.get("/api/v1/partners", () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
    // A putaway rule needs somewhere to aim at, and that screen says so
    // before it says anything about rules -- so give it one.
    http.get("/api/v1/locations", () =>
      HttpResponse.json(
        onePage([
          {
            id: "loc-1",
            name: "Receiving",
            location_type: "SHELF",
            parent_id: null,
            is_active: true,
          },
        ]),
      ),
    ),
    http.get("/api/v1/items/product-templates/count", () =>
      HttpResponse.json({ count: 0 }),
    ),
    http.get("/api/v1/organizations/members", () => HttpResponse.json([])),
  );
  signInWith(ACCOUNT);
});

afterEach(() => {
  signOut();
});

describe.each(SURFACES)(
  "Trade — $name says which of the three happened",
  ({ path, element, endpoint, emptyBody, emptyText }) => {
    it("shows the empty state when the read succeeds and there is nothing", async () => {
      server.use(http.get(endpoint, () => HttpResponse.json(emptyBody)));
      renderAt(path, element);

      expect(await screen.findByText(emptyText)).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("offers a retry, not an empty state, when the read fails", async () => {
      server.use(answers(endpoint, 500));
      renderAt(path, element);

      expect(await screen.findByRole("alert")).toBeInTheDocument();
      expect(
        await screen.findByRole("button", { name: /try again|retry/i }),
      ).toBeInTheDocument();
      expect(screen.queryByText(emptyText)).not.toBeInTheDocument();
    });

    it("says the account has no access, with no retry, when the read is refused", async () => {
      server.use(answers(endpoint, 403));
      renderAt(path, element);

      expect(
        await screen.findByText(/you do not have access to this/i),
      ).toBeInTheDocument();
      expect(screen.queryByText(emptyText)).not.toBeInTheDocument();
      // Retrying a refusal repeats it; a button that cannot work is a lie.
      expect(
        screen.queryByRole("button", { name: /try again|retry/i }),
      ).not.toBeInTheDocument();
    });
  },
);
