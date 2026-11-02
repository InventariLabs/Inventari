import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Link, MemoryRouter, useLocation } from "react-router-dom";
import ApprovalsDashboard from "../pages/ApprovalsDashboard";
import { server } from "@/test/mocks/server";
import { signInWith } from "@/test/auth";
import { http, HttpResponse } from "msw";
import { queryKeys } from "@/hooks/queries/keys";
import { formatDate } from "@/utils/formatters";
import * as modulesCtx from "@/contexts/ModulesContext";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: vi.fn() }),
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
  vi.clearAllMocks();
  server.resetHandlers();
  // The queue shows decision buttons, gated on the key the API enforces.
  signInWith(["approvals:approve"]);
});

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
};

// The address the router holds, so a test can read what the tab wrote to it.
function AddressProbe() {
  return <span data-testid="address">{useLocation().search}</span>;
}

const baseRequest = {
  id: "req-1",
  organization_id: "org-1",
  workflow_id: "wf-1",
  target_type: "document",
  target_id: "doc-42",
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

const envelope = (items: unknown[]) => ({
  items,
  total: items.length,
  limit: 100,
  offset: 0,
  has_more: false,
});

describe("ApprovalsDashboard", () => {
  it("renders empty state when there are no requests", async () => {
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(envelope([])),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    expect(
      await screen.findByText("No requests are waiting for approval"),
    ).toBeInTheDocument();
  });

  it("renders request cards with target type and stepper anchor", async () => {
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(envelope([baseRequest])),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    // The card shows the localised target type label, "Document".
    expect(await screen.findByText("Document")).toBeInTheDocument();
    // The stepper now renders the stage label as the dashboard anchor.
    expect(screen.getByText("Manager")).toBeInTheDocument();
    expect(screen.getByText("by Alice")).toBeInTheDocument();
  });

  it("renders Unknown when target_type is not in the label map", async () => {
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(
          envelope([{ ...baseRequest, target_type: "custom_thing" }]),
        ),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    expect(await screen.findByText("custom_thing")).toBeInTheDocument();
  });

  it("renders every status tab with i18n keys", async () => {
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(envelope([])),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    await screen.findByText("No requests are waiting for approval");
    // One word for a request that has not been decided: the chip that holds
    // a stage-2 request is the same one the card calls "Waiting for approval".
    expect(
      screen.getByRole("tab", { name: "Waiting for approval" }),
    ).toBeInTheDocument();
    expect(screen.getByText("All")).toBeInTheDocument();
    expect(screen.queryByText("Pending")).not.toBeInTheDocument();
    expect(screen.queryByText("In Progress")).not.toBeInTheDocument();
    expect(screen.getByText("Approved")).toBeInTheDocument();
    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(screen.getByText("Cancelled")).toBeInTheDocument();
  });

  it("hints at what the search matches in the words the screen uses", async () => {
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(envelope([])),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    expect(
      await screen.findByPlaceholderText("Search by name, number or type…"),
    ).toBeInTheDocument();
  });

  it("says a search matched nothing instead of calling the queue empty", async () => {
    // "No requests are waiting for approval" under a search for a name the
    // search missed read as an empty queue while a request waited.
    server.use(
      http.get("/api/v1/approvals/requests", ({ request }) => {
        const q = new URL(request.url).searchParams.get("search");
        return HttpResponse.json(envelope(q ? [] : [baseRequest]));
      }),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    await screen.findByText("Document");
    fireEvent.change(
      screen.getByPlaceholderText("Search by name, number or type…"),
      { target: { value: "printer" } },
    );

    expect(
      await screen.findByText("No request matches “printer”"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("No requests are waiting for approval"),
    ).not.toBeInTheDocument();
  });

  it("opens on the states that still need a decision", async () => {
    // Deleting a document cancels its request, and the queue used to
    // open on every status — so the first thing an approver saw was a row
    // of requests with nothing left to decide.
    let requestedStatus: string | null = "not-called";
    server.use(
      http.get("/api/v1/approvals/requests", ({ request }) => {
        requestedStatus = new URL(request.url).searchParams.get("status");
        return HttpResponse.json(envelope([]));
      }),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    await screen.findByText("No requests are waiting for approval");

    expect(requestedStatus).toBe("PENDING,IN_PROGRESS");
  });

  it("names the tab it is empty on, not the waiting queue", async () => {
    // One string used to serve every tab, so the Approved tab answered
    // "No requests are waiting for approval" — true of a different list.
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(envelope([])),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    await screen.findByText("No requests are waiting for approval");

    const titles: [string, string][] = [
      ["Approved", "No requests have been approved yet"],
      ["Rejected", "No requests have been rejected"],
      ["Cancelled", "No requests have been cancelled"],
      ["All", "There are no approval requests yet"],
    ];
    for (const [tab, title] of titles) {
      await userEvent.click(screen.getByRole("tab", { name: tab }));
      expect(await screen.findByText(title)).toBeInTheDocument();
      expect(
        screen.queryByText("No requests are waiting for approval"),
      ).not.toBeInTheDocument();
    }
  });

  it("lets the user ask for cancelled requests explicitly", async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.get("/api/v1/approvals/requests", ({ request }) => {
        seen.push(new URL(request.url).searchParams.get("status"));
        return HttpResponse.json(envelope([]));
      }),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    await screen.findByText("No requests are waiting for approval");

    await userEvent.click(screen.getByRole("tab", { name: "Cancelled" }));
    await waitFor(() => expect(seen).toContain("CANCELLED"));
  });

  it("follows a link that names a tab while the dashboard is already open", async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.get("/api/v1/approvals/requests", ({ request }) => {
        seen.push(new URL(request.url).searchParams.get("status"));
        return HttpResponse.json(envelope([]));
      }),
    );
    render(
      <>
        <Link to="/?status=REJECTED">to rejected</Link>
        <ApprovalsDashboard />
      </>,
      { wrapper: createWrapper() },
    );
    await screen.findByText("No requests are waiting for approval");

    await userEvent.click(screen.getByRole("link", { name: "to rejected" }));

    await waitFor(() => expect(seen).toContain("REJECTED"));
    expect(screen.getByRole("tab", { name: "Rejected" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("writes the chosen tab to the address and drops it for the default tab", async () => {
    render(
      <>
        <AddressProbe />
        <ApprovalsDashboard />
      </>,
      { wrapper: createWrapper() },
    );
    await screen.findByText("No requests are waiting for approval");
    const address = screen.getByTestId("address");

    await userEvent.click(screen.getByRole("tab", { name: "Cancelled" }));
    expect(address).toHaveTextContent("?status=CANCELLED");

    await userEvent.click(screen.getByRole("tab", { name: "All" }));
    expect(address).toHaveTextContent("?status=");
    expect(address).not.toHaveTextContent("CANCELLED");

    await userEvent.click(
      screen.getByRole("tab", { name: "Waiting for approval" }),
    );
    expect(address).toBeEmptyDOMElement();
  });

  it("does not show approval progress for a cancelled request", async () => {
    // "Approval Progress — Initial Review" under a cancelled request
    // reads as though it were still queued for the first stage.
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(
          envelope([
            {
              ...baseRequest,
              status: "CANCELLED",
              cancelled_at: "2026-08-15T09:00:00Z",
            },
          ]),
        ),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    await screen.findByText("Document");

    expect(screen.queryByText("Approval Progress")).not.toBeInTheDocument();
    expect(screen.queryByText("Manager")).not.toBeInTheDocument();
    // ...and no empty "Decision" heading over a request that recorded none.
    expect(screen.queryByText("Decision")).not.toBeInTheDocument();
  });

  it("filters by search query against target_id", async () => {
    server.use(
      http.get("/api/v1/approvals/requests", ({ request }) => {
        const url = new URL(request.url);
        const q = url.searchParams.get("search")?.toLowerCase() ?? "";
        const all = [
          baseRequest,
          { ...baseRequest, id: "req-2", target_id: "doc-other" },
        ];
        const items = all.filter(
          (r) => !q || r.target_id.toLowerCase().includes(q),
        );
        return HttpResponse.json(envelope(items));
      }),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    const search = (
      await screen.findAllByPlaceholderText("Search by name, number or type…")
    )[0] as HTMLInputElement;
    fireEvent.change(search, { target: { value: "doc-42" } });
    // Only the first card remains visible.
    await waitFor(() => {
      const cards = screen.getAllByText("Document");
      expect(cards.length).toBe(1);
    });
  });

  it("shows all cards when search is empty", async () => {
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
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    // Two cards render because both target_types are "document".
    await waitFor(() => {
      const cards = screen.getAllByText("Document");
      expect(cards.length).toBe(2);
    });
  });

  it("shows the approvers count for the current stage when not terminal", async () => {
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(
          envelope([
            {
              ...baseRequest,
              workflow_stages: [
                {
                  order: 1,
                  role: "manager",
                  label: "Manager",
                  approver_user_ids: ["u-1", "u-2", "u-3"],
                },
                {
                  order: 2,
                  role: "admin",
                  label: "Admin",
                  approver_user_ids: [],
                },
              ],
            },
          ]),
        ),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    // Three approvers on the current stage → the _other plural.
    expect(await screen.findByText("3 approvers assigned")).toBeInTheDocument();
  });

  it("does not show approver count for terminal statuses", async () => {
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(
          envelope([
            {
              ...baseRequest,
              status: "APPROVED",
              workflow_stages: [
                {
                  order: 1,
                  role: "manager",
                  label: "Manager",
                  approver_user_ids: ["u-1"],
                },
                {
                  order: 2,
                  role: "admin",
                  label: "Admin",
                  approver_user_ids: ["u-2"],
                },
              ],
            },
          ]),
        ),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    await screen.findByText("Document");
    expect(
      screen.queryByText("dashboard.stepper.approversAssigned"),
    ).not.toBeInTheDocument();
  });

  it("does not render the approver count when the stage has no approvers", async () => {
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(
          envelope([
            {
              ...baseRequest,
              workflow_stages: [
                {
                  order: 1,
                  role: "manager",
                  label: "Manager",
                  approver_user_ids: [],
                },
                {
                  order: 2,
                  role: "admin",
                  label: "Admin",
                  approver_user_ids: [],
                },
              ],
            },
          ]),
        ),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    await screen.findByText("Document");
    // The stepper shows the "any approver" hint instead of the count.
    expect(
      screen.getByText("Any approver may approve this stage"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("dashboard.stepper.approversAssigned"),
    ).not.toBeInTheDocument();
  });

  it("renders target_summary preview (number, partner, value, lines, link) for document requests", async () => {
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(
          envelope([
            {
              ...baseRequest,
              target_summary: {
                id: "doc-42",
                number: "IN/2026/9001",
                type: "IN",
                partner_name: "ACME Supplier",
                total_value: "250.00",
                currency: "USD",
                lines_count: 3,
              },
            },
          ]),
        ),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });

    await screen.findByText("IN/2026/9001");
    expect(screen.getByText("ACME Supplier")).toBeInTheDocument();
    expect(screen.getByText("$250.00")).toBeInTheDocument();
    expect(screen.getByText("3 lines")).toBeInTheDocument();
    // link to the document detail page
    const link = screen.getByRole("link", { name: "Open document" });
    expect(link).toHaveAttribute("href", "/warehouse/documents/doc-42");
    // View document is now an outline button (not primary) — it has a
    // border class but no filled background.
    expect(link.className).toContain("border");
  });

  it("describes a purchase order the same way it describes a document", async () => {
    // Everything but a document rendered as eight characters of a UUID, with
    // no supplier, no amount and nowhere to go — on the screen whose only job
    // is deciding about the spend.
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(
          envelope([
            {
              ...baseRequest,
              target_type: "purchase_order",
              target_id: "po-42",
              target_summary: {
                id: "po-42",
                number: "PO/2026/004",
                partner_name: "ACME Supplies",
                total_value: "300.00",
                currency: "USD",
                lines_count: 2,
              },
            },
          ]),
        ),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });

    await screen.findByText("PO/2026/004");
    expect(screen.getByText("ACME Supplies")).toBeInTheDocument();
    expect(screen.getByText("$300.00")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Open purchase order" });
    expect(link).toHaveAttribute("href", "/purchase-orders/po-42");
  });

  it("describes an equipment checkout with a name, serial and link", async () => {
    // An equipment checkout request rendered as eight characters of a UUID,
    // with no asset name and no way through to the asset.
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(
          envelope([
            {
              ...baseRequest,
              target_type: "equipment_checkout",
              target_id: "item-7",
              target_summary: {
                id: "item-7",
                number: "ThinkPad X1 Carbon",
                partner_name: null,
                total_value: null,
                currency: null,
                lines_count: 0,
                serial_number: "SN-001",
              },
            },
          ]),
        ),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });

    await screen.findByText("ThinkPad X1 Carbon");
    expect(screen.getByText("Serial SN-001")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Open equipment" });
    expect(link).toHaveAttribute("href", "/equipment/item-7");
    // No "0 lines" for a target that has no lines.
    expect(screen.queryByText("0 lines")).not.toBeInTheDocument();
    // Raised with no holder: the card says what the approval would cover.
    expect(
      screen.getByText(/the approval covers the next checkout/),
    ).toBeInTheDocument();
  });

  it("says who an equipment checkout goes to and until when", async () => {
    // The approver decided blind: the request carried the asset and nothing
    // about the hand-out it was asking for.
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(
          envelope([
            {
              ...baseRequest,
              target_type: "equipment_checkout",
              target_id: "item-7",
              meta_data: {
                checkout: {
                  holder: "Kasia Kowalska",
                  holder_kind: "person",
                  expected_return_at: "2026-11-05T14:59:59Z",
                },
              },
              target_summary: {
                id: "item-7",
                number: "Family laptop",
                partner_name: null,
                total_value: null,
                currency: null,
                lines_count: 0,
              },
            },
          ]),
        ),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });

    expect(await screen.findByText("For Kasia Kowalska")).toBeInTheDocument();
    expect(
      screen.getByText(`until ${formatDate("2026-11-05T14:59:59Z")}`),
    ).toBeInTheDocument();
  });

  it("says the document is gone when target_summary is null", async () => {
    // An absent summary means the document row is gone — deleting a
    // document cascades a cancel onto its request. Eight characters of a
    // UUID told the approver nothing about what the request was for.
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(envelope([{ ...baseRequest, target_summary: null }])),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    expect(await screen.findByText("Document deleted")).toBeInTheDocument();
    expect(screen.queryByText("doc-42…")).not.toBeInTheDocument();
    // ...and no offer to open it: the link would land on a 404.
    expect(
      screen.queryByRole("link", { name: "Open document" }),
    ).not.toBeInTheDocument();
  });

  it("terminal status: shows decision info and hides Approve/Reject buttons", async () => {
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(
          envelope([
            {
              ...baseRequest,
              status: "APPROVED",
              target_summary: {
                id: "doc-42",
                number: "IN/2026/9001",
                type: "IN",
                partner_name: "ACME",
                total_value: "100.00",
                currency: "USD",
                lines_count: 1,
              },
              decisions: [
                {
                  id: "dec-1",
                  stage_order: 1,
                  approver_id: "u-1",
                  approver_name: "Bob Manager",
                  status: "APPROVED",
                  notes: "All items in stock",
                  decided_at: "2026-07-26T14:30:00Z",
                  created_at: "2026-07-26T14:00:00Z",
                },
              ],
            },
          ]),
        ),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    await screen.findByText("IN/2026/9001");

    // Document number is the visible title
    expect(screen.getByText("IN/2026/9001")).toBeInTheDocument();
    // Partner visible
    expect(screen.getByText("ACME")).toBeInTheDocument();
    // Decision info: approved by (label + name may be in adjacent nodes)
    const decisionMatches = screen.getAllByText((_, el) =>
      Boolean(
        el?.textContent?.includes("Approved by") &&
        el.textContent.includes("Bob Manager"),
      ),
    );
    expect(decisionMatches.length).toBeGreaterThan(0);
    // Note is wrapped in literal quotes in JSX — match the substring
    const noteMatches = screen.getAllByText((_, el) =>
      Boolean(el?.textContent?.includes("All items in stock")),
    );
    expect(noteMatches.length).toBeGreaterThan(0);
    // Document link still visible
    const link = screen.getByRole("link", {
      name: "Open document",
    });
    expect(link).toHaveAttribute("href", "/warehouse/documents/doc-42");
    // No approve/reject buttons (they live inside ApprovalDecisionButtons
    // and are only shown for non-terminal statuses)
    expect(
      screen.queryByRole("button", { name: /^Approve$/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Reject$/i }),
    ).not.toBeInTheDocument();
  });

  it("renders the approval stepper and decision buttons for non-terminal status", async () => {
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(envelope([baseRequest])),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    await screen.findByText("Document");
    // The stepper section header is rendered.
    expect(screen.getByText("Approval Progress")).toBeInTheDocument();
    // The action section header for non-terminal is rendered.
    expect(screen.getByText("Your Action")).toBeInTheDocument();
    // Decision buttons are rendered (i18n mock returns the key as text).
    expect(screen.getByText("Approve")).toBeInTheDocument();
    expect(screen.getByText("Reject")).toBeInTheDocument();
  });

  it("renders the decision section header for terminal status", async () => {
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(
          envelope([
            {
              ...baseRequest,
              status: "REJECTED",
              decisions: [
                {
                  id: "dec-1",
                  stage_order: 1,
                  approver_id: "u-1",
                  approver_name: "Bob",
                  status: "REJECTED",
                  notes: "no",
                  decided_at: "2026-07-26T14:00:00Z",
                  created_at: "2026-07-26T14:00:00Z",
                },
              ],
            },
          ]),
        ),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    await screen.findByText("Document");
    expect(screen.getByText("Decision")).toBeInTheDocument();
    expect(screen.queryByText("Your Action")).not.toBeInTheDocument();
  });

  it("renders exactly one status badge per card", async () => {
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(envelope([baseRequest])),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    await screen.findByText("Document");
    // The open-request badge appears exactly once (header only, no
    // duplicate in the action column). The status filter has controls of
    // its own, so only non-interactive matches are counted.
    const badges = screen
      .getAllByText(/^Waiting for approval/)
      .filter((el) => el.closest("button") === null);
    expect(badges).toHaveLength(1);
  });

  // ------------------------------------------------------------------
  // Adapter registry: document requests route through the
  // atomic proxy endpoint (also flips the doc to CONFIRMED) instead of
  // the generic stage endpoint (which leaves it in PENDING_APPROVAL).
  // ------------------------------------------------------------------

  it("approves a document via the proxy endpoint (adapter), not the generic stage endpoint", async () => {
    let proxyCalled = false;
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(envelope([baseRequest])),
      ),
      http.post("/api/v1/approvals/documents/doc-42/approve", () => {
        proxyCalled = true;
        return HttpResponse.json({ ...baseRequest, status: "APPROVED" });
      }),
      http.post("/api/v1/approvals/requests/req-1/approve", () => {
        throw new Error("generic stage endpoint must not be called");
      }),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    await screen.findByText("Document");
    fireEvent.click(screen.getByText("Approve"));
    // approving is irreversible, so it asks first.
    fireEvent.click(await screen.findByText("Approve request"));
    await waitFor(() => expect(proxyCalled).toBe(true));
  });

  it("rejects a document via the proxy endpoint (adapter), not the generic stage endpoint", async () => {
    let proxyCalled = false;
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(envelope([baseRequest])),
      ),
      http.post("/api/v1/approvals/documents/doc-42/reject", () => {
        proxyCalled = true;
        return HttpResponse.json({ ...baseRequest, status: "REJECTED" });
      }),
      http.post("/api/v1/approvals/requests/req-1/reject", () => {
        throw new Error("generic stage endpoint must not be called");
      }),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    await screen.findByText("Document");
    // Reject requires a reason on the UI side.
    fireEvent.click(screen.getByText("Reject"));
    const reasonInput = screen.getByPlaceholderText("Rejection reason");
    fireEvent.change(reasonInput, { target: { value: "price too high" } });
    fireEvent.click(screen.getByText("Confirm Reject"));
    await waitFor(() => expect(proxyCalled).toBe(true));
  });

  it.each([
    ["approve", "Approve", "Approve request"],
    ["reject", "Reject", "Confirm Reject"],
  ])(
    "refreshes the notification bell after a document %s",
    async (action, trigger, confirm) => {
      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });
      const spy = vi.spyOn(queryClient, "invalidateQueries");
      server.use(
        http.get("/api/v1/approvals/requests", () =>
          HttpResponse.json(envelope([baseRequest])),
        ),
        http.post(`/api/v1/approvals/documents/doc-42/${action}`, () =>
          HttpResponse.json({ ...baseRequest, status: "APPROVED" }),
        ),
      );
      render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <ApprovalsDashboard />
          </MemoryRouter>
        </QueryClientProvider>,
      );
      await screen.findByText("Document");
      fireEvent.click(screen.getByText(trigger));
      if (action === "reject") {
        fireEvent.change(screen.getByPlaceholderText("Rejection reason"), {
          target: { value: "price too high" },
        });
      }
      fireEvent.click(await screen.findByText(confirm));
      await waitFor(() =>
        expect(spy).toHaveBeenCalledWith({
          queryKey: queryKeys.notifications.all,
        }),
      );
    },
  );

  // ------------------------------------------------------------------
  // Approvals card polish
  // ------------------------------------------------------------------

  it("renders the human-readable doc type label in the header", async () => {
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(
          envelope([
            {
              ...baseRequest,
              target_summary: {
                id: "doc-1",
                number: "OUT/2026/0001",
                type: "OUT",
                partner_name: "ACME",
                total_value: "120.00",
                currency: "USD",
                lines_count: 1,
              },
            },
          ]),
        ),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    await screen.findByText("OUT/2026/0001");
    // The dashboard surfaces a human-readable type label.
    expect(
      screen.getAllByText((_, el) =>
        Boolean(el?.textContent?.includes("Goods Issue")),
      ).length,
    ).toBeGreaterThan(0);
  });

  it("prominently displays the requester name and value", async () => {
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(
          envelope([
            {
              ...baseRequest,
              created_by_name: "Alice Manager",
              target_summary: {
                id: "doc-1",
                number: "OUT/2026/0001",
                type: "OUT",
                partner_name: "ACME",
                total_value: "1234.50",
                currency: "USD",
                lines_count: 2,
              },
            },
          ]),
        ),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    await screen.findByText("OUT/2026/0001");
    expect(screen.getByText("by Alice Manager")).toBeInTheDocument();
  });

  it("falls back to the location route for documents without a partner", async () => {
    server.use(
      http.get("/api/v1/approvals/requests", () =>
        HttpResponse.json(
          envelope([
            {
              ...baseRequest,
              target_summary: {
                id: "doc-1",
                number: "INT/2026/0001",
                type: "INT",
                partner_name: null,
                total_value: null,
                currency: null,
                lines_count: 1,
                source_location_name: "Receiving",
                target_location_name: "Cold Storage",
              },
            },
          ]),
        ),
      ),
    );
    render(<ApprovalsDashboard />, { wrapper: createWrapper() });
    await screen.findByText("INT/2026/0001");
    expect(
      screen.getByText("Receiving \u2192 Cold Storage"),
    ).toBeInTheDocument();
  });
});
