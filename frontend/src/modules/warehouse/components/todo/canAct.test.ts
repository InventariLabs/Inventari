import { describe, expect, it } from "vitest";
import type { WorkItem } from "@/modules/warehouse/types";
import { canAct, type ModuleWrites } from "./WorkItemRow";

const none: ModuleWrites = {
  purchaseOrders: false,
  maker: false,
  stockTakes: false,
};

const task = (over: Partial<WorkItem>): WorkItem =>
  ({
    key: "k",
    kind: "receive",
    state: "todo",
    source_kind: "purchase_order",
    source_id: "po-1",
    next_action: "receive_delivery",
    ...over,
  }) as WorkItem;

describe("canAct", () => {
  it("offers a reader no button that leads to a screen it may not use", () => {
    expect(canAct(task({}), false, none)).toBe(false);
    expect(
      canAct(
        task({ source_kind: "production_order", next_action: "produce" }),
        false,
        none,
      ),
    ).toBe(false);
    expect(
      canAct(
        task({
          source_kind: "cycle_count",
          kind: "count",
          next_action: "count",
          action_href: "/inventory/stock-takes/count",
        }),
        false,
        none,
      ),
    ).toBe(false);
  });

  it("offers each button to the account that holds the grant its screen needs", () => {
    expect(canAct(task({}), true, none)).toBe(true);
    expect(
      canAct(
        task({ source_kind: "production_order", next_action: "produce" }),
        false,
        { ...none, maker: true },
      ),
    ).toBe(true);
    expect(
      canAct(
        task({
          source_kind: "cycle_count",
          kind: "count",
          next_action: "count",
        }),
        false,
        { ...none, stockTakes: true },
      ),
    ).toBe(true);
  });

  it("keeps a document's review open to whoever the queue named", () => {
    expect(
      canAct(
        task({ source_kind: "document", next_action: "review_approval" }),
        false,
        none,
      ),
    ).toBe(true);
  });
});
