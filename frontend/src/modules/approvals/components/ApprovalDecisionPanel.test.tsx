import { render, screen } from "@/test/utils";
import { beforeEach, describe, expect, it } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as React from "react";

import { ApprovalDecisionPanel } from "./ApprovalDecisionPanel";
import { signInWith } from "@/test/auth";
import type { ApprovalRequest } from "@/modules/approvals/api/approvals";

const baseRequest = {
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
    { order: 1, role: "manager", label: "Manager", approver_user_ids: [] },
  ],
  decisions: [],
  created_at: new Date().toISOString(),
} as unknown as ApprovalRequest;

function Wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("ApprovalDecisionPanel", () => {
  beforeEach(() => {
    signInWith(["approvals:approve"]);
  });

  it("shows the YOUR ACTION label and decision buttons while open", () => {
    render(
      <Wrapper>
        <ApprovalDecisionPanel approval={baseRequest} />
      </Wrapper>,
    );
    expect(screen.getByText("Your Action")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });

  it("shows the DECISION label instead of buttons once resolved", () => {
    const decided = {
      ...baseRequest,
      status: "APPROVED",
      decisions: [
        {
          id: "d-1",
          status: "APPROVED",
          approver_name: "Boss",
          decided_at: "2026-08-14T10:00:00Z",
        },
      ],
    } as unknown as ApprovalRequest;
    render(
      <Wrapper>
        <ApprovalDecisionPanel approval={decided} />
      </Wrapper>,
    );
    expect(screen.getByText("Decision")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Approve" }),
    ).not.toBeInTheDocument();
  });

  it("names the final stage's approver on a two-stage approval", () => {
    // The server returns the decisions in stage order, so the first
    // APPROVED row is the first stage's approver — not the one that
    // settled the request. That was stage two's, the last row.
    const twoStages = {
      ...baseRequest,
      status: "APPROVED",
      current_stage: 2,
      total_stages: 2,
      decisions: [
        {
          id: "d-1",
          stage_order: 1,
          status: "APPROVED",
          approver_name: "First Approver",
          decided_at: "2026-08-14T10:00:00Z",
        },
        {
          id: "d-2",
          stage_order: 2,
          status: "APPROVED",
          approver_name: "Final Approver",
          decided_at: "2026-08-14T11:00:00Z",
        },
      ],
    } as unknown as ApprovalRequest;
    render(
      <Wrapper>
        <ApprovalDecisionPanel approval={twoStages} />
      </Wrapper>,
    );
    expect(screen.getByText(/Final Approver/)).toBeInTheDocument();
    expect(screen.queryByText(/First Approver/)).not.toBeInTheDocument();
  });

  it("renders nothing at all for a cancelled request with no decision", () => {
    // A CANCELLED request carries no decision row, so the panel used
    // to render the "Decision" heading over an empty box.
    const cancelled = {
      ...baseRequest,
      status: "CANCELLED",
      decisions: [],
      cancelled_at: "2026-08-14T10:00:00Z",
    } as unknown as ApprovalRequest;

    const { container } = render(
      <Wrapper>
        <ApprovalDecisionPanel approval={cancelled} />
      </Wrapper>,
    );

    expect(screen.queryByText("Decision")).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });

  it("offers no decision on a request the viewer raised themselves", () => {
    // the grant is not the whole rule. The server answers whether
    // this reader may decide on this request; holding approvals:approve
    // does not let anyone approve their own.
    const own = {
      ...baseRequest,
      created_by: "current-user",
      viewer_can_decide: false,
    } as unknown as ApprovalRequest;

    render(
      <Wrapper>
        <ApprovalDecisionPanel approval={own} />
      </Wrapper>,
    );

    expect(
      screen.queryByRole("button", { name: "Approve" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Reject" }),
    ).not.toBeInTheDocument();
    // Withdrawing is not a decision — the requester keeps it.
    expect(
      screen.getByRole("button", { name: "Withdraw request" }),
    ).toBeInTheDocument();
  });

  it("lays the divider across the stack instead of beside it", () => {
    // in fullWidth every button is w-full, so the row wraps into a
    // vertical stack and a `w-px` divider lands on its own line as a
    // zero-width element — the empty gap between Reject and Cancel request.
    const own = {
      ...baseRequest,
      created_by: "current-user",
      viewer_can_decide: true,
    } as unknown as ApprovalRequest;

    const { container } = render(
      <Wrapper>
        <ApprovalDecisionPanel approval={own} />
      </Wrapper>,
    );

    const divider = container.querySelector('span[aria-hidden="true"]');
    expect(divider).not.toBeNull();
    expect(divider).toHaveClass("w-full");
    expect(divider).not.toHaveClass("w-px");
  });

  it("stops the actions filling the card above the phone breakpoint", () => {
    // full width is a phone answer. Three w-full buttons in a
    // column read as three equal options and cost the card the height
    // that made this queue scroll.
    render(
      <Wrapper>
        <ApprovalDecisionPanel approval={baseRequest} />
      </Wrapper>,
    );

    const approve = screen.getByRole("button", { name: "Approve" });
    expect(approve).toHaveClass("w-full");
    expect(approve).toHaveClass("sm:w-auto");
  });

  it("says the request is waiting when the reader cannot decide it", () => {
    // Not an empty box under a "Your Action" heading: the heading would be
    // claiming an action the API would refuse.
    signInWith(["approvals:read"]);

    render(
      <Wrapper>
        <ApprovalDecisionPanel approval={baseRequest} />
      </Wrapper>,
    );

    expect(screen.getByText("Awaiting Decision")).toBeInTheDocument();
    expect(
      screen.getByText(
        "You don't have permission to decide on approval requests.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Your Action")).not.toBeInTheDocument();
  });
});
