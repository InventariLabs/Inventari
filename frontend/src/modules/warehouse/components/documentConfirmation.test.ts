import { describe, expect, it } from "vitest";

import { documentApprover, documentConfirmation } from "./documentConfirmation";

const stamped = {
  confirmed_at: "2026-10-10T09:00:00Z",
  confirmed_by: "u-submitter",
  confirmed_by_name: "Rita Requester",
};

const approved = (decidedAt = "2026-10-10T10:00:00Z") => ({
  status: "APPROVED",
  created_at: "2026-10-10T09:00:00Z",
  decisions: [{ status: "APPROVED", decided_at: decidedAt }],
});

describe("documentConfirmation", () => {
  it("shows no confirmation on a draft whatever the record holds", () => {
    expect(documentConfirmation({ status: "DRAFT", ...stamped })).toBeNull();
  });

  it("shows no confirmation while the document waits for approval", () => {
    expect(
      documentConfirmation({ status: "PENDING_APPROVAL", ...stamped }),
    ).toBeNull();
  });

  it("names the confirmer on a document that never went through approval", () => {
    expect(documentConfirmation({ status: "CONFIRMED", ...stamped })).toEqual({
      at: "2026-10-10T09:00:00Z",
      by: "u-submitter",
      byName: "Rita Requester",
    });
  });

  it("keeps the confirmer, dated at the approval, on a document the approval let through", () => {
    // The approval does not overwrite the confirmation: the person who
    // confirmed the document keeps their name, and the moment is when the
    // document became confirmed.
    expect(
      documentConfirmation({
        status: "CONFIRMED",
        ...stamped,
        approval: approved(),
      }),
    ).toEqual({
      at: "2026-10-10T10:00:00Z",
      by: "u-submitter",
      byName: "Rita Requester",
    });
  });

  it("keeps a later confirmation after an approved request", () => {
    // Legacy stamps are recovered by the detail API from the journal; a
    // later real confirmation must not lose its actor in the client.
    expect(
      documentConfirmation({
        status: "CONFIRMED",
        confirmed_at: "2026-10-10T10:05:00Z",
        confirmed_by: "u-approver",
        confirmed_by_name: "Admin",
        approval: approved(),
      }),
    ).toEqual({
      at: "2026-10-10T10:05:00Z",
      by: "u-approver",
      byName: "Admin",
    });
  });

  it("keeps the confirmation after a withdrawn request", () => {
    // Withdrawing takes back the question, not the confirmation that asked
    // it: the document stands confirmed, with its author named.
    expect(
      documentConfirmation({
        status: "CONFIRMED",
        ...stamped,
        approval: { status: "CANCELLED", created_at: "2026-10-10T09:00:00Z" },
      }),
    ).toEqual({
      at: "2026-10-10T09:00:00Z",
      by: "u-submitter",
      byName: "Rita Requester",
    });
  });

  it("keeps a confirmation stamped at or after a rejected request", () => {
    expect(
      documentConfirmation({
        status: "CONFIRMED",
        confirmed_at: "2026-10-10T09:30:02Z",
        confirmed_by: "u-requester",
        confirmed_by_name: "Rita Requester",
        approval: {
          status: "REJECTED",
          created_at: "2026-10-10T09:00:00Z",
          decisions: [
            { status: "REJECTED", decided_at: "2026-10-10T09:30:00Z" },
          ],
        },
      }),
    ).toMatchObject({ at: "2026-10-10T09:30:02Z", byName: "Rita Requester" });
  });
});

describe("documentApprover", () => {
  it("names the last approving decision of an approved request", () => {
    expect(
      documentApprover({
        approval: {
          status: "APPROVED",
          created_at: "2026-10-10T09:00:00Z",
          decisions: [
            {
              status: "APPROVED",
              decided_at: "2026-10-10T10:00:00Z",
              decided_by: "u-first",
              decided_by_name: "First Approver",
            },
            {
              status: "APPROVED",
              decided_at: "2026-10-10T11:00:00Z",
              decided_by: "u-second",
              decided_by_name: "Second Approver",
            },
          ],
        },
      }),
    ).toEqual({
      at: "2026-10-10T11:00:00Z",
      by: "u-second",
      byName: "Second Approver",
    });
  });

  it("names nobody while the request is undecided", () => {
    expect(
      documentApprover({
        approval: { status: "PENDING", created_at: "2026-10-10T09:00:00Z" },
      }),
    ).toBeNull();
  });

  it("names nobody on a rejected or withdrawn request", () => {
    expect(
      documentApprover({
        approval: {
          status: "REJECTED",
          decisions: [
            { status: "REJECTED", decided_at: "2026-10-10T10:00:00Z" },
          ],
        },
      }),
    ).toBeNull();
    expect(
      documentApprover({
        approval: { status: "CANCELLED", created_at: "2026-10-10T09:00:00Z" },
      }),
    ).toBeNull();
  });

  it("names nobody on a document that went through no approval", () => {
    expect(documentApprover({})).toBeNull();
  });
});
