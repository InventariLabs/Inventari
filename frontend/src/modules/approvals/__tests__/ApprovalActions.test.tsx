import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { ApprovalActions } from "../components/ApprovalActions";
import { server } from "@/test/mocks/server";
import { signInWith } from "@/test/auth";
import { http, HttpResponse } from "msw";
import * as modulesCtx from "@/contexts/ModulesContext";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const baseRequest = {
  id: "req-1",
  organization_id: "org-1",
  workflow_id: "wf-1",
  target_type: "document",
  target_id: "doc-1",
  status: "PENDING" as const,
  current_stage: 1,
  total_stages: 2,
  created_by: "user-1",
  created_by_name: "Alice",
  meta_data: null,
  workflow_stages: [
    { order: 1, role: "manager", label: "Manager", approver_user_ids: [] },
    { order: 2, role: "admin", label: "Admin", approver_user_ids: [] },
  ],
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

beforeEach(() => {
  vi.clearAllMocks();
  server.resetHandlers();
  // Default org-members handler so useOrgMembers resolves cleanly in every test.
  server.use(
    http.get("/api/v1/users/org-members", () => HttpResponse.json(onePage([]))),
  );
  // The decision buttons are gated on the permission the API enforces, and
  // so is the request button: the generic POST /approvals/requests answers
  // to approvals:write.
  signInWith(["approvals:approve", "approvals:write"]);
});

describe("ApprovalActions with no approval", () => {
  it("renders the Request Approval button", () => {
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={null}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText("Request Approval")).toBeInTheDocument();
  });

  it("calls requestApproval mutation on click", async () => {
    let receivedBody: Record<string, unknown> | null = null;
    server.use(
      http.post("/api/v1/approvals/requests", async ({ request }) => {
        receivedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(baseRequest, { status: 201 });
      }),
    );
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-42"
        approval={null}
      />,
      { wrapper: createWrapper() },
    );
    fireEvent.click(screen.getByText("Request Approval"));
    await waitFor(() => expect(receivedBody).not.toBeNull());
    expect(receivedBody).toEqual({
      target_type: "document",
      target_id: "doc-42",
    });
  });
});

