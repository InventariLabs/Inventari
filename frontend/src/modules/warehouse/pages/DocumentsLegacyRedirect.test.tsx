import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { onePage } from "@/test/mocks/page";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import DocumentsLegacyRedirect from "./DocumentsLegacyRedirect";
import DocumentsPage from "./DocumentsPage";
import DocumentHistoryPage from "./DocumentHistoryPage";

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

vi.mock("@/modules/warehouse/hooks/useDocumentProfile", () => ({
  useDocumentProfile: () => ({ data: { value_tracking_enabled: true } }),
}));

function PageHeaderHost({ children }: { children: React.ReactNode }) {
  const [data, setData] = React.useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      {children}
    </PageHeaderContext.Provider>
  );
}

function Landed() {
  const { pathname, search, hash } = useLocation();
  return <div data-testid="landed">{`${pathname}${search}${hash}`}</div>;
}

function renderAt(address: string) {
  return render(
    <MemoryRouter initialEntries={[address]}>
      <Routes>
        <Route path="/warehouse" element={<DocumentsLegacyRedirect />} />
        <Route
          path="/warehouse/profile"
          element={<DocumentsLegacyRedirect />}
        />
        <Route path="/warehouse/history" element={<Landed />} />
        <Route path="/warehouse/settings" element={<Landed />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("DocumentsLegacyRedirect", () => {
  it("sends the old document list to History", () => {
    renderAt("/warehouse");

    expect(screen.getByTestId("landed")).toHaveTextContent(
      "/warehouse/history",
    );
  });

  it("sends the old profile tab to Configuration, query and hash kept", () => {
    renderAt("/warehouse/profile?tab=x#numbering");

    expect(screen.getByTestId("landed")).toHaveTextContent(
      "/warehouse/settings?tab=x#numbering",
    );
  });
});

/**
 * An old bookmark or emailed link to one partner's documents used to land on
 * History with the partner carried in the address — and History reads no
 * filter, so it opened every movement of the warehouse. The screens here are
 * the real ones the module routes to: whichever the redirect picks, the
 * documents it asks the server for have to be that partner's.
 */
describe("DocumentsLegacyRedirect — a filtered bookmark", () => {
  let requested: URLSearchParams[] = [];

  beforeEach(() => {
    requested = [];
    server.use(
      http.get("/api/v1/warehouse/documents", ({ request }) => {
        requested.push(new URL(request.url).searchParams);
        return HttpResponse.json({ items: [], total: 0, offset: 0, limit: 50 });
      }),
      http.get("/api/v1/partners", () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
      http.get("/api/v1/partners/p1", () =>
        HttpResponse.json({ id: "p1", name: "Nowak" }),
      ),
      http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
    );
    signInWith(["warehouse:read", "warehouse:write"]);
  });

  afterEach(() => {
    signOut();
  });

  it("asks only for that partner's documents", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/warehouse?partner_id=p1"]}>
          <PageHeaderHost>
            <Routes>
              <Route path="/warehouse" element={<DocumentsLegacyRedirect />} />
              <Route path="/warehouse/all" element={<DocumentsPage />} />
              <Route
                path="/warehouse/history"
                element={<DocumentHistoryPage />}
              />
            </Routes>
          </PageHeaderHost>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => expect(requested.length).toBeGreaterThan(0));
    expect(requested.every((q) => q.get("partner_id") === "p1")).toBe(true);
  });
});
