import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import type { TargetApprovalRequest } from "@/lib/moduleRegistry";
import { signInWith } from "@/test/auth";
import { ApprovalDecisionPanelSlot } from "./ApprovalDecisionPanelSlot";

const approval = {
  id: "req-1",
  organization_id: "org-1",
  workflow_id: "wf-1",
  target_type: "document",
  target_id: "doc-42",
  status: "PENDING",
  current_stage: 1,
  total_stages: 2,
  created_by: "user-1",
  created_by_name: "Alice",
  meta_data: null,
  workflow_stages: [
    {
      order: 1,
      role: "manager",
      label: "Manager Review",
      approver_user_ids: [],
    },
    { order: 2, role: "director", label: "Director", approver_user_ids: [] },
  ],
  decisions: [],
  created_at: new Date().toISOString(),
  viewer_can_decide: true,
} as unknown as TargetApprovalRequest;

describe("ApprovalDecisionPanelSlot", () => {
  beforeEach(() => {
    signInWith(["approvals:approve"]);
  });

  it("shows how far the request has got, with the decision beside it", () => {
    render(
      <ApprovalDecisionPanelSlot
        data={{ approval, onApprove: vi.fn(), onReject: vi.fn() }}
      />,
    );

    expect(screen.getByText("Approval Progress")).toBeInTheDocument();
    expect(screen.getByText("Manager Review")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });

  it("decides through the target module's adapter, not the generic endpoint", async () => {
    const onApprove = vi.fn().mockResolvedValue(undefined);
    render(
      <ApprovalDecisionPanelSlot
        data={{ approval, onApprove, onReject: vi.fn() }}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    const confirm = await screen.findAllByRole("button", { name: /approve/i });
    await userEvent.click(confirm[confirm.length - 1]);

    await waitFor(() => expect(onApprove).toHaveBeenCalled());
    expect(onApprove.mock.calls[0][0]).toBe(approval);
  });
});
