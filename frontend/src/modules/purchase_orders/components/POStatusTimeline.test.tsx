import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { POStatusTimeline } from "./POStatusTimeline";
import type { ApprovalRequest } from "@/modules/approvals/api/approvals";
import type { PurchaseOrder, POStatus } from "../types/purchase-orders";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

function order(status: POStatus, extra: Partial<PurchaseOrder> = {}) {
  return {
    id: "po-1",
    organization_id: "org-1",
    number: "PO/2026/017",
    status,
    partner_id: null,
    scheduled_date: null,
    notes: null,
    currency: "PLN",
    created_by: "u-1",
    confirmed_by: null,
    confirmed_at: null,
    cancelled_by: null,
    cancelled_at: null,
    created_at: "2026-08-01T09:00:00Z",
    updated_at: "2026-08-01T09:00:00Z",
    lines: [],
    ...extra,
  } as PurchaseOrder;
}

function request(
  status: ApprovalRequest["status"],
  decidedAt: string | null = null,
) {
  return {
    id: "req-1",
    organization_id: "org-1",
    workflow_id: "wf-1",
    target_type: "purchase_order",
    target_id: "po-1",
    status,
    current_stage: 1,
    total_stages: 1,
    created_by: "u-1",
    created_by_name: "Requester",
    meta_data: null,
    workflow_stages: null,
    decisions: decidedAt
      ? [
          {
            id: "d-1",
            stage_order: 1,
            approver_id: "u-2",
            approver_name: "Approver",
            status: "APPROVED",
            notes: null,
            decided_at: decidedAt,
            created_at: "2026-08-02T08:00:00Z",
          },
        ]
      : [],
    created_at: "2026-08-02T08:00:00Z",
  } as ApprovalRequest;
}

const rungs = () =>
  screen.getAllByRole("listitem").map((li) => li.textContent ?? "");

// A ladder is a history. Built from the current status, this one grew an
// approval rung while the order waited and dropped it the moment the
// decision landed — so the one card that could show an order had been
// approved stopped showing it exactly when that became a fact about the past.
describe("POStatusTimeline — the ladder keeps the rungs it climbed", () => {
  it("keeps the approval rung after the decision, with its date", () => {
    render(
      <POStatusTimeline
        po={order("CONFIRMED", { confirmed_at: "2026-08-02T10:00:00Z" })}
        approval={request("APPROVED", "2026-08-02T09:30:00Z")}
        formatDate={(d) => d ?? "—"}
      />,
    );
    const labels = rungs();
    expect(labels.some((l) => l.includes("status.PENDING_APPROVAL"))).toBe(
      true,
    );
    expect(labels.find((l) => l.includes("status.PENDING_APPROVAL"))).toContain(
      "2026-08-02T09:30:00Z",
    );
  });

  it("shows the rung while the order is still waiting", () => {
    render(
      <POStatusTimeline
        po={order("PENDING_APPROVAL")}
        approval={request("PENDING")}
        formatDate={(d) => d ?? "—"}
      />,
    );
    expect(rungs().some((l) => l.includes("status.PENDING_APPROVAL"))).toBe(
      true,
    );
  });

  it("leaves the rung off an order that never asked for approval", () => {
    render(
      <POStatusTimeline
        po={order("CONFIRMED", { confirmed_at: "2026-08-02T10:00:00Z" })}
        approval={null}
        formatDate={(d) => d ?? "—"}
      />,
    );
    expect(rungs().some((l) => l.includes("status.PENDING_APPROVAL"))).toBe(
      false,
    );
  });

  it("leaves the rung off an order whose request was withdrawn", () => {
    // A cancelled request is one the order never passed through.
    render(
      <POStatusTimeline
        po={order("CONFIRMED", { confirmed_at: "2026-08-02T10:00:00Z" })}
        approval={request("CANCELLED")}
        formatDate={(d) => d ?? "—"}
      />,
    );
    expect(rungs().some((l) => l.includes("status.PENDING_APPROVAL"))).toBe(
      false,
    );
  });

  it("keeps the rung on an order cancelled after it was approved", () => {
    render(
      <POStatusTimeline
        po={order("CANCELLED", { cancelled_at: "2026-08-03T10:00:00Z" })}
        approval={request("APPROVED", "2026-08-02T09:30:00Z")}
        formatDate={(d) => d ?? "—"}
      />,
    );
    const labels = rungs();
    expect(labels.some((l) => l.includes("status.PENDING_APPROVAL"))).toBe(
      true,
    );
    expect(labels.some((l) => l.includes("status.CANCELLED"))).toBe(true);
  });
});
