import { describe, expect, it } from "vitest";
import { isDisposalReason } from "./stockReasons";

/**
 * Which "where did it go" answers mean the goods were thrown out. The
 * remove-from-stock window routes these to the discard endpoint — the one
 * whose action the ledger, the journal and the waste report can tell apart
 * from a use, so the waste report counts what was thrown out.
 */
describe("isDisposalReason", () => {
  it("routes the thrown-out reasons to disposal", () => {
    expect(isDisposalReason("DISPOSED")).toBe(true);
    expect(isDisposalReason("DAMAGED")).toBe(true);
    expect(isDisposalReason("EXPIRED")).toBe(true);
  });

  it("keeps the rest on the consume path", () => {
    expect(isDisposalReason("USED")).toBe(false);
    expect(isDisposalReason("OTHER")).toBe(false);
    expect(isDisposalReason("TEST_DATA")).toBe(false);
  });
});
