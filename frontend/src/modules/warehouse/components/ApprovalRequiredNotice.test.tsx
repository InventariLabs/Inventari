import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApprovalRequiredNotice } from "@/modules/warehouse/components/ApprovalRequiredNotice";

const base = {
  hasPendingApproval: false,
  approvalRequiredNoRequest: false,
  approvalWorkflowMissing: false,
};

describe("ApprovalRequiredNotice", () => {
  it("says on the card that approval is required and no request is open", () => {
    render(
      <ApprovalRequiredNotice
        gate={{ ...base, approvalRequiredNoRequest: true }}
      />,
    );
    expect(screen.getByTestId("approval-required-notice")).toBeInTheDocument();
  });

  it("names the missing workflow when none is active", () => {
    render(
      <ApprovalRequiredNotice
        gate={{
          ...base,
          approvalRequiredNoRequest: true,
          approvalWorkflowMissing: true,
        }}
      />,
    );
    expect(screen.getByTestId("approval-required-notice")).toBeInTheDocument();
  });

  it("is silent when nothing is required", () => {
    render(<ApprovalRequiredNotice gate={base} />);
    expect(screen.queryByTestId("approval-required-notice")).toBeNull();
  });
});
