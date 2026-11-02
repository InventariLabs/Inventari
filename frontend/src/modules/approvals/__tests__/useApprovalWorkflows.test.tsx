import React from "react";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  useApprovalWorkflows,
  useCreateWorkflow,
  useUpdateWorkflow,
  useDeleteWorkflow,
} from "../hooks/useApprovalWorkflows";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import * as modulesCtx from "@/contexts/ModulesContext";
import { onePage } from "@/test/mocks/page";

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

const mockWorkflow = {
  id: "wf1",
  organization_id: "org1",
  target_type: "document",
  name: "Document Approval",
  stages: [
    {
      order: 1,
      role: "manager",
      label: "Manager Review",
      approver_user_ids: ["u1"],
    },
  ],
  is_active: true,
  requester_scope: { everyone: true, user_ids: [], role_ids: [] },
  created_at: new Date().toISOString(),
  updated_at: null,
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

describe("useApprovalWorkflows", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([mockWorkflow])),
      ),
    );
  });

  it("returns workflow list on success", async () => {
    const { result } = renderHook(() => useApprovalWorkflows(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].name).toBe("Document Approval");
  });

  it("returns error on API failure", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 }),
      ),
    );
    const { result } = renderHook(() => useApprovalWorkflows(), {
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
    const { result } = renderHook(() => useApprovalWorkflows(), {
      wrapper: createWrapper(),
    });
    expect(result.current.fetchStatus).toBe("idle");
  });
});

describe("useCreateWorkflow", () => {
  beforeEach(() => {
    server.use(
      http.post("/api/v1/approvals/workflows", async ({ request }) => {
        const data = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: "wf-new", ...data }, { status: 201 });
      }),
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([mockWorkflow])),
      ),
    );
  });

  it("creates a workflow successfully", async () => {
    const { result } = renderHook(() => useCreateWorkflow(), {
      wrapper: createWrapper(),
    });
    act(() =>
      result.current.mutate({
        target_type: "document",
        name: "New Workflow",
        stages: [
          {
            order: 1,
            label: "Admin Review",
            approver_user_ids: ["u2"],
          },
        ],
        requester_scope: { everyone: true, user_ids: [], role_ids: [] },
      }),
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.name).toBe("New Workflow");
  });

  it("fails on validation error", async () => {
    server.use(
      http.post("/api/v1/approvals/workflows", () =>
        HttpResponse.json({ detail: "Invalid stages" }, { status: 422 }),
      ),
    );
    const { result } = renderHook(() => useCreateWorkflow(), {
      wrapper: createWrapper(),
    });
    act(() =>
      result.current.mutate({
        // Not a member of the contract's union — the server's refusal is what is under test.
        target_type: "" as never,
        name: "",
        stages: [],
        requester_scope: { everyone: true, user_ids: [], role_ids: [] },
      }),
    );
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useUpdateWorkflow", () => {
  beforeEach(() => {
    server.use(
      http.patch(
        "/api/v1/approvals/workflows/:id",
        async ({ request, params }) => {
          const data = (await request.json()) as Record<string, unknown>;
          const { id: _oldId, ...rest } = mockWorkflow;
          return HttpResponse.json({
            ...rest,
            id: params.id as string,
            ...data,
          });
        },
      ),
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([mockWorkflow])),
      ),
    );
  });

  it("updates a workflow successfully", async () => {
    const { result } = renderHook(() => useUpdateWorkflow(), {
      wrapper: createWrapper(),
    });
    act(() =>
      result.current.mutate({ id: "wf1", data: { name: "Updated Name" } }),
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});

describe("useDeleteWorkflow", () => {
  beforeEach(() => {
    server.use(
      http.delete(
        "/api/v1/approvals/workflows/:id",
        () => new HttpResponse(null, { status: 204 }),
      ),
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
    );
  });

  it("deletes a workflow successfully", async () => {
    const { result } = renderHook(() => useDeleteWorkflow(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate("wf1"));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});
