import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { DocumentApprovalRejectedBanner } from "../components/DocumentApprovalRejectedBanner";
import type { ApprovalRequest } from "@/modules/approvals/api/approvals";

const baseApproval: ApprovalRequest = {
  id: "req-1",
  organization_id: "org-1",
  workflow_id: "wf-1",
  target_type: "document",
  target_id: "doc-42",
  status: "REJECTED",
  current_stage: 1,
  total_stages: 2,
  created_by: "user-1",
  created_by_name: "Alice",
  meta_data: null,
  workflow_stages: [],
  decisions: [
    {
      id: "d-1",
      stage_order: 1,
      approver_id: "u-2",
      approver_name: "Bob Manager",
      status: "REJECTED",
      notes: "Numbers don't add up",
      decided_at: "2026-07-26T10:00:00Z",
      created_at: "2026-07-26T10:00:00Z",
    },
  ],
  created_at: "2026-07-26T09:00:00Z",
};

const renderWithRouter = (ui: React.ReactNode) =>
  render(<BrowserRouter>{ui}</BrowserRouter>);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("DocumentApprovalRejectedBanner", () => {
  it("renders the rejection reason and the approver name", () => {
    renderWithRouter(
      <DocumentApprovalRejectedBanner
        approval={baseApproval}
        documentId="doc-42"
      />,
    );
    expect(screen.getByText("Rejected by Bob Manager")).toBeInTheDocument();
    expect(screen.getByText(/Numbers don't add up/)).toBeInTheDocument();
  });

  it("renders the CTA as a link to the document detail with #edit", () => {
    renderWithRouter(
      <DocumentApprovalRejectedBanner
        approval={baseApproval}
        documentId="doc-42"
      />,
    );
    const link = screen.getByRole("link", {
      name: "Edit and re-submit",
    });
    expect(link).toHaveAttribute("href", "/warehouse/documents/doc-42#edit");
  });

  it("renders nothing when it is handed no request", () => {
    // The page hands the banner the request that still speaks for the
    // document — none once the document has moved past its rejection.
    const { container } = renderWithRouter(
      <DocumentApprovalRejectedBanner approval={null} documentId="doc-42" />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when no decision is REJECTED", () => {
    const noReject: ApprovalRequest = {
      ...baseApproval,
      status: "APPROVED",
      decisions: [
        {
          ...baseApproval.decisions[0]!,
          status: "APPROVED",
          notes: null,
        },
      ],
    };
    const { container } = renderWithRouter(
      <DocumentApprovalRejectedBanner
        approval={noReject}
        documentId="doc-42"
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("falls back to a generic someone label when approver_name is null", () => {
    const noName: ApprovalRequest = {
      ...baseApproval,
      decisions: [
        {
          ...baseApproval.decisions[0]!,
          approver_name: null,
        },
      ],
    };
    renderWithRouter(
      <DocumentApprovalRejectedBanner approval={noName} documentId="doc-42" />,
    );
    expect(screen.getByText("Rejected by an approver")).toBeInTheDocument();
  });
});
