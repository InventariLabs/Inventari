import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import DocumentApprovalsPage from "../pages/DocumentApprovalsPage";
// The queue hands the request, its stages and the decision to the approvals
// module through slots, so the module has to be registered for them to fill.
import "@/modules/approvals/module";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { server } from "@/test/mocks/server";
import { signInWith } from "@/test/auth";
import { http, HttpResponse } from "msw";
import { queryKeys } from "@/hooks/queries/keys";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { toast } from "sonner";

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: vi.fn() }),
}));

// A card quotes the document's total only where the organization tracks
// value; the queue itself is what this file is about.
vi.mock("@/modules/warehouse/hooks/useDocumentProfile", () => ({
  useDocumentProfile: () => ({ data: { value_tracking_enabled: true } }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  server.resetHandlers();
  // This queue renders the shared decision panel, gated on approvals:approve.
  signInWith(["approvals:approve"]);
});

const createWrapper = (
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  }),
) => {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ModulesProvider>{children}</ModulesProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

function pendingDocument(id: string, number: string) {
  return {
    id,
    organization_id: "org-1",
    type: "IN",
    number,
    status: "PENDING_APPROVAL",
    partner_id: null,
    partner_snapshot: null,
    corrects_document_id: null,
    backorder_id: null,
    source_location_id: null,
    target_location_id: "loc-1",
    scheduled_date: null,
    notes: null,
    external_reference: null,
    lines: [],
    created_by: "user-1",
    created_by_name: "Alice",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    confirmed_at: null,
    completed_at: null,
  };
}

describe("DocumentApprovalsPage", () => {
  it("names the document in the bulk-select checkbox and links to it once", async () => {
    // twenty rows announced as "Select" gave a screen-reader user no
    // way to tell which document they were ticking; the number and "Open
    // document" pointed at the same place from one row.
    server.use(
      http.get("/api/v1/warehouse/awaiting-my-approval", () =>
        HttpResponse.json({
          items: [pendingDocument("doc-1", "IN/2026/001")],
          documents: [pendingDocument("doc-1", "IN/2026/001")],
          total: 1,
          limit: 50,
          offset: 0,
          has_more: false,
        }),
      ),
      http.get("/api/v1/approvals/documents/doc-1/approval", () =>
        HttpResponse.json(null),
      ),
    );

    render(<DocumentApprovalsPage />, { wrapper: createWrapper() });

    expect(
      await screen.findByRole("checkbox", {
        name: /IN\/2026\/001/,
      }),
    ).toBeInTheDocument();
    const links = screen
      .getAllByRole("link")
      .filter((a) => a.getAttribute("href") === "/warehouse/documents/doc-1");
    expect(links).toHaveLength(1);
  });

  it("names a parked request whose stage nobody can decide, beside an empty queue", async () => {
    // A request waiting where nobody can act never enters the queue itself —
    // the queue shows what the reader can act on — so it used to read
    // exactly like an empty queue. The parked section names it instead.
    // The server CAN produce this state, which is what makes the assertion
    // honest: the reader's own request parked on a stage naming approvers
    // who cannot see approvals.
    server.use(
      http.get("/api/v1/modules/my", () =>
        HttpResponse.json(["core", "warehouse", "approvals"]),
      ),
      http.get("/api/v1/warehouse/awaiting-my-approval", () =>
        HttpResponse.json({
          items: [],
          total: 0,
          limit: 50,
          offset: 0,
          has_more: false,
        }),
      ),
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json({
          items: [
            {
              id: "req-1",
              organization_id: "org-1",
              workflow_id: "wf-1",
              target_type: "document",
              target_id: "doc-1",
              status: "PENDING",
              current_stage: 1,
              total_stages: 1,
              created_by: "user-1",
              created_by_name: "Alice",
              meta_data: null,
              workflow_stages: [
                {
                  order: 1,
                  role: "manager",
                  label: "Manager Approval",
                  approver_user_ids: ["user-2"],
                },
              ],
              decisions: [],
              created_at: new Date().toISOString(),
              target_summary: {
                number: "IN/2026/0001",
                type: "IN",
                partner_name: null,
                total_value: null,
                currency: null,
                lines_count: 1,
              },
              solvable: false,
              undecidable_reason: "named_approvers_cannot_decide",
            },
          ],
          total: 1,
          limit: 100,
          offset: 0,
          has_more: false,
        }),
      ),
    );

    render(<DocumentApprovalsPage />, { wrapper: createWrapper() });

    // The queue is empty and says so — the parked request is named beside
    // it, not mistaken for it and not swallowed by it.
    expect(
      await screen.findByText("No documents awaiting your approval"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Parked — nobody can decide"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Nobody can decide this request"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/names approvers who cannot see approvals/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /IN\/2026\/0001/ }),
    ).toHaveAttribute("href", "/warehouse/documents/doc-1");
  });

  it("names the parked request whose only possible decider is its own requester", async () => {
    // The third dead end, and the default shape of a fresh solo
    // organization: an open stage, and the grant's only holder is the
    // person who asked. The server names it only_the_requester_can_decide;
    // the section must not fall back to the "nobody holds the grant"
    // sentence, which would send the reader looking for the wrong fix.
    server.use(
      http.get("/api/v1/modules/my", () =>
        HttpResponse.json(["core", "warehouse", "approvals"]),
      ),
      http.get("/api/v1/warehouse/awaiting-my-approval", () =>
        HttpResponse.json({
          items: [],
          total: 0,
          limit: 50,
          offset: 0,
          has_more: false,
        }),
      ),
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json({
          items: [
            {
              id: "req-1",
              organization_id: "org-1",
              workflow_id: "wf-1",
              target_type: "document",
              target_id: "doc-1",
              status: "PENDING",
              current_stage: 1,
              total_stages: 1,
              created_by: "user-1",
              created_by_name: "Alice",
              meta_data: null,
              workflow_stages: [
                {
                  order: 1,
                  role: "manager",
                  label: "Manager Approval",
                  approver_user_ids: [],
                },
              ],
              decisions: [],
              created_at: new Date().toISOString(),
              target_summary: {
                number: "IN/2026/0001",
                type: "IN",
                partner_name: null,
                total_value: null,
                currency: null,
                lines_count: 1,
              },
              solvable: false,
              undecidable_reason: "only_the_requester_can_decide",
            },
          ],
          total: 1,
          limit: 100,
          offset: 0,
          has_more: false,
        }),
      ),
    );

    render(<DocumentApprovalsPage />, { wrapper: createWrapper() });

    expect(
      await screen.findByText("Parked — nobody can decide"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/the only holder is the person who asked/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/nobody in this organization holds it/i),
    ).not.toBeInTheDocument();
  });

  it("says nothing about a stage somebody can decide", async () => {
    server.use(
      http.get("/api/v1/modules/my", () =>
        HttpResponse.json(["core", "warehouse", "approvals"]),
      ),
      http.get("/api/v1/warehouse/awaiting-my-approval", () =>
        HttpResponse.json({
          items: [pendingDocument("doc-1", "IN/2026/0001")],
          total: 1,
          limit: 50,
          offset: 0,
          has_more: false,
        }),
      ),
      http.get("/api/v1/approvals/documents/doc-1/approval", () =>
        HttpResponse.json({
          id: "req-1",
          organization_id: "org-1",
          workflow_id: "wf-1",
          target_type: "document",
          target_id: "doc-1",
          status: "PENDING",
          current_stage: 1,
          total_stages: 1,
          created_by: "user-1",
          created_by_name: "Alice",
          meta_data: null,
          workflow_stages: [
            {
              order: 1,
              role: "manager",
              label: "Manager Approval",
              approver_user_ids: [],
            },
          ],
          decisions: [],
          created_at: new Date().toISOString(),
          solvable: true,
          undecidable_reason: null,
        }),
      ),
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json({
          items: [],
          total: 0,
          limit: 100,
          offset: 0,
          has_more: false,
        }),
      ),
    );

    render(<DocumentApprovalsPage />, { wrapper: createWrapper() });
    await screen.findByText("IN/2026/0001");
    await waitFor(() =>
      expect(screen.getByText("Approve")).toBeInTheDocument(),
    );
    expect(
      screen.queryByText("Parked — nobody can decide"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Nobody can decide this request"),
    ).not.toBeInTheDocument();
  });

  it("renders the empty state when there are no pending requests", async () => {
    server.use(
      http.get("/api/v1/warehouse/awaiting-my-approval", () =>
        HttpResponse.json({
          items: [],
          documents: [],
          total: 0,
          limit: 50,
          offset: 0,
          has_more: false,
        }),
      ),
    );
    render(<DocumentApprovalsPage />, { wrapper: createWrapper() });
    expect(
      await screen.findByText("No documents awaiting your approval"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Documents you can approve or reject appear here."),
    ).toBeInTheDocument();
  });

  it("offers no way into a module this workspace does not have", async () => {
    // The hint used to name the Approvals module in prose — in a workspace
    // mode where the module is absent from the launcher, and as text nobody
    // could click. There is no ModulesProvider here, so nothing is enabled.
    server.use(
      http.get("/api/v1/warehouse/awaiting-my-approval", () =>
        HttpResponse.json({
          items: [],
          documents: [],
          total: 0,
          limit: 50,
          offset: 0,
          has_more: false,
        }),
      ),
    );
    render(<DocumentApprovalsPage />, { wrapper: createWrapper() });

    await screen.findByText("No documents awaiting your approval");
    expect(
      screen.queryByText("Requests from other modules"),
    ).not.toBeInTheDocument();
  });

  it("links to the wider request inbox when that module is on", async () => {
    server.use(
      http.get("/api/v1/modules/my", () =>
        HttpResponse.json(["core", "warehouse", "approvals"]),
      ),
      http.get("/api/v1/warehouse/awaiting-my-approval", () =>
        HttpResponse.json({
          items: [],
          documents: [],
          total: 0,
          limit: 50,
          offset: 0,
          has_more: false,
        }),
      ),
    );
    render(<DocumentApprovalsPage />, { wrapper: createWrapper() });

    const link = await screen.findByRole("link", {
      name: "Requests from other modules",
    });
    expect(link).toHaveAttribute("href", "/approvals");
  });

  it("renders a card per pending document with the type badge and a link to detail", async () => {
    server.use(
      http.get("/api/v1/modules/my", () =>
        HttpResponse.json(["core", "warehouse", "approvals"]),
      ),
      http.get("/api/v1/warehouse/awaiting-my-approval", () =>
        HttpResponse.json({
          items: [
            {
              id: "doc-1",
              organization_id: "org-1",
              type: "IN",
              number: "IN/2026/0001",
              status: "PENDING_APPROVAL",
              partner_id: null,
              partner_snapshot: null,
              corrects_document_id: null,
              backorder_id: null,
              source_location_id: null,
              target_location_id: "loc-1",
              scheduled_date: null,
              notes: null,
              external_reference: null,
              lines: [],
              created_by: "user-1",
              created_by_name: "Alice",
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
              confirmed_at: null,
              completed_at: null,
            },
          ],
          total: 1,
          limit: 50,
          offset: 0,
          has_more: false,
        }),
      ),
      http.get("/api/v1/approvals/documents/doc-1/approval", () =>
        HttpResponse.json({
          id: "req-1",
          organization_id: "org-1",
          workflow_id: "wf-1",
          target_type: "document",
          target_id: "doc-1",
          status: "PENDING",
          current_stage: 1,
          total_stages: 1,
          created_by: "user-1",
          created_by_name: "Alice",
          meta_data: null,
          workflow_stages: [],
          decisions: [],
          created_at: new Date().toISOString(),
        }),
      ),
    );
    render(<DocumentApprovalsPage />, { wrapper: createWrapper() });
    await screen.findByText("IN/2026/0001");
    // The type label "IN" + the document number must be visible.
    expect(screen.getByText("IN/2026/0001")).toBeInTheDocument();
    // The requester name is prominent.
    await waitFor(() => expect(screen.getByText("Alice")).toBeInTheDocument());
    // The decision buttons are rendered (i18n mock returns the key).
    expect(screen.getByText("Approve")).toBeInTheDocument();
  });

  it("says the queue could not be loaded, rather than that it is empty", async () => {
    // this page used to answer a failed request with "nothing awaiting
    // your approval" — the one sentence guaranteed to make an approver stop
    // looking. The failure is now named, with a way to try again.
    server.use(
      http.get("/api/v1/warehouse/awaiting-my-approval", () =>
        HttpResponse.json({ detail: "approvals disabled" }, { status: 500 }),
      ),
    );
    render(<DocumentApprovalsPage />, { wrapper: createWrapper() });

    expect(
      await screen.findByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("No documents awaiting your approval"),
    ).not.toBeInTheDocument();
  });
});

