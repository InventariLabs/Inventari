import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useState } from "react";

import { DocumentApprovalCard } from "./DocumentApprovalCard";

function Late() {
  const [shown, setShown] = useState(false);
  return (
    <>
      <button onClick={() => setShown(true)}>arrive</button>
      <DocumentApprovalCard>
        <div className="slot-container">
          {shown ? "Request Approval" : null}
        </div>
      </DocumentApprovalCard>
    </>
  );
}

describe("DocumentApprovalCard", () => {
  it("steps aside while the slot has nothing to say", () => {
    const { container } = render(
      <DocumentApprovalCard>
        <div className="flex">
          <div className="slot-container" />
        </div>
      </DocumentApprovalCard>,
    );
    // The `hidden` attribute, not a class: the page spaces its children with
    // `space-y`, which skips hidden ones — a class would leave the gap.
    expect(container.firstElementChild).toHaveAttribute("hidden");
  });

  it("shows its content when the slot has some", () => {
    const { container } = render(
      <DocumentApprovalCard>
        <div className="slot-container">Pending approval</div>
      </DocumentApprovalCard>,
    );
    expect(container.firstElementChild).not.toHaveAttribute("hidden");
    expect(screen.getByText("Pending approval")).toBeInTheDocument();
  });

  it("comes back when the slot fills in after the first render", async () => {
    // The approvals card renders nothing until the request read lands, then
    // either a button or a badge.
    const { container } = render(<Late />);
    const card = container.querySelector("div.p-4") as HTMLElement;
    expect(card).toHaveAttribute("hidden");

    act(() => {
      screen.getByText("arrive").click();
    });
    await waitFor(() => expect(card).not.toHaveAttribute("hidden"));
  });
});
