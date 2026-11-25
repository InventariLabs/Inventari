import type { ProductionOrder } from "@/modules/maker/types/maker";

/**
 * The day a list shows under a run, and what that day means.
 *
 * A planner reads a draft's day as the day it is planned for, a run under way
 * as the day it was started, a finished or reversed one as the day it was
 * made, a cancelled one as the day it was planned or started. A run without a
 * day of its own (a draft nobody dated) falls back to the day it was created.
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
  if (order.status === "COMPLETED" || order.status === "REVERSED") {
    return {
      day: order.production_date ?? order.completed_at ?? order.created_at,
      kind: "plain",
    };
  }
  if (order.status === "CANCELLED") {
    return {
      day: order.production_date ?? order.started_on ?? order.created_at,
      kind: "plain",
    };
  }
  return { day: order.created_at, kind: "plain" };
}
