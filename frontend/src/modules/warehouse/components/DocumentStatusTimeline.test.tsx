import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { DocumentStatusTimeline } from "./DocumentStatusTimeline";
import type { DocumentStatus } from "@/modules/warehouse/types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

function doc(status: DocumentStatus, extra: Record<string, unknown> = {}) {
  return {
    status,
    createdAt: "2026-09-26T14:47:00Z",
    confirmedAt: "2026-09-26T16:50:00Z",
    completedAt: null as string | null,
    cancelledAt: null as string | null,
    ...extra,
  };
}

function trace(
  status: string,
  decided: { status: string; decided_at: string | null }[] = [],
  createdAt = "2026-09-26T16:50:05Z",
) {
  return {
    request_id: "req-1",
    status,
    current_stage: 1,
    total_stages: 1,
    created_at: createdAt,
    decisions: decided,
  };
}

const rungs = () =>
  screen.getAllByRole("listitem").map((li) => li.textContent ?? "");
const currentRung = () => {
  const current = document.querySelector('li[aria-current="step"]');
  if (!current) throw new Error("no current rung on the ladder");
  return current.textContent ?? "";
};

// The ladder was built from the current status with
// ['DRAFT', 'CONFIRMED', 'COMPLETED'] hardcoded — a document waiting for
// its approval showed a dated "Confirmed" rung and nothing current, and
// once approved, the rung kept the submission date instead of the
// decision's. A ladder is a history: the rungs come from what the
// document went through (the approval trace), not from where it stands.
describe("DocumentStatusTimeline — the ladder keeps the rungs it climbed", () => {
  it("marks the approval rung current while the document waits (not Confirmed)", () => {
    render(
      <DocumentStatusTimeline
        {...doc("PENDING_APPROVAL")}
        approval={trace("PENDING")}
        formatDate={(d) => d ?? "—"}
      />,
    );
    expect(currentRung()).toContain("status.PENDING_APPROVAL");
    expect(currentRung()).not.toContain("status.CONFIRMED");
  });

  it("keeps the approval rung after the decision, with the decision date", () => {
    render(
      <DocumentStatusTimeline
        {...doc("CONFIRMED", { confirmedAt: "2026-09-26T16:50:00Z" })}
        approval={trace("APPROVED", [
          { status: "APPROVED", decided_at: "2026-09-26T17:51:38Z" },
        ])}
        formatDate={(d) => d ?? "—"}
      />,
    );
    const approvalRung = rungs().find((l) =>
      l.includes("status.PENDING_APPROVAL"),
    );
    expect(approvalRung).toBeDefined();
    // The decision's time, not the submission's: 16:50 asked, 17:51:38
    // decided — the rung that says "approved" is dated by the answer.
    expect(approvalRung).toContain("2026-09-26T17:51:38Z");
    expect(approvalRung).not.toContain("16:50");
  });

  it("keeps the rung with the decision date on a completed document", () => {
    // History, not the current status: the document moved on to COMPLETED,
    // and the approval it passed through stays on the ladder.
    render(
      <DocumentStatusTimeline
        {...doc("COMPLETED", { completedAt: "2026-09-27T09:00:00Z" })}
        approval={trace("APPROVED", [
          { status: "APPROVED", decided_at: "2026-09-26T17:51:38Z" },
        ])}
        formatDate={(d) => d ?? "—"}
      />,
    );
    const approvalRung = rungs().find((l) =>
      l.includes("status.PENDING_APPROVAL"),
    );
    expect(approvalRung).toBeDefined();
    expect(approvalRung).toContain("2026-09-26T17:51:38Z");
  });

  it("leaves the rung off a document that never asked for approval", () => {
    render(
      <DocumentStatusTimeline
        {...doc("CONFIRMED")}
        approval={null}
        formatDate={(d) => d ?? "—"}
      />,
    );
    expect(rungs().some((l) => l.includes("status.PENDING_APPROVAL"))).toBe(
      false,
    );
  });

  it("dates the cancelled rung and keeps the approval it passed", () => {
    render(
      <DocumentStatusTimeline
        {...doc("CANCELLED", { cancelledAt: "2026-09-28T14:53:47Z" })}
        approval={trace("APPROVED", [
          { status: "APPROVED", decided_at: "2026-09-26T17:51:38Z" },
        ])}
        formatDate={(d) => d ?? "—"}
      />,
    );
    const labels = rungs();
    expect(labels.some((l) => l.includes("status.PENDING_APPROVAL"))).toBe(
      true,
    );
    const cancelledRung = labels.find((l) => l.includes("status.CANCELLED"));
    expect(cancelledRung).toContain("2026-09-28T14:53:47Z");
  });

  it("dates no rung the document has not reached (pending, rejected)", () => {
    const { unmount } = render(
      <DocumentStatusTimeline
        {...doc("PENDING_APPROVAL")}
        approval={trace("PENDING")}
        formatDate={(d) => d ?? "—"}
      />,
    );
    const confirmed = rungs().find((l) => l.includes("status.CONFIRMED"));
    expect(confirmed).not.toContain("2026-09-26T16:50:00Z");
    unmount();

    render(
      <DocumentStatusTimeline
        {...doc("DRAFT", { confirmedAt: "2026-09-26T16:50:00Z" })}
        approval={trace("REJECTED")}
        formatDate={(d) => d ?? "—"}
      />,
    );
    const upcoming = rungs().filter(
      (l) =>
        l.includes("status.PENDING_APPROVAL") || l.includes("status.CONFIRMED"),
    );
    expect(upcoming).toHaveLength(2);
    for (const rung of upcoming) expect(rung).not.toMatch(/2026-09-26T16:5/);
  });
});
