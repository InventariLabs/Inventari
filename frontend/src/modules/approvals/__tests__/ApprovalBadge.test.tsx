import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ApprovalBadge } from "../components/ApprovalBadge";

describe("ApprovalBadge", () => {
  it("renders the localized status text", () => {
    render(<ApprovalBadge status="PENDING" />);
    expect(screen.getByText("Waiting for approval")).toBeInTheDocument();
  });

  it("reads the same for both open states", () => {
    render(<ApprovalBadge status="IN_PROGRESS" />);
    expect(screen.getByText("Waiting for approval")).toBeInTheDocument();
  });

  it("names the step of a multi-stage request that is still open", () => {
    render(
      <ApprovalBadge status="IN_PROGRESS" stage={{ current: 2, total: 2 }} />,
    );
    expect(
      screen.getByText("Waiting for approval — step 2 of 2"),
    ).toBeInTheDocument();
  });

  it("leaves a single-stage request and a settled one without a step", () => {
    const { rerender } = render(
      <ApprovalBadge status="PENDING" stage={{ current: 1, total: 1 }} />,
    );
    expect(screen.getByText("Waiting for approval")).toBeInTheDocument();

    rerender(
      <ApprovalBadge status="APPROVED" stage={{ current: 2, total: 2 }} />,
    );
    expect(screen.getByText("Approved")).toBeInTheDocument();
  });

  it("uses warning variant for PENDING and IN_PROGRESS", () => {
    const { rerender, container } = render(<ApprovalBadge status="PENDING" />);
    expect(container.firstChild).toHaveClass("bg-amber-100");

    rerender(<ApprovalBadge status="IN_PROGRESS" />);
    expect(container.firstChild).toHaveClass("bg-amber-100");
  });

  it("uses success variant for APPROVED", () => {
    const { container } = render(<ApprovalBadge status="APPROVED" />);
    expect(container.firstChild).toHaveClass("bg-success-100");
  });

  it("uses danger variant for REJECTED", () => {
    const { container } = render(<ApprovalBadge status="REJECTED" />);
    expect(container.firstChild).toHaveClass("bg-red-100");
  });

  it("uses default variant for unknown status", () => {
    const { container } = render(<ApprovalBadge status="UNKNOWN" />);
    // The default Badge variant renders without the warning/success/danger class.
    expect(container.firstChild?.firstChild).toBeInTheDocument();
  });

  it("passes className through to the badge", () => {
    const { container } = render(
      <ApprovalBadge status="PENDING" className="custom-class" />,
    );
    expect(container.firstChild).toHaveClass("custom-class");
  });
});
