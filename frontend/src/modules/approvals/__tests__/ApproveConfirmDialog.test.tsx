import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { ApproveConfirmDialog } from "../components/ApproveConfirmDialog";
import type { ApprovalRequest } from "../api/approvals";

const baseRequest: ApprovalRequest = {
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
  workflow_stages: [{ order: 1, label: "Manager", approver_user_ids: [] }],
  decisions: [],
  created_at: new Date().toISOString(),
};

const renderDialog = (approval: ApprovalRequest) =>
  render(
    <ApproveConfirmDialog
      open
      approval={approval}
      onConfirm={() => {}}
      onCancel={() => {}}
    />,
  );

describe("ApproveConfirmDialog", () => {
  it("promises the status change, not a stock move, for a final document approval", () => {
    // Approving the last stage runs confirm_after_approval: the document
    // goes from PENDING_APPROVAL to CONFIRMED and nothing else — the stock
    // moves only when someone later runs the receipt from the document page.
    // The dialog used to promise "which moves its stock", so whoever believed
    // it never came back for the receipt and the book said nothing arrived.
    // The text must keep saying what the backend does.
    renderDialog(baseRequest);

    const message = screen.getByText(/last stage/);
    expect(message).toHaveTextContent("ready for warehouse execution");
    // The stock-move promise must not survive in any wording.
    expect(message.textContent).not.toMatch(/moves? (its |the )?stock/);
  });

  it("uses the same warehouse-execution wording the document confirm dialog uses", () => {
    // Both dialogs stand in front of the same transition — they must tell
    // the same story about it, not two stories about one status change.
    renderDialog(baseRequest);

    const message = screen.getByText(/last stage/);
    expect(message.textContent).toBe(
      "This is the last stage — your approval completes the request and " +
        "marks the document ready for warehouse execution. It cannot be " +
        "taken back.",
    );
  });

  it("says the approval posts the stock for a one-step submission", () => {
    // A document the one-step action submitted carries
    // ``posts_on_approval``: the approval completes it and moves the stock
    // now. Promising "ready for warehouse execution" would send the reader
    // looking for a receipt that has already happened.
    renderDialog({
      ...baseRequest,
      target_summary: {
        id: "doc-1",
        number: "OUT/2026/110",
        type: "OUT",
        partner_name: "Harper Catering",
        total_value: null,
        currency: null,
        lines_count: 1,
        posts_on_approval: true,
      },
    });

    const message = screen.getByText(/last stage/);
    expect(message).toHaveTextContent(
      "posts the document's stock movement now",
    );
    expect(message.textContent).not.toMatch(/warehouse execution/);
  });

  it("keeps the next-stage wording for a request that is not on its last stage", () => {
    // Mid-flow approvals never claimed a stock move — a stage decision just
    // hands the request on. The fix is scoped to the final-document branch.
    renderDialog({
      ...baseRequest,
      total_stages: 2,
      workflow_stages: [
        { order: 1, label: "Manager", approver_user_ids: [] },
        { order: 2, label: "Director", approver_user_ids: [] },
      ],
    });

    expect(screen.getByText(/moves on to "Director"/)).toBeInTheDocument();
    expect(screen.queryByText(/warehouse execution/)).not.toBeInTheDocument();
  });

  it("uses the generic final wording for a non-document target", () => {
    // Only the document branch ever promised stock movement, so only it
    // carries the warehouse-execution sentence.
    renderDialog({
      ...baseRequest,
      target_type: "purchase_order",
    });

    const message = screen.getByText(/last stage/);
    expect(message).toHaveTextContent("completes the request");
    expect(message.textContent).not.toMatch(/warehouse execution/);
  });

  it("names the document in the title when the summary carries a number", () => {
    renderDialog({
      ...baseRequest,
      target_summary: {
        id: "doc-1",
        number: "INT/2026/110",
        type: "INT",
        partner_name: null,
        total_value: null,
        currency: null,
        lines_count: 1,
      },
    });

    expect(screen.getByText("Approve INT/2026/110?")).toBeInTheDocument();
  });

  it("names an unlabelled stage by its order and still sees the next stage", () => {
    renderDialog({
      ...baseRequest,
      total_stages: 2,
      workflow_stages: [
        { order: 1, label: "", approver_user_ids: [] },
        { order: 2, label: "", approver_user_ids: [] },
      ],
    });

    expect(screen.getByText(/moves on to/)).toHaveTextContent(
      'Stage "#1" gets your approval and the request moves on to "#2"',
    );
  });
});