describe("ApprovalActions with PENDING approval", () => {
  it("shows the current stage label", () => {
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={baseRequest}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText("Manager")).toBeInTheDocument();
  });

  it("renders Approve and Reject buttons", () => {
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={baseRequest}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText("Approve")).toBeInTheDocument();
    expect(screen.getByText("Reject")).toBeInTheDocument();
  });

  it("calls approveStage mutation on Approve click", async () => {
    let receivedUrl = "";
    server.use(
      http.post(
        "/api/v1/approvals/requests/:id/approve",
        async ({ params }) => {
          receivedUrl = `/api/v1/approvals/requests/${params.id}/approve`;
          return HttpResponse.json({
            ...baseRequest,
            status: "APPROVED",
          });
        },
      ),
    );
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={baseRequest}
      />,
      { wrapper: createWrapper() },
    );
    fireEvent.click(screen.getByText("Approve"));
    // approving is irreversible, so it asks first.
    fireEvent.click(await screen.findByText("Approve request"));
    await waitFor(() => expect(receivedUrl).toBeTruthy());
    expect(receivedUrl).toBe("/api/v1/approvals/requests/req-1/approve");
  });

  it("uses the target approve adapter when provided", async () => {
    const onApprove = vi.fn().mockResolvedValue(undefined);
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={baseRequest}
        onApprove={onApprove}
      />,
      { wrapper: createWrapper() },
    );

    fireEvent.click(screen.getByText("Approve"));
    // approving is irreversible, so it asks first.
    fireEvent.click(await screen.findByText("Approve request"));

    await waitFor(() =>
      expect(onApprove).toHaveBeenCalledWith(baseRequest, undefined),
    );
  });

  it("expands the reject input on Reject click and submits notes", async () => {
    let receivedBody: Record<string, unknown> | null = null;
    server.use(
      http.post(
        "/api/v1/approvals/requests/:id/reject",
        async ({ request }) => {
          receivedBody = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({
            ...baseRequest,
            status: "REJECTED",
          });
        },
      ),
    );
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={baseRequest}
      />,
      { wrapper: createWrapper() },
    );
    fireEvent.click(screen.getByText("Reject"));
    const input = await screen.findByPlaceholderText("Rejection reason");
    fireEvent.change(input, { target: { value: "Not ready" } });
    fireEvent.click(screen.getByText("Confirm Reject"));
    await waitFor(() => expect(receivedBody).not.toBeNull());
    expect(receivedBody).toEqual({ notes: "Not ready" });
  });

  it("blocks reject without notes", async () => {
    // The reject UI now requires a reason; without it the mutation is
    // never called. The error message is surfaced so the user knows
    // what to do.
    let receivedBody: Record<string, unknown> | null = null;
    server.use(
      http.post(
        "/api/v1/approvals/requests/:id/reject",
        async ({ request }) => {
          receivedBody = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({
            ...baseRequest,
            status: "REJECTED",
          });
        },
      ),
    );
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={baseRequest}
      />,
      { wrapper: createWrapper() },
    );
    fireEvent.click(screen.getByText("Reject"));
    await screen.findByPlaceholderText("Rejection reason");
    fireEvent.click(screen.getByText("Confirm Reject"));
    // Wait a tick for any pending mutation. Wrapped in act() so background
    // queries settling during the wait (e.g. useOrgMembers) stay act-scoped.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(receivedBody).toBeNull();
  });

  it("cancels the reject input and resets notes", async () => {
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={baseRequest}
      />,
      { wrapper: createWrapper() },
    );
    fireEvent.click(screen.getByText("Reject"));
    const input = await screen.findByPlaceholderText("Rejection reason");
    fireEvent.change(input, { target: { value: "draft" } });
    fireEvent.click(screen.getByText("Cancel"));
    // After cancel, the Reject button must be back, the input gone.
    expect(screen.getByText("Reject")).toBeInTheDocument();
    expect(
      screen.queryByPlaceholderText("Rejection reason"),
    ).not.toBeInTheDocument();
  });
});

describe("ApprovalActions with APPROVED status", () => {
  it("renders the approved badge without action buttons", () => {
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={{
          ...baseRequest,
          status: "APPROVED",
          decisions: [
            {
              id: "d-1",
              stage_order: 1,
              approver_id: "user-1",
              approver_name: "Alice",
              status: "APPROVED",
              notes: null,
              decided_at: new Date().toISOString(),
              created_at: new Date().toISOString(),
            },
          ],
        }}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText("Approved")).toBeInTheDocument();
    expect(screen.queryByText("Approve")).not.toBeInTheDocument();
  });

  it("shows the approver name and decided date", () => {
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={{
          ...baseRequest,
          status: "APPROVED",
          decisions: [
            {
              id: "d-1",
              stage_order: 1,
              approver_id: "user-1",
              approver_name: "Bob",
              status: "APPROVED",
              notes: null,
              decided_at: "2026-01-15T00:00:00Z",
              created_at: new Date().toISOString(),
            },
          ],
        }}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText(/Bob/)).toBeInTheDocument();
  });
});

