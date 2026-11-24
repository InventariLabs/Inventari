import type { ProductionOrder } from "@/modules/maker/types/maker";

/**
 * The day a list shows under a run, and what that day means.
 *
 * A planner reads a draft's day as the day it is planned for, a run under way
 * as the day it was started, a finished one as the day it was made. A run
 * without a day of its own (a draft nobody dated, a cancelled run) falls back
 * to the day it was created, which is how the list read before.
 */
export type RunDay = {
  day: string;
  kind: "planned" | "started" | "plain";
};

export function runDay(order: ProductionOrder): RunDay {
  if (order.status === "DRAFT" && order.production_date) {
    return { day: order.production_date, kind: "planned" };
  }
  if (order.status === "IN_PROGRESS" && order.started_on) {
    return { day: order.started_on, kind: "started" };
  }
  if (order.status === "COMPLETED") {
    return {
      day: order.production_date ?? order.completed_at ?? order.created_at,
      kind: "plain",
    };
  }
  return { day: order.created_at, kind: "plain" };
}