describe("DocumentApprovalsPage — approving in bulk", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/warehouse/awaiting-my-approval", () =>
        HttpResponse.json({
          items: [
            pendingDocument("doc-1", "IN/2026/0001"),
            pendingDocument("doc-2", "IN/2026/0002"),
          ],
          total: 2,
          limit: 50,
          offset: 0,
          has_more: false,
        }),
      ),
      http.get("/api/v1/approvals/documents/:id/approval", () =>
        HttpResponse.json(null),
      ),
    );
  });

  async function selectBothAndPressApprove(queryClient?: QueryClient) {
    render(<DocumentApprovalsPage />, {
      wrapper: createWrapper(queryClient),
    });
    await screen.findByText("IN/2026/0001");
    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);
    fireEvent.click(
      screen.getByRole("button", { name: /approve 2 documents/i }),
    );
  }

  it("sticks the bulk bar below the app header, not at a z-index offset", async () => {
    render(<DocumentApprovalsPage />, { wrapper: createWrapper() });
    await screen.findByText("IN/2026/0001");
    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[0]);

    const bar = screen
      .getByRole("button", { name: /approve 1 document/i })
      .closest(".sticky");
    expect(bar?.className).not.toContain("--z-app-bar");
    expect(bar?.className).toMatch(/top-\[calc\(3\.5rem\+/);
  });

  it("asks before approving, and does nothing until confirmed", async () => {
    let approvals = 0;
    server.use(
      http.post("/api/v1/approvals/documents/:id/approve", () => {
        approvals += 1;
        return HttpResponse.json({});
      }),
    );

    await selectBothAndPressApprove();

    // Approving in bulk confirms every document for warehouse execution —
    // irreversible from here, so the button asks first instead of acting on
    // the first click.
    expect(
      await screen.findByText(/approve selected documents/i),
    ).toBeInTheDocument();
    // Same truth the single-approval dialog tells: approval marks the
    // documents ready for warehouse execution — the stock moves later, at
    // the receipt, so no wording may promise it here.
    const message = await screen.findByText(/approves 2 documents/);
    expect(message).toHaveTextContent("ready for warehouse execution");
    expect(message.textContent).not.toMatch(/moves? stock/);
    expect(approvals).toBe(0);
  });

  it("refreshes the notification bell once the documents are approved", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    server.use(
      http.post("/api/v1/approvals/documents/:id/approve", () =>
        HttpResponse.json({}),
      ),
    );

    await selectBothAndPressApprove(queryClient);
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: /approve 2 documents/i }),
    );

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({
        queryKey: queryKeys.notifications.all,
      }),
    );
  });

  it("names the documents that failed and keeps them selected", async () => {
    server.use(
      http.post("/api/v1/approvals/documents/doc-1/approve", () =>
        HttpResponse.json({}),
      ),
      http.post("/api/v1/approvals/documents/doc-2/approve", () =>
        HttpResponse.json({ detail: "nope" }, { status: 409 }),
      ),
    );

    await selectBothAndPressApprove();
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: /approve 2 documents/i }),
    );

    await waitFor(() =>
      expect(vi.mocked(toast.error)).toHaveBeenCalledWith(
        expect.stringContaining("IN/2026/0002"),
      ),
    );
    // A bare count left the approver to work out which two of twenty to redo.
    expect(vi.mocked(toast.error).mock.calls[0][0]).not.toContain(
      "IN/2026/0001",
    );
  });
});
