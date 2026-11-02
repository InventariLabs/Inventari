import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

import DocumentsPage from "@/modules/warehouse/pages/DocumentsPage";
import { onePage } from "@/test/mocks/page";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { documentRow } from "@/test/factories/documents";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useModules: () => ({
    enabledModules: ["warehouse", "partners"],
    isModuleEnabled: () => true,
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

// The row's amount follows the profile as well as the document, and this
// spec is about filtering — the profile only has to be there.
vi.mock("@/modules/warehouse/hooks/useDocumentProfile", () => ({
  useDocumentProfile: () => ({ data: { value_tracking_enabled: true } }),
}));

/**
 * A list that found nothing and a shelf that holds nothing are two different
 * answers, and this screen gave the second one to both. Over forty-nine
 * documents a search replied "No documents yet. Create your first warehouse
 * document to track goods movement" — a false diagnosis and, for a read-only
 * account, a prescription it is not allowed to fill.
 */
function PageHeaderHost({ children }: { children: React.ReactNode }) {
  const [data, setData] = React.useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      {children}
    </PageHeaderContext.Provider>
  );
}

const SHELF = [
  {
    id: "doc-1",
    organization_id: "org-1",
    type: "IN",
    number: "IN/2026/024",
    status: "COMPLETED",
    partner_id: "p-1",
    partner_snapshot: { name: "Nowak" },
    corrects_document_id: null,
    source_location_id: null,
    target_location_id: null,
    scheduled_date: null,
    notes: null,
    external_reference: null,
    lines: [],
    created_at: "2026-03-04T09:00:00Z",
    updated_at: "2026-03-04T09:00:00Z",
  },
];

/** What the list request was asked for, in order. */
let requestedQueries: URLSearchParams[] = [];

function renderList() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/warehouse"]}>
        <PageHeaderHost>
          <Routes>
            <Route path="/warehouse" element={<DocumentsPage />} />
          </Routes>
        </PageHeaderHost>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  requestedQueries = [];
  server.resetHandlers();
  server.use(
    // The shelf holds one document and the server finds nothing for a
    // narrowed request — the shape the report was written from.
    http.get("/api/v1/warehouse/documents", ({ request }) => {
      const params = new URL(request.url).searchParams;
      requestedQueries.push(params);
      const narrowed = params.get("search") || params.get("date_from");
      // The list answers with rows, built from the documents as the server
      // builds them.
      const items = narrowed
        ? []
        : SHELF.map((d) => documentRow(d as unknown as WarehouseDocument));
      return HttpResponse.json({
        items,
        total: items.length,
        offset: 0,
        limit: 50,
      });
    }),
    http.get("/api/v1/partners", () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
    http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
  );
  signInWith(["warehouse:read", "warehouse:write"]);
});

afterEach(() => {
  signOut();
});

describe("Documents list — the two empties are told apart", () => {
  it("says nothing matched, and offers the way back", async () => {
    const user = userEvent.setup();
    renderList();
    expect(await screen.findByText("IN/2026/024")).toBeInTheDocument();

    const search = screen.getAllByPlaceholderText(/search by number/i)[0]!;
    await user.type(search, "Kowalski");

    expect(
      await screen.findByText(/no documents match the filter/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/create your first warehouse document/i),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /clear filters/i }));
    expect(await screen.findByText("IN/2026/024")).toBeInTheDocument();
  });

  it("names the partner among the things the search field looks at", async () => {
    renderList();
    await screen.findByText("IN/2026/024");
    // The hint has to agree with what the field does. It promised number and
    // reference, and the partner printed on every row was the one thing the
    // search would not accept.
    expect(
      screen.getAllByPlaceholderText(/search by number, reference, partner/i)
        .length,
    ).toBeGreaterThan(0);
  });

  it("asks the server for a date range once the reader picks one", async () => {
    const user = userEvent.setup();
    renderList();
    await screen.findByText("IN/2026/024");

    // The range lives behind the filter toggle, as the register's does.
    await user.click(screen.getAllByRole("button", { name: /filters/i })[0]!);
    const from = screen.getAllByLabelText(/^from$/i)[0]!;
    await user.click(from);

    // Day cells are labelled with the full date, not the numeral.
    const days = await screen.findAllByRole("button", { name: /2026/ });
    await user.click(days[0]!);

    await waitFor(() =>
      expect(requestedQueries.some((q) => q.get("date_from"))).toBe(true),
    );
  });
});
