import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApprovalDecisionButtons } from "../components/ApprovalDecisionButtons";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { http, HttpResponse } from "msw";
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
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

beforeEach(() => {
  vi.clearAllMocks();
  server.resetHandlers();
  server.use(
    http.get("/api/v1/users/org-members", () => HttpResponse.json(onePage([]))),
  );
  // The buttons are gated on approvals:approve, the same key the API checks.
  signInWith(["approvals:approve"]);
});

describe("ApprovalDecisionButtons", () => {
  it("renders Approve and Reject buttons", () => {
    render(<ApprovalDecisionButtons approval={baseRequest} />, {
      wrapper: createWrapper(),
    });
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
    render(<ApprovalDecisionButtons approval={baseRequest} />, {
      wrapper: createWrapper(),
    });
    fireEvent.click(screen.getByText("Approve"));
    // approving is irreversible, so it asks first.
    fireEvent.click(await screen.findByText("Approve request"));
    await waitFor(() => expect(receivedUrl).toBeTruthy());
    expect(receivedUrl).toBe("/api/v1/approvals/requests/req-1/approve");
  });

  it("submits an optional note with the approval", async () => {
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
    render(<ApprovalDecisionButtons approval={baseRequest} />, {
      wrapper: createWrapper(),
    });
    fireEvent.click(screen.getByText("Approve"));
    const input = await screen.findByPlaceholderText(
      "Add a note for the audit trail (optional)",
    );
    fireEvent.change(input, { target: { value: "Budget confirmed" } });
    fireEvent.click(screen.getByText("Approve request"));
    await waitFor(() => expect(receivedBody).not.toBeNull());
    expect(receivedBody).toEqual({ notes: "Budget confirmed" });
  });

  it("uses the override onApprove adapter when provided", async () => {
    const onApprove = vi.fn().mockResolvedValue(undefined);
    render(
      <ApprovalDecisionButtons approval={baseRequest} onApprove={onApprove} />,
      { wrapper: createWrapper() },
    );

    fireEvent.click(screen.getByText("Approve"));
    // approving is irreversible, so it asks first.
    fireEvent.click(await screen.findByText("Approve request"));

    await waitFor(() =>
      expect(onApprove).toHaveBeenCalledWith(baseRequest, undefined),
    );
  });

  it("asks before approving, and does nothing until the answer is yes", async () => {
    // a single approve moves the document to CONFIRMED and keeps the
    // reservations — irreversible, exactly like the bulk action that has
    // asked since.
    let approveCalled = false;
    server.use(
      http.post("/api/v1/approvals/requests/:id/approve", () => {
        approveCalled = true;
        return HttpResponse.json({ ...baseRequest, status: "APPROVED" });
      }),
    );
    render(<ApprovalDecisionButtons approval={baseRequest} />, {
      wrapper: createWrapper(),
    });

    fireEvent.click(screen.getByText("Approve"));
    expect(
      await screen.findByText("Approve this request?"),
    ).toBeInTheDocument();
    expect(approveCalled).toBe(false);

    fireEvent.click(screen.getByText("Approve request"));
    await waitFor(() => expect(approveCalled).toBe(true));
  });

  it("names what it is about to approve", async () => {
    // A confirmation that hides the thing being confirmed asks for a
    // decision the reader cannot make. The dialog restates the card.
    render(
      <ApprovalDecisionButtons
        approval={{
          ...baseRequest,
          workflow_stages: [
            {
              order: 1,
              label: "Manager Review",
              approver_user_ids: [],
            },
            {
              order: 2,
              label: "Director Approval",
              approver_user_ids: [],
            },
          ],
          target_summary: {
            id: "doc-1",
            number: "INT/2026/110",
            type: "INT",
            partner_name: null,
            total_value: "1250.00",
            currency: "PLN",
            lines_count: 3,
            source_location_name: "Cold Store",
            target_location_name: "Rack C-2",
          },
        }}
      />,
      { wrapper: createWrapper() },
    );

    fireEvent.click(screen.getByText("Approve"));

    expect(
      await screen.findByText("Approve INT/2026/110?"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Internal Transfer/)).toBeInTheDocument();
    expect(screen.getByText(/3 lines/)).toBeInTheDocument();
    expect(screen.getByText("Cold Store → Rack C-2")).toBeInTheDocument();
    // And what the approval actually does to this request, not in general.
    expect(
      screen.getByText(/moves on to "Director Approval"/),
    ).toBeInTheDocument();
  });

  it("withdraws a request without a dialog in the way", async () => {
    // withdrawing your own open request changes nothing about the
    // document — the friction was upside down.
    signInWith(["approvals:read"], { id: "user-1" });
    let cancelCalled = false;
    server.use(
      http.post("/api/v1/approvals/requests/:id/cancel", () => {
        cancelCalled = true;
        return HttpResponse.json({ ...baseRequest, status: "CANCELLED" });
      }),
    );
    render(
      <ApprovalDecisionButtons
        approval={{ ...baseRequest, created_by: "user-1" }}
      />,
      { wrapper: createWrapper() },
    );

    fireEvent.click(screen.getByText("Withdraw request"));

    await waitFor(() => expect(cancelCalled).toBe(true));
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
    render(<ApprovalDecisionButtons approval={baseRequest} />, {
      wrapper: createWrapper(),
    });
    fireEvent.click(screen.getByText("Reject"));
    const input = await screen.findByPlaceholderText("Rejection reason");
    fireEvent.change(input, { target: { value: "Not ready" } });
    fireEvent.click(screen.getByText("Confirm Reject"));
    await waitFor(() => expect(receivedBody).not.toBeNull());
    expect(receivedBody).toEqual({ notes: "Not ready" });
  });

  it("rejects without notes when input is empty", async () => {
    // The reason is required on the UI side
    // (backend stays optional — Odoo/Coupa require it on the form, not
    // the API). The mutation must NOT be called when the notes field
    // is empty, and the user must see a validation hint.
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
    render(<ApprovalDecisionButtons approval={baseRequest} />, {
      wrapper: createWrapper(),
    });
    fireEvent.click(screen.getByText("Reject"));
    await screen.findByPlaceholderText("Rejection reason");
    fireEvent.click(screen.getByText("Confirm Reject"));
    // The validation hint should render synchronously after the click
    // (no mutation fires because the notes field is empty). Use
    // waitFor so the assertion matches the React 18 microtask
    // behaviour without a magic-number setTimeout.
    await waitFor(() =>
      expect(
        screen.getByText("Please provide a reason for rejecting"),
      ).toBeInTheDocument(),
    );
    expect(receivedBody).toBeNull();
  });

  it("wires the empty-reason error to the field it belongs to", async () => {
    // The block was the exact inverse of the document form — aria-invalid was
    // set but nothing pointed the reader at the message, and the field kept
    // its resting border, so a sighted user saw no change at all.
    render(<ApprovalDecisionButtons approval={baseRequest} />, {
      wrapper: createWrapper(),
    });
    fireEvent.click(screen.getByText("Reject"));
    const input = await screen.findByPlaceholderText("Rejection reason");
    fireEvent.click(screen.getByText("Confirm Reject"));

    await waitFor(() => expect(input).toHaveAttribute("aria-invalid", "true"));

    const describedBy = input.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    const message = document.getElementById(describedBy as string);
    expect(message).toHaveTextContent("Please provide a reason for rejecting");
    expect(message).toHaveAttribute("role", "alert");
    // The field itself has to look wrong, not just report wrong.
    expect(input.className).toContain("border-red-500");
  });

  it("drops the error wiring once the user types a reason", async () => {
    render(<ApprovalDecisionButtons approval={baseRequest} />, {
      wrapper: createWrapper(),
    });
    fireEvent.click(screen.getByText("Reject"));
    const input = await screen.findByPlaceholderText("Rejection reason");
    fireEvent.click(screen.getByText("Confirm Reject"));
    await waitFor(() => expect(input).toHaveAttribute("aria-invalid", "true"));

    fireEvent.change(input, { target: { value: "too expensive" } });

    await waitFor(() => expect(input).not.toHaveAttribute("aria-invalid"));
    expect(input).not.toHaveAttribute("aria-describedby");
  });

  it("cancels the reject input and resets notes", async () => {
    render(<ApprovalDecisionButtons approval={baseRequest} />, {
      wrapper: createWrapper(),
    });
    fireEvent.click(screen.getByText("Reject"));
    const input = await screen.findByPlaceholderText("Rejection reason");
    fireEvent.change(input, { target: { value: "draft" } });
    fireEvent.click(screen.getByText("Cancel"));
    expect(screen.getByText("Reject")).toBeInTheDocument();
    expect(
      screen.queryByPlaceholderText("Rejection reason"),
    ).not.toBeInTheDocument();
  });

  it("shows error toast when approve fails", async () => {
    const { toast } = await import("sonner");
    server.use(
      http.post("/api/v1/approvals/requests/:id/approve", () =>
        HttpResponse.json({ detail: "Already approved" }, { status: 400 }),
      ),
    );
    render(<ApprovalDecisionButtons approval={baseRequest} />, {
      wrapper: createWrapper(),
    });
    fireEvent.click(screen.getByText("Approve"));
    // approving is irreversible, so it asks first.
    fireEvent.click(await screen.findByText("Approve request"));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Already approved"),
    );
  });

  it("shows an error toast when the server refuses the rejection", async () => {
    // a refused reject (409 "Cannot reject your own request") used to
    // be read as silence — the dialog stayed open with the reason still in it
    // and nothing said why. The typed reason survives the failure so the
    // reader can retry without typing it again.
    const { toast } = await import("sonner");
    server.use(
      http.post("/api/v1/approvals/requests/:id/reject", () =>
        HttpResponse.json(
          {
            detail: {
              code: "APPROVAL_ERROR",
              message: "Cannot reject your own request",
            },
          },
          { status: 409 },
        ),
      ),
    );
    render(<ApprovalDecisionButtons approval={baseRequest} />, {
      wrapper: createWrapper(),
    });
    fireEvent.click(screen.getByText("Reject"));
    const input = await screen.findByPlaceholderText("Rejection reason");
    fireEvent.change(input, { target: { value: "Wrong supplier" } });
    fireEvent.click(screen.getByText("Confirm Reject"));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Cannot reject your own request",
      ),
    );
    expect(screen.getByPlaceholderText("Rejection reason")).toHaveValue(
      "Wrong supplier",
    );
  });

  it("shows an error toast when the reject adapter fails", async () => {
    // The documents and purchase-order queues reject through their own
    // endpoints via this adapter, so the failure path has to surface there
    // too — that is the route where the failure was seen.
    const { toast } = await import("sonner");
    const onReject = vi.fn().mockRejectedValue(
      Object.assign(new Error("Request failed"), {
        isAxiosError: true,
        response: {
          status: 409,
          data: {
            detail: {
              code: "APPROVAL_ERROR",
              message: "No pending approval request for this document",
            },
          },
        },
      }),
    );
    render(
      <ApprovalDecisionButtons approval={baseRequest} onReject={onReject} />,
      { wrapper: createWrapper() },
    );
    fireEvent.click(screen.getByText("Reject"));
    const input = await screen.findByPlaceholderText("Rejection reason");
    fireEvent.change(input, { target: { value: "Wrong supplier" } });
    fireEvent.click(screen.getByText("Confirm Reject"));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "No pending approval request for this document",
      ),
    );
  });

  it("renders full-width buttons when fullWidth is true", () => {
    render(<ApprovalDecisionButtons approval={baseRequest} fullWidth />, {
      wrapper: createWrapper(),
    });
    const approve = screen.getByText("Approve").closest("button");
    const reject = screen.getByText("Reject").closest("button");
    expect(approve).toHaveClass("w-full");
    expect(reject).toHaveClass("w-full");
  });

  it("keeps a thumb-sized target and lets the row wrap on a phone", async () => {
    // the actions were 95x36 and the last label broke across two lines
    // and ran past the card edge on a 390px screen. `h-11` is the 44px
    // touch height below `md:`, `flex-wrap` moves the row down whole, and
    // `whitespace-nowrap` keeps each label on one line. Only the classes are
    // checkable here — jsdom has no layout — so a measurement in a real
    // browser stays the source of the numbers.
    render(<ApprovalDecisionButtons approval={baseRequest} />, {
      wrapper: createWrapper(),
    });
    const approve = screen.getByText("Approve").closest("button");
    const reject = screen.getByText("Reject").closest("button");
    for (const button of [approve, reject]) {
      expect(button).toHaveClass("h-11");
      expect(button).toHaveClass("whitespace-nowrap");
    }
    expect(approve?.parentElement).toHaveClass("flex-wrap");
  });

  it("offers the decision to a delegated approver holding only read", async () => {
    // Naming someone on a stage hands them the decision — the server
    // says so in viewer_can_decide, and the buttons follow the verdict even
    // when the reader holds no approvals:approve.
    signInWith(["approvals:read"]);
    let approveCalled = false;
    server.use(
      http.post("/api/v1/approvals/requests/:id/approve", () => {
        approveCalled = true;
        return HttpResponse.json({ ...baseRequest, status: "APPROVED" });
      }),
    );
    render(
      <ApprovalDecisionButtons
        approval={{ ...baseRequest, viewer_can_decide: true }}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText("Approve")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Approve"));
    fireEvent.click(await screen.findByText("Approve request"));
    await waitFor(() => expect(approveCalled).toBe(true));
  });

  describe("without approvals:approve", () => {
    // The API rejects /approve and /reject for these users. The buttons used
    // to be offered anyway, so the rule arrived as a 403 toast after the
    // click.
    it("offers neither Approve nor Reject", () => {
      signInWith(["approvals:read"]);

      render(<ApprovalDecisionButtons approval={baseRequest} />, {
        wrapper: createWrapper(),
      });

      expect(screen.queryByText("Approve")).not.toBeInTheDocument();
      expect(screen.queryByText("Reject")).not.toBeInTheDocument();
    });

    it("still lets the requester withdraw their own request", () => {
      // /cancel carries no permission check — withdrawing is not a decision.
      signInWith(["approvals:read"], { id: "user-1" });

      render(
        <ApprovalDecisionButtons
          approval={{ ...baseRequest, created_by: "user-1" }}
        />,
        { wrapper: createWrapper() },
      );

      expect(screen.getByText("Withdraw request")).toBeInTheDocument();
      expect(screen.queryByText("Approve")).not.toBeInTheDocument();
    });

    it("renders nothing at all when there is also nothing to withdraw", () => {
      signInWith(["approvals:read"]);

      const { container } = render(
        <ApprovalDecisionButtons approval={baseRequest} />,
        { wrapper: createWrapper() },
      );

      expect(container).toBeEmptyDOMElement();
    });

    it("denies a signed-out reader too", () => {
      signOut();

      render(<ApprovalDecisionButtons approval={baseRequest} />, {
        wrapper: createWrapper(),
      });

      expect(screen.queryByText("Approve")).not.toBeInTheDocument();
    });
  });

  it("keeps the admin bypass the API applies", () => {
    signInWith([], { role: "admin" });

    render(<ApprovalDecisionButtons approval={baseRequest} />, {
      wrapper: createWrapper(),
    });

    expect(screen.getByText("Approve")).toBeInTheDocument();
  });

  it("clears the validation error when the user types a reason", async () => {
    render(<ApprovalDecisionButtons approval={baseRequest} />, {
      wrapper: createWrapper(),
    });
    fireEvent.click(screen.getByText("Reject"));
    await screen.findByPlaceholderText("Rejection reason");
    fireEvent.click(screen.getByText("Confirm Reject"));
    expect(
      screen.getByText("Please provide a reason for rejecting"),
    ).toBeInTheDocument();

    const input = screen.getByPlaceholderText("Rejection reason");
    fireEvent.change(input, { target: { value: "Now valid" } });
    expect(
      screen.queryByText("Please provide a reason for rejecting"),
    ).not.toBeInTheDocument();
  });
});