describe("ApprovalActions with an automatically passed stage", () => {
  it("says so on an approved card instead of naming the requester as approver", () => {
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={{
          ...baseRequest,
          status: "APPROVED",
          decisions: [
            {
              id: "d-1",
              stage_order: 1,
              approver_id: "user-1",
              approver_name: "Alice",
              status: "APPROVED",
              notes:
                "Auto-approved: requester is the sole approver for this stage",
              decided_at: "2026-01-15T00:00:00Z",
              created_at: new Date().toISOString(),
            },
          ],
        }}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText(/Passed automatically/)).toBeInTheDocument();
    expect(screen.queryByText(/Alice/)).not.toBeInTheDocument();
  });

  it("says so on a pending card beside the real approvals", () => {
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={{
          ...baseRequest,
          decisions: [
            {
              id: "d-1",
              stage_order: 1,
              approver_id: "user-1",
              approver_name: "Alice",
              status: "APPROVED",
              notes:
                "Auto-approved: requester is the sole approver for this stage",
              decided_at: "2026-01-15T00:00:00Z",
              created_at: new Date().toISOString(),
            },
          ],
        }}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText(/Passed automatically/)).toBeInTheDocument();
    expect(screen.queryByText(/Alice approved/)).not.toBeInTheDocument();
  });
});

describe("ApprovalActions with REJECTED status", () => {
  it("renders the rejected badge plus a re-request button", () => {
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={{
          ...baseRequest,
          status: "REJECTED",
          decisions: [
            {
              id: "d-1",
              stage_order: 1,
              approver_id: "user-1",
              approver_name: "Bob",
              status: "REJECTED",
              notes: "Wrong numbers",
              decided_at: new Date().toISOString(),
              created_at: new Date().toISOString(),
            },
          ],
        }}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(screen.getByText("Request Approval")).toBeInTheDocument();
  });

  it("shows the rejection reason from the latest decision", () => {
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={{
          ...baseRequest,
          status: "REJECTED",
          decisions: [
            {
              id: "d-1",
              stage_order: 1,
              approver_id: "user-1",
              approver_name: "Bob",
              status: "REJECTED",
              notes: "Wrong numbers",
              decided_at: new Date().toISOString(),
              created_at: new Date().toISOString(),
            },
          ],
        }}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText(/Wrong numbers/)).toBeInTheDocument();
  });
});

describe("ApprovalActions with CANCELLED status", () => {
  // a withdrawn request left the document in PENDING_APPROVAL and
  // fell through to the default branch, which rendered live Approve/Reject
  // on a request the API answers with a conflict. The way back existed
  // (POST /approvals/documents/{id}/request-approval) but nothing offered it.
  const cancelled = {
    ...baseRequest,
    status: "CANCELLED" as const,
    cancelled_by: "user-1",
    cancelled_at: "2026-08-19T09:30:00Z",
    decisions: [],
  };

  it("renders the cancelled badge plus a re-request button", () => {
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={cancelled}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText("Cancelled")).toBeInTheDocument();
    expect(screen.getByText("Request Approval")).toBeInTheDocument();
  });

  it("offers no decision on a withdrawn request", () => {
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={cancelled}
      />,
      { wrapper: createWrapper() },
    );
    expect(
      screen.queryByRole("button", { name: /Approve$/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Reject" }),
    ).not.toBeInTheDocument();
  });

  it("says when the request was withdrawn", () => {
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={cancelled}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText(/Withdrawn on/)).toBeInTheDocument();
  });
});

