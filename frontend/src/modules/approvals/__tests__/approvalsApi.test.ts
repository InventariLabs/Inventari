import { describe, it, expect, vi, beforeEach } from "vitest";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import {
  approvalsApi,
  type WorkflowCreateInput,
  type WorkflowUpdateInput,
} from "../api/approvals";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const baseWorkflow = {
  id: "wf-1",
  organization_id: "org-1",
  target_type: "document",
  name: "Test Workflow",
  stages: [
    {
      order: 1,
      role: "manager",
      label: "Manager",
      approver_user_ids: ["user-1"],
    },
  ],
  is_active: true,
  requester_scope: { everyone: true, user_ids: [], role_ids: [] },
  created_at: "2026-01-01T00:00:00Z",
  updated_at: null,
};

const baseRequest = {
  id: "req-1",
  organization_id: "org-1",
  workflow_id: "wf-1",
  target_type: "document",
  target_id: "doc-1",
  status: "PENDING" as const,
  current_stage: 1,
  total_stages: 1,
  created_by: "user-1",
  created_by_name: "Alice",
  meta_data: null,
  workflow_stages: null,
  decisions: [],
  created_at: "2026-01-01T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("approvalsApi.listWorkflows", () => {
  it("returns workflow list from GET /approvals/workflows", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([baseWorkflow])),
      ),
    );
    const result = await approvalsApi.listWorkflows();
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("wf-1");
  });

  it("propagates server errors", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json({ detail: "Forbidden" }, { status: 403 }),
      ),
    );
    await expect(approvalsApi.listWorkflows()).rejects.toBeDefined();
  });
});

describe("approvalsApi.createWorkflow", () => {
  it("POSTs to /approvals/workflows and returns the new workflow", async () => {
    let receivedBody: unknown = null;
    server.use(
      http.post("/api/v1/approvals/workflows", async ({ request }) => {
        receivedBody = await request.json();
        return HttpResponse.json(
          { ...baseWorkflow, ...(receivedBody as object) },
          { status: 201 },
        );
      }),
    );
    const payload: WorkflowCreateInput = {
      target_type: "document",
      name: "New",
      stages: [
        {
          order: 1,
          label: "Admin",
          approver_user_ids: [],
        },
      ],
      is_active: true,
      requester_scope: { everyone: true, user_ids: [], role_ids: [] },
    };
    const result = await approvalsApi.createWorkflow(payload);
    expect(result.name).toBe("New");
    expect(receivedBody).toEqual(payload);
  });

  it("omits is_active from the body when not provided", async () => {
    let receivedBody: Record<string, unknown> | null = null;
    server.use(
      http.post("/api/v1/approvals/workflows", async ({ request }) => {
        receivedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(baseWorkflow, { status: 201 });
      }),
    );
    await approvalsApi.createWorkflow({
      target_type: "document",
      name: "X",
      stages: [{ order: 1, label: "M", approver_user_ids: [] }],
      requester_scope: { everyone: true, user_ids: [], role_ids: [] },
    });
    // The client forwards the payload as-is; the server's default for
    // ``is_active`` applies because the key is not present in the body.
    expect("is_active" in (receivedBody ?? {})).toBe(false);
  });
});

describe("approvalsApi.updateWorkflow", () => {
  it("PATCHes /approvals/workflows/{id} with provided data", async () => {
    let receivedBody: unknown = null;
    let receivedUrl = "";
    server.use(
      http.patch(
        "/api/v1/approvals/workflows/:id",
        async ({ request, params }) => {
          receivedUrl = `/api/v1/approvals/workflows/${params.id}`;
          receivedBody = await request.json();
          return HttpResponse.json({
            ...baseWorkflow,
            ...(receivedBody as object),
          });
        },
      ),
    );
    const update: WorkflowUpdateInput = { name: "Renamed" };
    const result = await approvalsApi.updateWorkflow("wf-1", update);
    expect(result.name).toBe("Renamed");
    expect(receivedUrl).toBe("/api/v1/approvals/workflows/wf-1");
    expect(receivedBody).toEqual(update);
  });

  it("supports partial updates (only is_active)", async () => {
    let receivedBody: Record<string, unknown> | null = null;
    server.use(
      http.patch("/api/v1/approvals/workflows/:id", async ({ request }) => {
        receivedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...baseWorkflow, is_active: false });
      }),
    );
    await approvalsApi.updateWorkflow("wf-1", { is_active: false });
    expect(receivedBody).toEqual({ is_active: false });
  });
});

