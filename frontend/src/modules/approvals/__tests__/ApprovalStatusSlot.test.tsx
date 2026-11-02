import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  waitFor,
  fireEvent,
  act,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { ApprovalStatusSlot } from "../slots/ApprovalStatusSlot";
import { server } from "@/test/mocks/server";
import { signInWith } from "@/test/auth";
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

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
};

const baseRequest = {
  id: "req-1",
  organization_id: "org-1",
  workflow_id: "wf-1",
  target_type: "document",
  target_id: "doc-42",
  status: "PENDING" as const,
  current_stage: 1,
  total_stages: 1,
  created_by: "user-1",
  created_by_name: "Alice",
  meta_data: null,
  workflow_stages: null,
  decisions: [],
  created_at: new Date().toISOString(),
};

const envelope = (items: unknown[]) => ({
  items,
  total: items.length,
  limit: 100,
  offset: 0,
  has_more: false,
});

beforeEach(() => {
  vi.clearAllMocks();
  server.resetHandlers();
  // The slot renders the decision buttons (gated on approvals:approve) and
  // the request button (gated on the write right the request endpoint
  // answers to).
  signInWith(["approvals:approve", "approvals:write"]);
});

describe("ApprovalStatusSlot", () => {
  it("filters requests by target_type and target_id", async () => {
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(
          envelope([
            baseRequest,
            { ...baseRequest, id: "req-2", target_id: "doc-other" },
          ]),
        ),
      ),
    );
    render(
      <ApprovalStatusSlot
        data={{ targetType: "document", targetId: "doc-42" }}
      />,
      { wrapper: createWrapper() },
    );
    await waitFor(() => {
      expect(screen.getByText(/^Waiting for approval/)).toBeInTheDocument();
    });
  });

  it("says the requests could not be read instead of offering to raise one", async () => {
    server.use(
      http.get(
        "/api/v1/approvals/requests",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    render(
      <ApprovalStatusSlot
        data={{ targetType: "document", targetId: "doc-42" }}
      />,
      { wrapper: createWrapper() },
    );
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("Request approval")).not.toBeInTheDocument();
  });

  it("forwards the target approve adapter", async () => {
    const onApprove = vi.fn().mockResolvedValue(undefined);
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(envelope([baseRequest])),
      ),
    );
    render(
      <ApprovalStatusSlot
        data={{ targetType: "document", targetId: "doc-42", onApprove }}
      />,
      { wrapper: createWrapper() },
    );

    const approveButton = await screen.findByText("Approve");
    fireEvent.click(approveButton);
    // approving is irreversible, so it asks first.
    fireEvent.click(await screen.findByText("Approve request"));

    await waitFor(() =>
      expect(onApprove).toHaveBeenCalledWith("req-1", undefined),
    );
  });

  it("passes the typed note to the target approve adapter", async () => {
    const onApprove = vi.fn().mockResolvedValue(undefined);
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(envelope([baseRequest])),
      ),
    );
    render(
      <ApprovalStatusSlot
        data={{ targetType: "document", targetId: "doc-42", onApprove }}
      />,
      { wrapper: createWrapper() },
    );

    const approveButton = await screen.findByText("Approve");
    fireEvent.click(approveButton);
    fireEvent.change(
      await screen.findByPlaceholderText(
        "Add a note for the audit trail (optional)",
      ),
      { target: { value: "Audit note" } },
    );
    fireEvent.click(await screen.findByText("Approve request"));

    await waitFor(() =>
      expect(onApprove).toHaveBeenCalledWith("req-1", "Audit note"),
    );
  });

  it("forwards the target request adapter instead of the generic endpoint", async () => {
    // A documents request is gated on warehouse:write — the module whose
    // proxy endpoint the adapter calls.
    signInWith(["approvals:approve", "warehouse:write"]);
    const onRequest = vi.fn().mockResolvedValue(undefined);
    let genericCalled = false;
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(envelope([])),
      ),
      http.post("/api/v1/approvals/requests", () => {
        genericCalled = true;
        return HttpResponse.json(baseRequest, { status: 201 });
      }),
    );
    render(
      <ApprovalStatusSlot
        data={{
          targetType: "document",
          targetId: "doc-42",
          requestModule: "warehouse",
          onRequest,
        }}
      />,
      { wrapper: createWrapper() },
    );

    const requestButton = await screen.findByText("Request Approval");
    fireEvent.click(requestButton);

    await waitFor(() => expect(onRequest).toHaveBeenCalled());
    expect(genericCalled).toBe(false);
  });

  it("offers no request button to an account the endpoint would refuse", async () => {
    // The request button used to render for every reader; the backend
    // refused the click with 403. Without the write right the button says
    // nothing instead of promising an action.
    signInWith(["approvals:read"]);
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(envelope([])),
      ),
    );
    render(
      <ApprovalStatusSlot
        data={{ targetType: "document", targetId: "doc-42" }}
      />,
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      expect(screen.queryByText("Request Approval")).not.toBeInTheDocument();
    });
  });

  it("forwards the target reject adapter with notes", async () => {
    const onReject = vi.fn().mockResolvedValue(undefined);
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(envelope([baseRequest])),
      ),
    );
    render(
      <ApprovalStatusSlot
        data={{ targetType: "document", targetId: "doc-42", onReject }}
      />,
      { wrapper: createWrapper() },
    );

    const rejectButton = await screen.findByText("Reject");
    fireEvent.click(rejectButton);
    fireEvent.change(screen.getByPlaceholderText("Rejection reason"), {
      target: { value: "missing lines" },
    });
    fireEvent.click(screen.getByText("Confirm Reject"));

    await waitFor(() =>
      expect(onReject).toHaveBeenCalledWith("req-1", "missing lines"),
    );
  });

  it("falls back to Request Approval button when no matching request", async () => {
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(envelope([])),
      ),
    );
    render(
      <ApprovalStatusSlot
        data={{ targetType: "document", targetId: "doc-42" }}
      />,
      { wrapper: createWrapper() },
    );
    await waitFor(() => {
      expect(screen.getByText("Request Approval")).toBeInTheDocument();
    });
  });

  it("passes the target_type as a query filter", async () => {
    let receivedUrl: URL | undefined;
    server.use(
      http.get("/api/v1/approvals/requests", ({ request }) => {
        receivedUrl = new URL(request.url);
        return HttpResponse.json([]);
      }),
    );
    render(
      <ApprovalStatusSlot
        data={{ targetType: "purchase_order", targetId: "po-1" }}
      />,
      { wrapper: createWrapper() },
    );
    await waitFor(() => {
      expect(receivedUrl).toBeDefined();
    });
    expect(receivedUrl?.searchParams.get("target_type")).toBe("purchase_order");
  });

  it("picks the newest matching request regardless of list order", async () => {
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(
          envelope([
            {
              ...baseRequest,
              id: "req-1",
              status: "APPROVED",
              created_at: "2026-01-01T00:00:00Z",
            },
            {
              ...baseRequest,
              id: "req-2",
              status: "PENDING",
              created_at: "2026-01-02T00:00:00Z",
            },
          ]),
        ),
      ),
    );
    render(
      <ApprovalStatusSlot
        data={{ targetType: "document", targetId: "doc-42" }}
      />,
      { wrapper: createWrapper() },
    );
    // req-1 sits first and is APPROVED, but req-2 is newer and PENDING — the
    // slot must read the newest one, so the decision buttons appear instead
    // of the stale Approved badge.
    await waitFor(() => {
      expect(screen.getByText("Approve")).toBeInTheDocument();
    });
    expect(screen.queryByText("Approved")).not.toBeInTheDocument();
  });
});