describe("ApprovalActions with no active workflow", () => {
  // The role this gate exists for: it composes requests in its target
  // modules and may point at the configuration screen, but holds no read
  // grant over approvals — the workflow list answers it nothing at all.
  // The one bit comes from its own endpoint, which needs no such grant.
  const withWriteButNoRead = () =>
    signInWith(["approvals:approve", "approvals:write", "approvals:configure"]);

  const workflowConfigured = (configured: boolean) =>
    server.use(
      http.get("/api/v1/approvals/workflows/configured", () =>
        HttpResponse.json({ configured }),
      ),
    );

  beforeEach(() => {
    // The module is on; the screen that renders this component always has it
    // on (the slot belongs to the module).
    vi.spyOn(modulesCtx, "useEnabledModulesOptional").mockReturnValue([
      "approvals",
    ]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("explains the missing workflow before the click instead of after", async () => {
    withWriteButNoRead();
    workflowConfigured(false);

    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={null}
      />,
      { wrapper: createWrapper() },
    );

    // The button used to stand there until clicked; the refusal — "No active
    // approval workflow is configured for this action" — arrived after. This
    // account cannot read the workflow list, so the answer has to come from
    // the endpoint that needs no such grant.
    await waitFor(() =>
      expect(screen.queryByText("Request Approval")).not.toBeInTheDocument(),
    );
    expect(
      screen.getByText(
        "There is no active approval workflow yet — a request would be refused.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Configure a workflow" }),
    ).toHaveAttribute("href", "/approvals/workflows");
  });

  it("offers the request again once the server says a workflow is configured", async () => {
    withWriteButNoRead();
    workflowConfigured(true);

    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={null}
      />,
      { wrapper: createWrapper() },
    );

    expect(await screen.findByText("Request Approval")).toBeInTheDocument();
  });

  it("needs no read grant over approvals to answer the door", async () => {
    // The measured regression: write on the target module, no read over
    // approvals. The list is empty for this account — not unconfigured —
    // and the door used to read that emptiness as permission to offer a
    // request the engine then refused.
    signInWith(["approvals:approve", "approvals:write"]);
    workflowConfigured(false);

    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={null}
      />,
      { wrapper: createWrapper() },
    );

    expect(
      await screen.findByText(
        "There is no active approval workflow yet — a request would be refused.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Request Approval")).not.toBeInTheDocument();
  });

  it("spares an account that cannot request the notice about requesting", async () => {
    // The reader meets the warning where the button would have stood. For an
    // account the endpoint would refuse, no button ever stands there — and
    // the warning was still on the screen, telling a warehouseman a request
    // they cannot make would be refused.
    signInWith(["approvals:read"]);
    workflowConfigured(false);

    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={null}
      />,
      { wrapper: createWrapper() },
    );

    await waitFor(() =>
      expect(
        screen.queryByText(/no active approval workflow yet/),
      ).not.toBeInTheDocument(),
    );
    expect(screen.queryByText("Request Approval")).not.toBeInTheDocument();
  });

  it("spares a confirmed document the warning about a request nobody makes", async () => {
    // On a confirmed document the only request is the exceptional "send it
    // back", and the caller says so with a consequence. There is no primary
    // path to protect, so a missing workflow means no affordance at all —
    // not a yellow box over a receipt whose worker never asked for approval.
    withWriteButNoRead();
    workflowConfigured(false);

    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={null}
        requestConsequence="Requesting approval moves this document back."
      />,
      { wrapper: createWrapper() },
    );

    // While the answer is still in flight the affordance assumes the button
    // is usable; once "no workflow" lands, both the button and the warning
    // are gone — nothing to request and nothing to warn about.
    await waitFor(() =>
      expect(screen.queryByText("Request Approval")).not.toBeInTheDocument(),
    );
    expect(
      screen.queryByText(/no active approval workflow yet/),
    ).not.toBeInTheDocument();
  });

  it("keeps the button when the answer cannot be had", async () => {
    // Unanswered (a failed read, a still-open request): the API keeps the
    // last word, exactly as it did before the door learned to ask.
    withWriteButNoRead();
    server.use(
      http.get("/api/v1/approvals/workflows/configured", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={null}
      />,
      { wrapper: createWrapper() },
    );

    await waitFor(() =>
      expect(screen.getByText("Request Approval")).toBeInTheDocument(),
    );
  });

  it("explains the missing workflow on the way back from a rejected request", async () => {
    withWriteButNoRead();
    workflowConfigured(false);

    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={{
          ...baseRequest,
          status: "REJECTED",
          decisions: [
            {
              id: "d-1",
              stage_order: 1,
              approver_id: "user-1",
              approver_name: "Bob",
              status: "REJECTED",
              notes: "Wrong numbers",
              decided_at: new Date().toISOString(),
              created_at: new Date().toISOString(),
            },
          ],
        }}
      />,
      { wrapper: createWrapper() },
    );

    await waitFor(() =>
      expect(screen.queryByText("Request Approval")).not.toBeInTheDocument(),
    );
    expect(
      screen.getByText(
        "There is no active approval workflow yet — a request would be refused.",
      ),
    ).toBeInTheDocument();
    // The state itself stays visible: what happened to the request is not
    // erased by the missing workflow.
    expect(screen.getByText("Rejected")).toBeInTheDocument();
  });
});

