import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { POActionBar } from "../POActionBar";
import type { PurchaseOrder } from "../../types/purchase-orders";

function draftOrder(): PurchaseOrder {
  return {
    id: "po-1",
    organization_id: "org-1",
    number: "PO/2026/001",
    status: "DRAFT",
    partner_id: null,
    scheduled_date: null,
    notes: null,
    currency: "PLN",
    created_by: "u1",
    confirmed_by: null,
    confirmed_at: null,
    cancelled_by: null,
    cancelled_at: null,
    created_at: "2026-09-18T10:00:00Z",
    updated_at: "2026-09-18T10:00:00Z",
    lines: [],
  };
}

const baseProps = {
  canManage: true,
  canDecide: true,
  canWrite: true,
  approvalsEnabled: true,
  hasPendingApproval: false,
  viewer_can_decide: null,
  pdfPending: false,
  onEdit: vi.fn(),
  onAction: vi.fn(),
  onDownloadPdf: vi.fn(),
  onReceive: vi.fn(),
};

describe("POActionBar", () => {
  it("offers no request action on a draft when no approval workflow exists", () => {
    render(
      <POActionBar
        {...baseProps}
        po={draftOrder()}
        workflowConfigured={false}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /request approval/i }),
    ).not.toBeInTheDocument();
    // The gate covers only the request: the draft is still editable and
    // confirmable, so a missing workflow must not bury the order itself.
    expect(
      screen.getByRole("button", { name: /confirm/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /edit/i })).toBeInTheDocument();
  });

  it("keeps offering the request while the server has not answered yet", () => {
    render(
      <POActionBar
        {...baseProps}
        po={draftOrder()}
        workflowConfigured={undefined}
      />,
    );

    expect(
      screen.getByRole("button", { name: /request approval/i }),
    ).toBeInTheDocument();
  });

  it("offers the request once a workflow is configured", () => {
    render(
      <POActionBar
        {...baseProps}
        po={draftOrder()}
        workflowConfigured={true}
      />,
    );

    expect(
      screen.getByRole("button", { name: /request approval/i }),
    ).toBeInTheDocument();
  });

  it("hides Approve/Reject from a manager who may not decide", () => {
    // The endpoint checks `approvals:approve`, not `purchase_orders:manage`.
    render(
      <POActionBar
        {...baseProps}
        canDecide={false}
        po={{ ...draftOrder(), status: "PENDING_APPROVAL" }}
        hasPendingApproval={true}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /^approve$/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^reject$/i }),
    ).not.toBeInTheDocument();
  });

  it("offers Approve/Reject to an approver who is not a manager", () => {
    render(
      <POActionBar
        {...baseProps}
        canManage={false}
        canDecide={true}
        po={{ ...draftOrder(), status: "PENDING_APPROVAL" }}
        hasPendingApproval={true}
      />,
    );

    expect(
      screen.getByRole("button", { name: /^approve$/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^reject$/i }),
    ).toBeInTheDocument();
  });

  it("leaves the decision to the approval card while the card is on the page", async () => {
    const user = userEvent.setup();
    // The card shows the stage, who approved before and the decision; the
    // header offered the same Approve and Reject a second time.
    render(
      <POActionBar
        {...baseProps}
        approvalCardShown
        po={{ ...draftOrder(), status: "PENDING_APPROVAL" }}
        hasPendingApproval={true}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /^approve$/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^reject$/i }),
    ).not.toBeInTheDocument();
    // Cancelling the order is the order's own action, not the request's —
    // and it sits in the menu, not on the header row.
    expect(
      screen.queryByRole("button", { name: /cancel/i }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /more actions/i }));
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
  });

  it("leaves asking again to the approval card too", () => {
    render(
      <POActionBar
        {...baseProps}
        approvalCardShown
        po={{ ...draftOrder(), status: "PENDING_APPROVAL" }}
        hasPendingApproval={false}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /request approval/i }),
    ).not.toBeInTheDocument();
  });

  it("says why Send to supplier is disabled on an order with no supplier", () => {
    render(
      <POActionBar
        {...baseProps}
        po={{ ...draftOrder(), status: "CONFIRMED" }}
        workflowConfigured={false}
      />,
    );

    const send = screen.getByRole("button", { name: /send to supplier/i });
    expect(send).toBeDisabled();
    expect(send.parentElement).toHaveAttribute(
      "title",
      expect.stringMatching(/no supplier/i),
    );
  });

  it("receives a confirmed order on the receive screen, with a parcel, not the download arrow", async () => {
    const onReceive = vi.fn();
    const { container } = render(
      <POActionBar
        {...baseProps}
        po={{ ...draftOrder(), status: "CONFIRMED", partner_id: "partner-1" }}
        onReceive={onReceive}
      />,
    );

    const receive = screen.getByRole("button", { name: "Receive delivery" });
    await userEvent.click(receive);
    expect(onReceive).toHaveBeenCalledTimes(1);
    // Two arrows into a tray side by side read as one action twice.
    const receiveIcon = receive.querySelector("svg")?.getAttribute("class");
    const pdfIcon = screen
      .getByRole("button", { name: "Download PDF" })
      .querySelector("svg")
      ?.getAttribute("class");
    expect(receiveIcon).toContain("lucide-package-plus");
    expect(receiveIcon).not.toBe(pdfIcon);
    expect(container.querySelector(".lucide-arrow-down-to-line")).toBeNull();
  });

  it("says why an order without a supplier cannot be received", () => {
    render(
      <POActionBar
        {...baseProps}
        po={{ ...draftOrder(), status: "CONFIRMED", partner_id: null }}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Receive delivery" }),
    ).toBeDisabled();
    expect(
      screen.getByTitle("The order names no supplier."),
    ).toBeInTheDocument();
  });
});
