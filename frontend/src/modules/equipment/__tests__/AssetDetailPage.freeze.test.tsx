import React, { useRef, useState } from "react";
import { render, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";

import AssetDetailPage from "../pages/AssetDetailPage";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const ITEM_ID = "ec6be09a-90ba-449d-a45b-6217ef627d37";

const mockItem = {
  id: ITEM_ID,
  name: "Dell Latitude 5520",
  brand: "Dell",
  barcode: "SN-123",
  status: "ACTIVE",
  category_id: "cat-1",
  location_id: "loc-1",
  context_tag: "equipment",
  quantity: 1,
  added_date: "2024-01-01T00:00:00Z",
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
  metadata: {
    equipment: {
      equipment_status: "AVAILABLE",
      serial_number: "SN-123",
    },
  },
};

/**
 * Mirrors how ModuleShell provides the page header: the useState setter is
 * passed directly as `setHeader` so it keeps a STABLE identity across renders
 * (a new function literal here would itself cause re-renders and mask the bug).
 *
 * `Commits` counts how often the provider's `data` actually changes — i.e. how
 * many times setHeader committed a new value. A healthy mount commits a small
 * constant number of times; the regression (a non-memoized object in the page's
 * useEffect deps) drives this into the hundreds.
 */
function PageHeaderHost({
  onCommits,
  children,
}: {
  onCommits: (n: number) => void;
  children: React.ReactNode;
}) {
  const [data, setData] = useState<PageHeaderData>({});
  // Count commits WITHOUT introducing extra renders: a ref-based counter that
  // we bump only when `data` reference actually changes (guarded by a prev-ref).
  // The setHeader identity stays the stable useState setter, matching ModuleShell.
  const countRef = useRef(0);
  const prevRef = useRef<PageHeaderData>({});
  if (data !== prevRef.current) {
    countRef.current += 1;
    prevRef.current = data;
    onCommits(countRef.current);
  }
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      {children}
    </PageHeaderContext.Provider>
  );
}

function renderPage(onCommits: (n: number) => void) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter initialEntries={[`/equipment/${ITEM_ID}`]}>
          <PageHeaderHost onCommits={onCommits}>
            <Routes>
              <Route path="/equipment/:id" element={children} />
            </Routes>
          </PageHeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
  return render(<AssetDetailPage />, { wrapper });
}

describe("AssetDetailPage — freeze regression (useEffect deps)", () => {
  beforeEach(() => {
    server.resetHandlers();
    server.use(
      http.get(`/api/v1/items/${ITEM_ID}`, () => HttpResponse.json(mockItem)),
      // approval-status: a workflow exists but no request yet — this exercises
      // the approvalStatus branch in the header effect.
      http.get(`/api/v1/equipment/${ITEM_ID}/approval-status`, () =>
        HttpResponse.json({
          has_workflow: true,
          request_id: null,
          status: null,
        }),
      ),
      http.get(`/api/v1/equipment/${ITEM_ID}/valuation`, () =>
        HttpResponse.json({}),
      ),
      http.get(`/api/v1/equipment/${ITEM_ID}/attachments`, () =>
        HttpResponse.json(onePage([])),
      ),
    );
  });

  it("settles the header effect in a bounded number of commits (no infinite loop)", async () => {
    let maxCommits = 0;
    renderPage((n) => {
      maxCommits = Math.max(maxCommits, n);
    });

    // Wait for the item to load and the header effect to run with the title.
    await waitFor(
      () => {
        expect(maxCommits).toBeGreaterThan(0);
      },
      { timeout: 3000 },
    );

    // Grace window for any straggler renders to settle — wrapped in act() so
    // deferred Radix Select/Tabs mount effects and the setHeader effect flush
    // inside an act boundary instead of leaking as warnings.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 500));
    });

    // A healthy mount commits a small constant number of times. The buggy
    // version (requestApprovalMutation in the deps array) committed 100+ times
    // because the useMutation result is a new reference every render.
    // 20 is a generous upper bound well below the runaway threshold.
    expect(maxCommits).toBeLessThan(20);
  });
});