describe("ApprovalActions error handling", () => {
  it("shows error toast when approval request fails", async () => {
    const { toast } = await import("sonner");
    server.use(
      http.post("/api/v1/approvals/requests", () =>
        HttpResponse.json({ detail: "No active workflow" }, { status: 409 }),
      ),
    );
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={null}
      />,
      { wrapper: createWrapper() },
    );
    fireEvent.click(screen.getByText("Request Approval"));
    await waitFor(() =>
      // The server detail ("No active workflow") must be surfaced to the user
      // instead of a generic localized fallback.
      expect(toast.error).toHaveBeenCalledWith("No active workflow"),
    );
  });

  it("shows error toast when approve fails", async () => {
    const { toast } = await import("sonner");
    server.use(
      http.post("/api/v1/approvals/requests/:id/approve", () =>
        HttpResponse.json({ detail: "Already approved" }, { status: 400 }),
      ),
    );
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={baseRequest}
      />,
      { wrapper: createWrapper() },
    );
    fireEvent.click(screen.getByText("Approve"));
    // approving is irreversible, so it asks first.
    fireEvent.click(await screen.findByText("Approve request"));
    await waitFor(() =>
      // The server detail ("Already approved") must be surfaced to the user.
      expect(toast.error).toHaveBeenCalledWith("Already approved"),
    );
  });
});

describe("ApprovalActions pending approvers", () => {
  it("lists the resolved approver names for the current stage", async () => {
    server.use(
      http.get("/api/v1/users/org-members", () =>
        HttpResponse.json(
          onePage([
            { id: "u-1", full_name: "Alice", email: "alice@x.com" },
            { id: "u-2", full_name: "Bob", email: "bob@x.com" },
          ]),
        ),
      ),
    );
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={{
          ...baseRequest,
          workflow_stages: [
            {
              order: 1,
              label: "Manager",
              approver_user_ids: ["u-1", "u-2"],
            },
          ],
        }}
      />,
      { wrapper: createWrapper() },
    );
    expect(
      await screen.findByText("Approvers: Alice, Bob"),
    ).toBeInTheDocument();
  });

  it("says the approvers could not be loaded instead of showing a bare count", async () => {
    server.use(
      http.get(
        "/api/v1/users/org-members",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={{
          ...baseRequest,
          workflow_stages: [
            {
              order: 1,
              label: "Manager",
              approver_user_ids: ["u-1", "u-2"],
            },
          ],
        }}
      />,
      { wrapper: createWrapper() },
    );
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it("shows the any-approver hint when the stage has no assigned approvers", () => {
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={baseRequest}
      />,
      { wrapper: createWrapper() },
    );
    expect(
      screen.getByText("Any approver may approve this stage"),
    ).toBeInTheDocument();
  });

  it("tells a requester they cannot decide on their own request", () => {
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={{
          ...baseRequest,
          created_by: "current-user",
          viewer_can_decide: false,
        }}
      />,
      { wrapper: createWrapper() },
    );
    expect(
      screen.getByText(
        "You submitted this request, so another approver must decide on this stage.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Approve")).not.toBeInTheDocument();
  });
});

