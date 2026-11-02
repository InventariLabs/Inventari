/**
 * The sentence the confirm dialog opens with has to describe what the server
 * will actually do — the page reads the rule's answer and words it, and a
 * reader decides from that sentence whether to press Confirm.
 *
 * Four states, four properties. When approval is required and a workflow
 * exists the document is handed over and waits; when it is required and no
 * workflow exists the server will refuse, so the sentence refuses first;
 * a configured threshold is worth naming only while the approvals module is
 * switched on; and when nothing gates it the sentence must not invent a
 * hand-off the server will never make.
 */
import { describe, expect, it } from "vitest";
import i18next from "i18next";

import type { DocumentStatus } from "@/modules/warehouse/types";

import { confirmDialogMessage, confirmDialogTitle } from "./DocumentDetailPage";

const doc = { type: "IN", status: "DRAFT" as DocumentStatus };

const t = (key: string, options?: Record<string, unknown>) =>
  i18next.t(`warehouse:${key}`, options) as string;

describe("DocumentDetailPage.confirmDialogMessage", () => {
  it("the approve case says the document waits for a workflow", () => {
    const message = confirmDialogMessage(
      "confirm",
      doc,
      {
        required: true,
        workflowConfigured: true,
        hasThreshold: false,
        approvalsEnabled: true,
      },
      t,
    );

    // It promises the hand-off and nothing else: the document goes to the
    // queue and waits there, so the sentence says so and does not claim a
    // straight run to execution.
    expect(message).toMatch(/approval queue|workflow/i);
    expect(message).toMatch(/continue/i);
    expect(message).not.toMatch(/ready for warehouse execution/i);
  });

  it("the required case with no workflow says confirming will be refused", () => {
    const message = confirmDialogMessage(
      "confirm",
      doc,
      {
        required: true,
        workflowConfigured: false,
        hasThreshold: false,
        approvalsEnabled: true,
      },
      t,
    );

    // This is the state the old sentence walked into: approval required,
    // nobody to give it, and a dialog promising a place in the queue the
    // next click answered with a 400.
    expect(message).not.toMatch(/approval queue/i);
    expect(message).not.toMatch(/ready for warehouse execution/i);
    expect(message).toMatch(/no approval workflow/i);
    expect(message).toMatch(/refused/i);
  });

  it("the non-approve case promises neither a queue nor a workflow", () => {
    const message = confirmDialogMessage(
      "confirm",
      doc,
      {
        required: false,
        workflowConfigured: false,
        hasThreshold: false,
        approvalsEnabled: true,
      },
      t,
    );

    expect(message).not.toMatch(/approval queue/i);
    expect(message).not.toMatch(/workflow/i);
    expect(message).toMatch(/mark the document ready/i);
    expect(message).toMatch(/continue/i);
  });

  it("a configured threshold is named while the approvals module is on", () => {
    const message = confirmDialogMessage(
      "confirm",
      doc,
      {
        required: false,
        workflowConfigured: false,
        hasThreshold: true,
        approvalsEnabled: true,
      },
      t,
    );

    expect(message).toMatch(/approval threshold/i);
    expect(message).toMatch(/approval queue/i);
    expect(message).toMatch(/continue/i);
  });

  it("a threshold names no queue while the approvals module is off", () => {
    const message = confirmDialogMessage(
      "confirm",
      doc,
      {
        required: false,
        workflowConfigured: false,
        hasThreshold: true,
        approvalsEnabled: false,
      },
      t,
    );

    // The server's gate stands down with the module, so nothing is sent
    // anywhere: the threshold is inert and naming it would promise an
    // exception that cannot happen.
    expect(message).not.toMatch(/approval queue/i);
    expect(message).not.toMatch(/threshold/i);
    expect(message).toMatch(/mark the document ready/i);
    expect(message).toMatch(/continue/i);
  });

  describe("when nobody could decide the stage the document would wait at", () => {
    const base = {
      required: true,
      workflowConfigured: true,
      hasThreshold: false,
      approvalsEnabled: true,
    };

    it("names the stage and says the approval queue will not decide it", () => {
      const message = confirmDialogMessage(
        "confirm",
        doc,
        {
          ...base,
          deadEnd: {
            reason: "named_approvers_cannot_decide",
            stage: "Peer review",
          },
        },
        t,
      );

      // The old sentence promised "the approval queue" for a request that no
      // queue would ever show; the new one says why and what ends the wait.
      expect(message).not.toMatch(/send this document to the approval queue/i);
      expect(message).toMatch(/nobody could decide it/i);
      expect(message).toMatch(/“Peer review”/);
      expect(message).toMatch(/cannot see approvals/i);
      expect(message).toMatch(/withdrawn/i);
    });

    it("says the asker is the only one who could approve", () => {
      const message = confirmDialogMessage(
        "confirm",
        doc,
        {
          ...base,
          deadEnd: {
            reason: "only_the_requester_can_decide",
            stage: "Manager Approval",
          },
        },
        t,
      );

      expect(message).toMatch(/the only person who can approve/i);
      expect(message).toMatch(/is you/i);
    });

    it("says nobody holds the grant", () => {
      const message = confirmDialogMessage(
        "confirm",
        doc,
        {
          ...base,
          deadEnd: {
            reason: "no_approver_in_organization",
            stage: "Manager Approval",
          },
        },
        t,
      );

      expect(message).toMatch(/nobody in this organization holds it/i);
    });

    it("keeps the plain sentence when the stage can be decided", () => {
      const message = confirmDialogMessage(
        "confirm",
        doc,
        { ...base, deadEnd: null },
        t,
      );

      expect(message).toMatch(/approval queue/i);
      expect(message).not.toMatch(/nobody could decide/i);
    });
  });
});

describe("DocumentDetailPage.confirmDialogTitle", () => {
  it("asks 'Post this document?' only where the press posts", () => {
    expect(confirmDialogTitle("postNow", t)).toBe("Post this document?");
  });

  it("asks to send for approval where the press only sends it to the queue", () => {
    // The button read "Send for approval" and the dialog it opened asked
    // "Post this document?" with a "Post" button.
    expect(confirmDialogTitle("postNow", t, true)).toBe(
      "Send this document for approval?",
    );
  });
});