describe("approvalsApi.deleteWorkflow", () => {
  it("DELETEs /approvals/workflows/{id} and reports what happened", async () => {
    let receivedMethod = "";
    let receivedUrl = "";
    server.use(
      http.delete("/api/v1/approvals/workflows/:id", ({ request, params }) => {
        receivedMethod = request.method;
        receivedUrl = `/api/v1/approvals/workflows/${params.id}`;
        return HttpResponse.json({ archived: false, requests_kept: 0 });
      }),
    );
    // A workflow with history is archived instead of deleted, and the caller
    // has to know which so the toast can say it.
    await expect(approvalsApi.deleteWorkflow("wf-1")).resolves.toEqual({
      archived: false,
      requests_kept: 0,
    });
    expect(receivedMethod).toBe("DELETE");
    expect(receivedUrl).toBe("/api/v1/approvals/workflows/wf-1");
  });

  it("passes the archive outcome through", async () => {
    server.use(
      http.delete("/api/v1/approvals/workflows/:id", () =>
        HttpResponse.json({ archived: true, requests_kept: 4 }),
      ),
    );
    await expect(approvalsApi.deleteWorkflow("wf-1")).resolves.toEqual({
      archived: true,
      requests_kept: 4,
    });
  });

  it("surfaces 404 errors as rejected promise", async () => {
    server.use(
      http.delete("/api/v1/approvals/workflows/:id", () =>
        HttpResponse.json({ detail: "WORKFLOW_NOT_FOUND" }, { status: 404 }),
      ),
    );
    await expect(approvalsApi.deleteWorkflow("missing")).rejects.toBeDefined();
  });
});

describe("approvalsApi.listRequests", () => {
  it("passes filter params as query string", async () => {
    let receivedUrl: URL | undefined;
    server.use(
      http.get("/api/v1/approvals/requests", ({ request }) => {
        receivedUrl = new URL(request.url);
        return HttpResponse.json({
          items: [baseRequest],
          total: 1,
          limit: 100,
          offset: 0,
          has_more: false,
        });
      }),
    );
    await approvalsApi.listRequests({
      target_type: "document",
      status: "PENDING",
    });
    expect(receivedUrl?.searchParams.get("target_type")).toBe("document");
    expect(receivedUrl?.searchParams.get("status")).toBe("PENDING");
  });

  it("does not add params when no filters supplied", async () => {
    let receivedUrl: URL | undefined;
    server.use(
      http.get("/api/v1/approvals/requests", ({ request }) => {
        receivedUrl = new URL(request.url);
        return HttpResponse.json({
          items: [],
          total: 0,
          limit: 100,
          offset: 0,
          has_more: false,
        });
      }),
    );
    await approvalsApi.listRequests();
    expect(receivedUrl?.search).toBe("");
  });
});

describe("approvalsApi.getRequest", () => {
  it("fetches a single request by id", async () => {
    let receivedUrl = "";
    server.use(
      http.get("/api/v1/approvals/requests/:id", ({ params }) => {
        receivedUrl = `/api/v1/approvals/requests/${params.id}`;
        return HttpResponse.json(baseRequest);
      }),
    );
    const result = await approvalsApi.getRequest("req-1");
    expect(result.id).toBe("req-1");
    expect(receivedUrl).toBe("/api/v1/approvals/requests/req-1");
  });
});

describe("approvalsApi.requestApproval", () => {
  it("POSTs the target_type and target_id as JSON body", async () => {
    let receivedBody: Record<string, unknown> | null = null;
    server.use(
      http.post("/api/v1/approvals/requests", async ({ request }) => {
        receivedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          { ...baseRequest, status: "PENDING" },
          { status: 201 },
        );
      }),
    );
    const result = await approvalsApi.requestApproval("document", "doc-42");
    expect(result.status).toBe("PENDING");
    expect(receivedBody).toEqual({
      target_type: "document",
      target_id: "doc-42",
    });
  });
});

describe("approvalsApi.approveStage", () => {
  it("POSTs notes (or undefined) to /approve endpoint", async () => {
    let receivedBody: Record<string, unknown> | null = null;
    server.use(
      http.post(
        "/api/v1/approvals/requests/:id/approve",
        async ({ request }) => {
          receivedBody = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({ ...baseRequest, status: "APPROVED" });
        },
      ),
    );
    const withNotes = await approvalsApi.approveStage("req-1", "Looks good");
    expect(withNotes.status).toBe("APPROVED");
    expect(receivedBody).toEqual({ notes: "Looks good" });

    const withoutNotes = await approvalsApi.approveStage("req-1");
    expect(withoutNotes.status).toBe("APPROVED");
    // When notes is undefined, axios serializes the key with null value.
    // We just assert that the request completed.
  });

  it("returns 404 error when request is missing", async () => {
    server.use(
      http.post("/api/v1/approvals/requests/:id/approve", () =>
        HttpResponse.json(
          { detail: "APPROVAL_REQUEST_NOT_FOUND" },
          { status: 404 },
        ),
      ),
    );
    await expect(approvalsApi.approveStage("missing")).rejects.toBeDefined();
  });
});

describe("approvalsApi.rejectRequest", () => {
  it("POSTs notes to /reject endpoint", async () => {
    let receivedBody: Record<string, unknown> | null = null;
    server.use(
      http.post(
        "/api/v1/approvals/requests/:id/reject",
        async ({ request }) => {
          receivedBody = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({ ...baseRequest, status: "REJECTED" });
        },
      ),
    );
    const result = await approvalsApi.rejectRequest("req-1", "Not right");
    expect(result.status).toBe("REJECTED");
    expect(receivedBody).toEqual({ notes: "Not right" });
  });
});