describe("ApprovalActions without approvals:approve", () => {
  it("names the block for what it is instead of promising an action", () => {
    signInWith(["approvals:read"]);

    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={baseRequest}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText("Awaiting Decision")).toBeInTheDocument();
    expect(screen.queryByText("Your Action")).not.toBeInTheDocument();
    expect(screen.queryByText("Approve")).not.toBeInTheDocument();
  });

  it("keeps the stage and approver context visible", () => {
    // Who has to act is information, not an action — a reader still needs it.
    signInWith(["approvals:read"]);

    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={baseRequest}
      />,
      { wrapper: createWrapper() },
    );

    expect(
      screen.getByText("Any approver may approve this stage"),
    ).toBeInTheDocument();
  });

  it("still offers Request Approval to an account holding approvals:write", () => {
    signInWith(["approvals:read", "approvals:write"]);

    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={null}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText("Request Approval")).toBeInTheDocument();
  });

  it("hides Request Approval from an account that may not write", () => {
    // The generic POST /approvals/requests is refused to any account without
    // approvals:write; the button used to render anyway and the refusal
    // arrived only after the click.
    signInWith(["approvals:read"]);

    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={null}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.queryByText("Request Approval")).not.toBeInTheDocument();
  });

  it("gates the request button on the target module's write right, not approvals:write", () => {
    // A documents request goes through the documents proxy, which the module
    // router answers to warehouse:write — so the gate follows the endpoint
    // the button actually calls.
    signInWith(["warehouse:write"]);

    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={null}
        requestModule="warehouse"
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText("Request Approval")).toBeInTheDocument();
  });

  it("hides the re-request button without the write right, keeping the state", () => {
    signInWith(["approvals:read"]);

    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={{
          ...baseRequest,
          status: "REJECTED",
          decisions: [
            {
              id: "d-1",
              stage_order: 1,
              approver_id: "user-1",
              approver_name: "Bob",
              status: "REJECTED",
              notes: "Wrong numbers",
              decided_at: new Date().toISOString(),
              created_at: new Date().toISOString(),
            },
          ],
        }}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(screen.queryByText("Request Approval")).not.toBeInTheDocument();
  });
});

describe("ApprovalActions naming what a request does", () => {
  const CONSEQUENCE =
    "Requesting approval moves this document back to awaiting approval, where it stays until someone signs off.";

  it("asks first when the request would move the target's state", async () => {
    // On a confirmed document the request is not just a question — it
    // takes the document back to the approval queue. The click that does
    // that says so before it happens, not after.
    const onRequest = vi.fn().mockResolvedValue(undefined);
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={null}
        requestConsequence={CONSEQUENCE}
        onRequest={onRequest}
      />,
      { wrapper: createWrapper() },
    );

    fireEvent.click(screen.getByText("Request Approval"));
    expect(await screen.findByText(CONSEQUENCE)).toBeInTheDocument();
    expect(onRequest).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("Send for approval"));
    await waitFor(() => expect(onRequest).toHaveBeenCalled());
  });

  it("lets the user back out without requesting", async () => {
    const onRequest = vi.fn().mockResolvedValue(undefined);
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={null}
        requestConsequence={CONSEQUENCE}
        onRequest={onRequest}
      />,
      { wrapper: createWrapper() },
    );

    fireEvent.click(screen.getByText("Request Approval"));
    fireEvent.click(await screen.findByText("Cancel"));

    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(onRequest).not.toHaveBeenCalled();
    expect(screen.queryByText(CONSEQUENCE)).not.toBeInTheDocument();
  });

  it("requests straight away when the caller names no consequence", async () => {
    // A request that only asks — one that leaves the target's state alone —
    // has nothing to warn about and keeps its one click.
    const onRequest = vi.fn().mockResolvedValue(undefined);
    render(
      <ApprovalActions
        targetType="document"
        targetId="doc-1"
        approval={null}
        onRequest={onRequest}
      />,
      { wrapper: createWrapper() },
    );

    fireEvent.click(screen.getByText("Request Approval"));
    await waitFor(() => expect(onRequest).toHaveBeenCalled());
  });
});
