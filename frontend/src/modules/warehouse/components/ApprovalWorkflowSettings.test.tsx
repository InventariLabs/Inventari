import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import type { ReactNode } from "react";
import { render, screen } from "@/test/utils";

import { ApprovalWorkflowSettings } from "./ApprovalWorkflowSettings";
import { DOCUMENT_TYPES } from "@/modules/warehouse/types";
import { signInWith, signOut } from "@/test/auth";

// The approvals module fills this slot while it is on; what it says is its
// own tests' business. Switched off, the slot holds nothing and the warehouse
// speaks for itself — which is what this file keeps.
const approvalsOn = vi.hoisted(() => ({ value: false }));
vi.mock("@/components/Slot", () => ({
  TypedSlot: ({
    name,
    data,
    fallback,
  }: {
    name: string;
    data: unknown;
    fallback?: ReactNode;
  }) =>
    approvalsOn.value ? (
      <div data-testid={`slot-${name}`} data-requested={JSON.stringify(data)} />
    ) : (
      <>{fallback}</>
    ),
}));

const baseProps = {
  approvalThreshold: "",
  approvalRequiredTypes: [],
  onThresholdChange: vi.fn(),
  onTypeToggle: vi.fn(),
};

describe("ApprovalWorkflowSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    approvalsOn.value = true;
    signInWith(["approvals:read"]);
  });

  afterEach(() => {
    signOut();
  });

  it("names the workflow half of the approval rule, not only the profile half", () => {
    // The sentence used to describe only the threshold and the type list,
    // while an active document workflow already parked every confirmed
    // document on its own — measured: empty profile, workflow active, and
    // each confirm landed on PENDING_APPROVAL.
    render(<ApprovalWorkflowSettings {...baseProps} />);

    expect(
      screen.getByText(/document workflow decides who approves/i),
    ).toBeInTheDocument();
  });

  it("hands the approvals module's notice whether approval is asked for at all", () => {
    const { rerender } = render(<ApprovalWorkflowSettings {...baseProps} />);
    expect(
      screen.getByTestId("slot-document_approval_setup_notice"),
    ).toHaveAttribute(
      "data-requested",
      JSON.stringify({ approvalRequested: false }),
    );

    rerender(
      <ApprovalWorkflowSettings {...baseProps} approvalThreshold="100" />,
    );
    expect(
      screen.getByTestId("slot-document_approval_setup_notice"),
    ).toHaveAttribute(
      "data-requested",
      JSON.stringify({ approvalRequested: true }),
    );

    rerender(
      <ApprovalWorkflowSettings
        {...baseProps}
        approvalRequiredTypes={["IN"]}
      />,
    );
    expect(
      screen.getByTestId("slot-document_approval_setup_notice"),
    ).toHaveAttribute(
      "data-requested",
      JSON.stringify({ approvalRequested: true }),
    );
  });

  it("gives the two Confirmed visits in the flow legend different names", () => {
    // The cycle visits CONFIRMED twice — once before the document goes out
    // for approval, once after the approval is granted and the document is
    // back. The legend printed the same word for both visits, so the phase
    // before the wait was indistinguishable from the phase after it.
    render(<ApprovalWorkflowSettings {...baseProps} />);

    const legend = screen.getByTestId("approval-flow-legend");
    const names = Array.from(legend.querySelectorAll("[data-phase]")).map(
      (el) => el.textContent,
    );

    expect(names).toEqual([
      "Draft",
      "Confirmed",
      "Waiting for approval",
      "Confirmed (after approval)",
      "Completed",
    ]);
    expect(new Set(names).size).toBe(names.length);
  });

  it("names the document types instead of printing their codes", () => {
    // The chips read IN / OUT / SCRAP while the screen above them called the
    // same documents Receipt, Delivery and Scrap. Nobody asked for approval
    // on "OUT".
    render(<ApprovalWorkflowSettings {...baseProps} />);

    expect(screen.getByText("Scrap")).toBeInTheDocument();
    expect(screen.getByText("Correction")).toBeInTheDocument();
    expect(screen.queryByText("SCRAP")).toBeNull();
    expect(screen.queryByText("OUT")).toBeNull();
  });

  it("offers every type the module knows", () => {
    render(<ApprovalWorkflowSettings {...baseProps} />);

    expect(screen.getAllByRole("checkbox")).toHaveLength(DOCUMENT_TYPES.length);
  });

  // With the Approvals module off nothing contributes the notice, and the
  // warehouse speaks for itself.
  describe("with the Approvals module off", () => {
    beforeEach(() => {
      approvalsOn.value = false;
    });

    it("points at the module store", async () => {
      render(
        <ApprovalWorkflowSettings
          {...baseProps}
          approvalRequiredTypes={["IN"]}
        />,
      );

      expect(
        await screen.findByText(/The Approvals module is off/),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Open apps" }),
      ).toBeInTheDocument();
    });

    it("overrides every combination with one sentence", () => {
      render(
        <ApprovalWorkflowSettings {...baseProps} approvalThreshold="100" />,
      );

      expect(screen.getByTestId("approval-consequence")).toHaveTextContent(
        /no document waits for approval — confirming executes directly/i,
      );
    });

    it("keeps the warning quiet while nothing asks for approval", () => {
      render(<ApprovalWorkflowSettings {...baseProps} />);

      expect(
        screen.queryByRole("button", { name: "Open apps" }),
      ).not.toBeInTheDocument();
    });

    it("keeps the warning quiet for an account that cannot see the approval setup", () => {
      signInWith([]);
      render(
        <ApprovalWorkflowSettings
          {...baseProps}
          approvalRequiredTypes={["IN"]}
        />,
      );

      expect(
        screen.queryByRole("button", { name: "Open apps" }),
      ).not.toBeInTheDocument();
    });
  });
});
