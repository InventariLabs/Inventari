import React from "react";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  useApprovalRequests,
  useRequestApproval,
  useApproveStage,
  useRejectRequest,
  useCancelRequest,
} from "../hooks/useApprovalRequests";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import * as modulesCtx from "@/contexts/ModulesContext";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

beforeEach(() => {
  vi.spyOn(modulesCtx, "useModules").mockReturnValue({
    enabledModules: ["approvals"],
    isModuleEnabled: (name: string) => name === "approvals",
    isLoading: false,
    refreshModules: vi.fn(),
    focusModule: null,
    hiddenModules: [],
  });
});

const mockRequest = {
  id: "req1",
  organization_id: "org1",
  workflow_id: "wf1",
  target_type: "document",
  target_id: "doc1",
  status: "PENDING" as const,
  current_stage: 1,
  total_stages: 2,
  created_by: "u1",
  created_by_name: "Alice",
  meta_data: null,
  workflow_stages: null,
  decisions: [],
  created_at: new Date().toISOString(),
};

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
};

describe("useApprovalRequests", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json({
          items: [mockRequest],
          total: 1,
          limit: 100,
          offset: 0,
          has_more: false,
        }),
      ),
    );
  });

  it("returns request list on success", async () => {
    const { result } = renderHook(() => useApprovalRequests(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toHaveLength(1);
    expect(result.current.data?.items[0].status).toBe("PENDING");
  });

  it("returns error on API failure", async () => {
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json({ detail: "Forbidden" }, { status: 403 }),
      ),
    );
    const { result } = renderHook(() => useApprovalRequests(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it("does not fetch when approvals module is disabled", async () => {
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: [],
      isModuleEnabled: () => false,
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
    const { result } = renderHook(() => useApprovalRequests(), {
      wrapper: createWrapper(),
    });
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("passes filter params to the API", async () => {
    let receivedUrl: URL | undefined;
    server.use(
      http.get("/api/v1/approvals/requests", ({ request }) => {
        receivedUrl = new URL(request.url);
        return HttpResponse.json({
          items: [mockRequest],
          total: 1,
          limit: 100,
          offset: 0,
          has_more: false,
        });
      }),
    );
    const { result } = renderHook(
      () => useApprovalRequests({ target_type: "document", status: "PENDING" }),
      { wrapper: createWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(receivedUrl!.searchParams.get("target_type")).toBe("document");
    expect(receivedUrl!.searchParams.get("status")).toBe("PENDING");
  });
});

describe("useRequestApproval", () => {
  beforeEach(() => {
    server.use(
      http.post("/api/v1/approvals/requests", async ({ request }) => {
        const data = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          { id: "req-new", status: "PENDING", ...data },
          { status: 201 },
        );
      }),
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json({
          items: [mockRequest],
          total: 1,
          limit: 100,
          offset: 0,
          has_more: false,
        }),
      ),
    );
  });

  it("submits an approval request successfully", async () => {
    const { result } = renderHook(() => useRequestApproval(), {
      wrapper: createWrapper(),
    });
    act(() =>
      result.current.mutate({ targetType: "document", targetId: "doc1" }),
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("fails when server rejects the request", async () => {
    server.use(
      http.post("/api/v1/approvals/requests", () =>
        HttpResponse.json(
          { detail: "No workflow configured" },
          { status: 400 },
        ),
      ),
    );
    const { result } = renderHook(() => useRequestApproval(), {
      wrapper: createWrapper(),
    });
    act(() =>
      result.current.mutate({ targetType: "document", targetId: "doc1" }),
    );
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useApproveStage", () => {
  beforeEach(() => {
    server.use(
      http.post("/api/v1/approvals/requests/:id/approve", () =>
        HttpResponse.json({ ...mockRequest, status: "APPROVED" }),
      ),
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json({
          items: [mockRequest],
          total: 1,
          limit: 100,
          offset: 0,
          has_more: false,
        }),
      ),
    );
  });

  it("approves a request successfully", async () => {
    const { result } = renderHook(() => useApproveStage(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate({ id: "req1", notes: "Looks good" }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("fails on server error", async () => {
    server.use(
      http.post("/api/v1/approvals/requests/:id/approve", () =>
        HttpResponse.json({ detail: "Already approved" }, { status: 409 }),
      ),
    );
    const { result } = renderHook(() => useApproveStage(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate({ id: "req1" }));
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useRejectRequest", () => {
  beforeEach(() => {
    server.use(
      http.post("/api/v1/approvals/requests/:id/reject", () =>
        HttpResponse.json({ ...mockRequest, status: "REJECTED" }),
      ),
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json({
          items: [mockRequest],
          total: 1,
          limit: 100,
          offset: 0,
          has_more: false,
        }),
      ),
    );
  });

  it("rejects a request successfully", async () => {
    const { result } = renderHook(() => useRejectRequest(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate({ id: "req1", notes: "Needs revision" }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("fails on server error", async () => {
    server.use(
      http.post("/api/v1/approvals/requests/:id/reject", () =>
        HttpResponse.json({ detail: "Not pending" }, { status: 409 }),
      ),
    );
    const { result } = renderHook(() => useRejectRequest(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate({ id: "req1" }));
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useCancelRequest", () => {
  it("refreshes the document's own approval read, which sits outside the documents prefix", async () => {
    server.use(
      http.post("*/approvals/requests/req1/cancel", () =>
        HttpResponse.json({ ...mockRequest, status: "CANCELLED" }),
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>{children}</BrowserRouter>
      </QueryClientProvider>
    );
    const { result } = renderHook(() => useCancelRequest(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({ id: "req1" });
    });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["document-approval"] });
  });
});

describe("settling a request", () => {
  it.each([
    ["approve", "approve", useApproveStage, { id: "req1" }],
    ["reject", "reject", useRejectRequest, { id: "req1" }],
    ["cancel", "cancel", useCancelRequest, { id: "req1" }],
  ] as const)(
    "refreshes the bell after %s, which clears the request's notices",
    async (_label, action, useHook, vars) => {
      server.use(
        http.post(`*/approvals/requests/req1/${action}`, () =>
          HttpResponse.json(mockRequest),
        ),
      );
      const queryClient = new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      });
      const spy = vi.spyOn(queryClient, "invalidateQueries");
      const wrapper = ({ children }: { children: React.ReactNode }) => (
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>{children}</BrowserRouter>
        </QueryClientProvider>
      );
      const { result } = renderHook(() => useHook(), { wrapper });
      await act(async () => {
        await result.current.mutateAsync(vars);
      });
      expect(spy).toHaveBeenCalledWith({ queryKey: ["notifications"] });
    },
  );
});
