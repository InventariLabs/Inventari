/**
 * The launcher tile says what the overview it opens says: the tile reads the
 * heading's own number, narrowed by the organization's "show module data"
 * setting the way the heading and its rows are.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import * as React from "react";

import { server } from "@/test/mocks/server";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { useAuthStore } from "@/store/authStore";
import { useInventoryStatusBadge } from "./useInventoryStatusBadge";

function renderBadge() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return renderHook(() => useInventoryStatusBadge(), {
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>
        <ModulesProvider>{children}</ModulesProvider>
      </QueryClientProvider>
    ),
  });
}

function serve(showModuleData: boolean) {
  const asked: (string | null)[] = [];
  server.use(
    http.get("/api/v1/organizations/my", () =>
      HttpResponse.json({
        id: "1",
        name: "Test Organization",
        settings: { show_module_data: showModuleData },
      }),
    ),
    // Module-owned products drop out of the count when module data is hidden.
    http.get("/api/v1/items/attention-counts", ({ request }) => {
      const flag = new URL(request.url).searchParams.get(
        "exclude_module_contexts",
      );
      asked.push(flag);
      return HttpResponse.json({
        expired: 0,
        expiring_soon: 0,
        low_stock: 1,
        records: flag === "true" ? 2 : 3,
      });
    }),
  );
  return asked;
}

beforeEach(() => {
  useAuthStore.setState({ isAuthenticated: true, isLoading: false });
  server.resetHandlers();
});

describe("useInventoryStatusBadge", () => {
  it("counts what the heading counts when module data is hidden", async () => {
    const asked = serve(false);

    const { result } = renderBadge();

    await waitFor(() => expect(result.current).not.toBeNull());
    expect(result.current?.count).toBe(2);
    expect(asked).toContain("true");
  });

  it("counts every record behind the heading when module data is shown", async () => {
    serve(true);

    const { result } = renderBadge();

    await waitFor(() => expect(result.current?.count).toBe(3));
  });
});
