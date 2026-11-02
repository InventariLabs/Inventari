/**
 * The launcher badge is a call to act: "3 approvals waiting", linking into the
 * queue. Offered to someone the API will not let approve, it is a call to a
 * dead end — so the grant decides whether it appears at all.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import * as React from "react";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import * as modulesCtx from "@/contexts/ModulesContext";
import { useApprovalActionItems } from "../hooks/useApprovalActionItems";

/** One client across the test, so the count stays cached between renders. */
function renderItems() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return renderHook(() => useApprovalActionItems(), {
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

beforeEach(() => {
  vi.spyOn(modulesCtx, "useModules").mockReturnValue({
    enabledModules: ["approvals"],
    isModuleEnabled: (name: string) => name === "approvals",
    isLoading: false,
    refreshModules: vi.fn(),
    focusModule: null,
    hiddenModules: [],
  });
  vi.clearAllMocks();
  server.resetHandlers();
  server.use(
    http.get("/api/v1/approvals/requests", () =>
      HttpResponse.json({
        items: [],
        total: 3,
        limit: 100,
        offset: 0,
        has_more: false,
      }),
    ),
  );
});

describe("useApprovalActionItems", () => {
  it("reports the pending count to an approver", async () => {
    signInWith(["approvals:approve"]);

    const { result } = renderItems();

    await waitFor(() => expect(result.current).toHaveLength(1));
    expect(result.current[0].count).toBe(3);
  });

  it("says the queue could not be read instead of reporting nothing waiting", async () => {
    server.use(
      http.get(
        "/api/v1/approvals/requests",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    signInWith(["approvals:approve"]);

    const { result } = renderItems();

    await waitFor(() => expect(result.current).toHaveLength(1));
    expect(result.current[0]).toMatchObject({
      id: "approvals-unavailable",
      severity: "error",
    });
  });

  it("drops the item for a user who cannot decide any of them", async () => {
    // Start from the count already loaded, so the empty result can only come
    // from the permission — not from a query that has yet to resolve.
    signInWith(["approvals:approve"]);
    const { result } = renderItems();
    await waitFor(() => expect(result.current).toHaveLength(1));

    act(() => {
      signInWith(["approvals:read"]);
    });

    await waitFor(() => expect(result.current).toEqual([]));
  });

  it("drops the item when the user signs out", async () => {
    signInWith(["approvals:approve"]);
    const { result } = renderItems();
    await waitFor(() => expect(result.current).toHaveLength(1));

    act(() => {
      signOut();
    });

    await waitFor(() => expect(result.current).toEqual([]));
  });
});

describe("what the badge counts", () => {
  it("asks for every state still awaiting a decision", async () => {
    signInWith(["approvals:approve"]);
    let requestedStatus: string | null = null;
    server.use(
      http.get("/api/v1/approvals/requests", ({ request }) => {
        requestedStatus = new URL(request.url).searchParams.get("status");
        return HttpResponse.json({
          items: [],
          total: 2,
          limit: 100,
          offset: 0,
          has_more: false,
        });
      }),
    );

    const { result } = renderItems();

    await waitFor(() => expect(result.current).toHaveLength(1));
    // A request part-way through a multi-stage workflow is IN_PROGRESS and
    // still waiting on someone — counting PENDING alone hid it.
    expect(requestedStatus).toBe("PENDING,IN_PROGRESS");
    expect(result.current[0].linkTo).toBe(
      "/approvals?status=PENDING,IN_PROGRESS",
    );
  });
});
