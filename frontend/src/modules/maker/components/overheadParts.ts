import type { CostBreakdownResponse } from "@/modules/maker/types/maker";

export interface OverheadPart {
  kind: "fixed" | "labour";
  cost: string;
  /** Share of `total_cost`, the way each ingredient's own share is. */
  percentage: string | null;
}

/**
 * The parts of `total_cost` that are not ingredients — fixed costs and labour,
 * each only when the formula has it. Listed beside the ingredients they make
 * the parts add up to the total the reader is shown.
 */
export function overheadParts(
  breakdown: CostBreakdownResponse,
): OverheadPart[] {
  const total = Number(breakdown.total_cost);
  const parts: [OverheadPart["kind"], string][] = [
    ["fixed", breakdown.fixed_cost],
    ["labour", breakdown.labour_cost],
  ];
  return parts
    .filter(([, cost]) => Number(cost) > 0)
    .map(([kind, cost]) => ({
      kind,
      cost,
      percentage: total > 0 ? ((Number(cost) / total) * 100).toFixed(2) : null,
    }));
}
