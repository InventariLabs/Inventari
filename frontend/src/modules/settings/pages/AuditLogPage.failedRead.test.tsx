import axios from "axios";
import { render, screen } from "@/test/utils";
import { describe, it, expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import AuditLogPage from "./AuditLogPage";

const row = {
  id: "a1",
  organization_id: "o1",
  user_id: "u1",
  user_email: "admin@example.com",
  action: "CREATE",
  target_type: "partner",
  target_id: "7d6f4bf7-1111-2222-3333-444455556666",
  snapshot: { name: "Acme" },
  reason: null,
  meta_data: null,
  created_at: "2026-08-20T10:00:00Z",
};

/**
 * A query that fails to refresh keeps the rows it already has, so the page
 * holds both the old data and the error: the error card replaces the rows,
 * and the footer must not go on counting them.
 */
vi.mock("@/modules/settings/hooks/useAuditLog", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/modules/settings/hooks/useAuditLog")
  >()),
  useAuditLog: () => ({
    data: { items: [row], total: 40, limit: 100, offset: 0, has_more: false },
    isLoading: false,
    isError: true,
    error: new axios.AxiosError(),
    isPlaceholderData: false,
    refetch: vi.fn(),
  }),
}));

describe("AuditLogPage — a refresh that failed", () => {
  it("drops the row count and the pager along with the rows", async () => {
    server.use(
      http.get("/api/v1/audit-log/target-types", () => HttpResponse.json([])),
    );
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: vi.fn() }}>
        <AuditLogPage />
      </PageHeaderContext.Provider>,
    );

    expect(
      (await screen.findAllByText("Cannot reach the server")).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText("40")).not.toBeInTheDocument();
    expect(screen.queryByText("Showing")).not.toBeInTheDocument();
  });
});
