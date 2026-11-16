import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import { signInWith } from "@/test/auth";
import ProductionPlanPage from "./ProductionPlanPage";

const list = vi.fn();
vi.mock("@/modules/maker/api/production", () => ({
  productionApi: { list: (params: unknown) => list(params) },
}));
vi.mock("@/modules/maker/api/planning", () => ({
  planningApi: {
    needs: vi.fn(async () => ({
      rows: [],
      purchasing: false,
      run_count: 0,
      unmeasured: [],
    })),
  },
}));

describe("ProductionPlanPage", () => {
  beforeEach(() => {
    signInWith(["maker:write"]);
    list.mockReset();
    list.mockResolvedValue({
      items: [],
      total: 0,
      limit: 200,
      offset: 0,
      has_more: false,
    });
  });

  it("asks for the runs planned in the period, not those made in it", async () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <PageHeaderContext.Provider
        value={{ data: {}, setHeader: (_data: PageHeaderData) => undefined }}
      >
        <QueryClientProvider client={qc}>
          <MemoryRouter>
            <ProductionPlanPage />
          </MemoryRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    await waitFor(() => expect(list).toHaveBeenCalled());
    const params = list.mock.calls[0][0];
    // Runs are made today and planned for another week: filtering on the
    // creation date shows an empty calendar over a needs list that counts them.
    expect(params.planned_from).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(params.planned_to).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(params.date_from).toBeUndefined();
    expect(params.date_to).toBeUndefined();
  });
});
