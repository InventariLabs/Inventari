import { describe, expect, it } from "vitest";
import { workingStatus } from "./documentApprovalGate";

// A document parked for an approval, with the approvals module switched off
// since, is worked as the confirmed document it was: the server takes the
// scanning, the press and the completion, so the page has to offer them.
describe("workingStatus", () => {
  it("works a document whose hold stood down as a confirmed one", () => {
    expect(
      workingStatus({ status: "PENDING_APPROVAL", hold_stood_down: true }),
    ).toBe("CONFIRMED");
  });

  it("leaves a document whose hold stands waiting", () => {
    expect(
      workingStatus({ status: "PENDING_APPROVAL", hold_stood_down: false }),
    ).toBe("PENDING_APPROVAL");
  });

  it("reads a row written without the field as its own status", () => {
    expect(workingStatus({ status: "PENDING_APPROVAL" })).toBe(
      "PENDING_APPROVAL",
    );
    expect(workingStatus({ status: "DRAFT" })).toBe("DRAFT");
  });
});
