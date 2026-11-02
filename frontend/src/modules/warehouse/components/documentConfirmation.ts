/**
 * Who confirmed a document, and who approved it — whatever the record holds.
 *
 * The confirmation stamp is written when the document is confirmed and it
 * survives the approval: the hand that confirmed the document and the hand
 * that approved it are two different facts, and the card names both. Rows
 * written while the approval overwrote the confirmation are enriched by the
 * detail API from the original confirmation event in the audit journal.
 */
export interface DocumentApprovalDecision {
  status: string;
  decided_at?: string | null;
  decided_by?: string | null;
  decided_by_name?: string | null;
}

export interface DocumentApprovalTrace {
  status?: string | null;
  created_at?: string | null;
  decisions?: DocumentApprovalDecision[];
}

export interface DocumentConfirmation {
  at: string | null;
  by: string | null;
  byName: string | null;
}

/**
 * When the approval let the document through: the last approving
 * decision, failing that when the request was raised.
 */
export function approvalDate(approval: DocumentApprovalTrace): string | null {
  return (
    lastApprovingDecision(approval)?.decided_at ?? approval.created_at ?? null
  );
}

/**
 * The decision that let the document through, when one did.
 *
 * A stage decides, not the request: a fully approved request carries one
 * approving decision per stage, and the last of them is the hand that
 * closed it.
 */
function lastApprovingDecision(
  approval: DocumentApprovalTrace,
): DocumentApprovalDecision | null {
  const approved = (approval.decisions ?? [])
    .filter((d) => d.status === "APPROVED" && d.decided_at)
    .sort((a, b) =>
      (a.decided_at as string) < (b.decided_at as string) ? -1 : 1,
    );
  return approved[approved.length - 1] ?? null;
}

export function documentConfirmation(doc: {
  status: string;
  confirmed_at?: string | null;
  confirmed_by?: string | null;
  confirmed_by_name?: string | null;
  approval?: DocumentApprovalTrace | null;
}): DocumentConfirmation | null {
  // Not confirmed yet: a document waiting for its approval has the stamp of
  // the submission that sent it there, and a draft carries a leftover. The
  // card reads the confirmation only once it means "confirmed".
  if (doc.status === "DRAFT" || doc.status === "PENDING_APPROVAL") return null;

  const stamp: DocumentConfirmation = {
    at: doc.confirmed_at ?? null,
    by: doc.confirmed_by ?? null,
    byName: doc.confirmed_by_name ?? null,
  };
  if (!stamp.at && !stamp.by) return null;

  const approval = doc.approval;
  if (approval?.status === "APPROVED") {
    const decidedAt = approvalDate(approval);
    if (decidedAt && stamp.at) {
      if (stamp.at < decidedAt) {
        // The confirmation that sent the document into approval: its author
        // confirmed it, and the moment is when it became confirmed — the
        // approval letting it through.
        return { at: decidedAt, by: stamp.by, byName: stamp.byName };
      }
    }
  }
  return stamp;
}

/** When the card may say the document was confirmed, if it may. */
export function documentConfirmedAt(
  doc: Parameters<typeof documentConfirmation>[0],
): string | null {
  return documentConfirmation(doc)?.at ?? null;
}

/**
 * The hand the approval was decided by: the last approving decision of a
 * request that ended approved, or nothing while it is undecided or ended
 * another way.
 */
export function documentApprover(doc: {
  approval?: DocumentApprovalTrace | null;
}): DocumentConfirmation | null {
  const approval = doc.approval;
  if (approval?.status !== "APPROVED") return null;
  const decided = lastApprovingDecision(approval);
  if (!decided) return null;
  return {
    at: decided.decided_at ?? null,
    by: decided.decided_by ?? null,
    byName: decided.decided_by_name ?? null,
  };
}
