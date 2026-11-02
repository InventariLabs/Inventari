import { describe, expect, it } from "vitest";
import i18n from "@/i18n/config";
import type { WorkItem } from "@/modules/warehouse/types";
import { actionLabel, workItemSentence, workItemTarget } from "./workItemText";

const t = i18n.getFixedT("en", "warehouse");

function task(overrides: Partial<WorkItem>): WorkItem {
  return {
    key: "k",
    kind: "ship",
    state: "todo",
    source_kind: "document",
    source_id: "id-1",
    overdue: false,
    shelf_scan_required: false,
    ...overrides,
  };
}

describe("a task's sentence", () => {
  it("says how long ago a due location was last counted", () => {
    const due = task({
      kind: "count",
      source_kind: "location",
      subject: "Pantry / Shelf A",
    });
    expect(workItemSentence(t, { ...due, count: "62" })).toBe(
      "Count Pantry / Shelf A — last counted 62 days ago",
    );
    expect(workItemSentence(t, { ...due, count: "1" })).toBe(
      "Count Pantry / Shelf A — last counted 1 day ago",
    );
    expect(workItemSentence(t, { ...due, count: null })).toBe(
      "Count Pantry / Shelf A — never counted",
    );
    // A schedule's count keeps its own words.
    expect(
      workItemSentence(
        t,
        task({ kind: "count", source_kind: "cycle_count", subject: "Fast" }),
      ),
    ).toBe("Count: Fast");
  });

  it("names the document when there is no partner to name", () => {
    expect(
      workItemSentence(
        t,
        task({ kind: "receive", number: "PZ/1", count: "1" }),
      ),
    ).toBe("Receive goods on PZ/1 — 1 line");
    expect(workItemSentence(t, task({ number: "WZ/2", count: "3" }))).toBe(
      "Issue goods on WZ/2 — 3 lines",
    );
  });

  it("calls a transfer a move, whoever it is for", () => {
    expect(
      workItemSentence(
        t,
        task({ document_type: "INT", number: "MM/3", subject: "Ann" }),
      ),
    ).toBe("Move goods on MM/3");
  });

  it("says which order a backorder continues, when it is known", () => {
    expect(
      workItemSentence(
        t,
        task({ kind: "backorder", origin_number: "PZ/7", number: "DRAFT-1" }),
      ),
    ).toBe("Decide on the rest of PZ/7");
    expect(
      workItemSentence(t, task({ kind: "backorder", number: "DRAFT-1" })),
    ).toBe("Decide on the leftover DRAFT-1");
  });

  it("says how much reserve stock is on its way to a pick face", () => {
    const replenish = task({
      kind: "replenish",
      source_kind: "replenishment",
      next_action: "replenish",
      subject: "Jasmine Rice",
      count: "17",
      unit: "pcs",
      place: "Pick B-01",
    });
    expect(workItemSentence(t, replenish)).toBe(
      "Carry 17 pcs. Jasmine Rice from reserve to Pick B-01",
    );
    expect(actionLabel(t, replenish)).toBe("Replenish");
  });

  it("is a custom task's own title, with no count after it", () => {
    expect(
      workItemSentence(
        t,
        task({
          kind: "custom",
          source_kind: "custom",
          subject: "Move the rack",
          count: "9",
        }),
      ),
    ).toBe("Move the rack");
  });
});

describe("a task another module contributed", () => {
  const contributed = task({
    kind: "certificate_check",
    source_kind: "certificate_check",
    sentence: "Check the delivery certificate for ZK/7",
    action_label: "Open certificate",
    action_href: "/certificates/7",
  });

  it("is worded, labelled and linked by the module that added it", () => {
    expect(workItemSentence(t, contributed)).toBe(
      "Check the delivery certificate for ZK/7",
    );
    expect(actionLabel(t, contributed)).toBe("Open certificate");
    expect(workItemTarget(contributed)).toBe("/certificates/7");
  });

  it("has no button when the module named no action", () => {
    expect(
      actionLabel(t, task({ kind: "certificate_check", sentence: "Check it" })),
    ).toBeNull();
  });
});

describe("where a task's button leads", () => {
  it("opens an order, a run or the count under way, not a document", () => {
    expect(
      workItemTarget(
        task({
          source_kind: "purchase_order",
          next_action: "receive_delivery",
        }),
      ),
    ).toBe("/warehouse/receive?order=id-1");
    expect(
      workItemTarget(
        task({ source_kind: "production_order", next_action: "produce" }),
      ),
    ).toBe("/maker/production/id-1");
    expect(
      workItemTarget(
        task({
          source_kind: "cycle_count",
          next_action: "count",
          action_href: "/inventory/stock-takes/take-1/counting",
        }),
      ),
    ).toBe("/inventory/stock-takes/take-1/counting");
  });

  it("sends a document that waits for an approval to its own page", () => {
    const blocked = task({
      kind: "ship",
      document_type: "OUT",
      next_action: "request_approval",
    });
    expect(actionLabel(t, blocked)).toBe("Request approval");
    expect(workItemTarget(blocked)).toBe("/warehouse/documents/id-1");
    expect(
      workItemTarget(
        task({ document_type: "IN", next_action: "request_approval" }),
      ),
    ).toBe("/warehouse/documents/id-1");
  });

  it("resumes a receipt as receiving and a dispatch as picking", () => {
    expect(
      workItemTarget(task({ document_type: "IN", next_action: "resume" })),
    ).toBe("/warehouse/documents/id-1#receive");
    expect(
      workItemTarget(task({ document_type: "OUT", next_action: "resume" })),
    ).toBe("/warehouse/documents/id-1#pick");
  });
});