/**
 * A request raised by somebody else — the manager who created the document
 * from a purchase order. A viewer without `approvals:read` never sees it in
 * GET /approvals/requests: the server scopes that list to one's own requests
 * (and the open ones awaiting one's decision). GET /approvals/documents/{id}/approval
 * answers with it regardless — that is the read the card must use.
 */
const managersRequest = {
  ...baseRequest,
  id: "req-manager",
  target_id: "doc-42",
  created_by: "manager-1",
  created_by_name: "Manager",
  viewer_can_decide: false,
};

let listCalls = 0;

/** One macrotask turn — long enough for any enabled query to reach MSW. */
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("ApprovalStatusSlot with the target's own request", () => {
  beforeEach(() => {
    listCalls = 0;
    signInWith(["warehouse:write"]);
    server.use(
      // What the scoped list answers for this viewer when the document's
      // only request was raised by someone else: nothing.
      http.get("/api/v1/approvals/requests", () => {
        listCalls += 1;
        return HttpResponse.json(envelope([]));
      }),
    );
  });

  it("shows a request raised by another user instead of the Request Approval button", () => {
    render(
      <ApprovalStatusSlot
        data={{
          targetType: "document",
          targetId: "doc-42",
          requestModule: "warehouse",
          approval: managersRequest,
        }}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText(/^Waiting for approval/)).toBeInTheDocument();
    expect(screen.queryByText("Request Approval")).not.toBeInTheDocument();
  });

  it("does not read the type list when the caller provides the document's request", async () => {
    render(
      <ApprovalStatusSlot
        data={{
          targetType: "document",
          targetId: "doc-42",
          requestModule: "warehouse",
          approval: managersRequest,
        }}
      />,
      { wrapper: createWrapper() },
    );

    await settle();
    expect(listCalls).toBe(0);
  });

  it("offers Request Approval only once the document's request is known to be absent", async () => {
    render(
      <ApprovalStatusSlot
        data={{
          targetType: "document",
          targetId: "doc-42",
          requestModule: "warehouse",
          approval: null,
        }}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText("Request Approval")).toBeInTheDocument();
    await settle();
    expect(listCalls).toBe(0);
  });

  it("says nothing while the document's request is still loading", async () => {
    render(
      <ApprovalStatusSlot
        data={{
          targetType: "document",
          targetId: "doc-42",
          requestModule: "warehouse",
          approval: undefined,
        }}
      />,
      { wrapper: createWrapper() },
    );

    await settle();
    expect(screen.queryByText("Request Approval")).not.toBeInTheDocument();
    expect(screen.queryByText(/^Waiting for approval/)).not.toBeInTheDocument();
    expect(listCalls).toBe(0);
  });
});
