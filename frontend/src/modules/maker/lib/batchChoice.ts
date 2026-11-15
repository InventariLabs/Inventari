import type {
  IngredientBatchPlan,
  IngredientLotChoice,
} from "@/modules/maker/types/maker";

/** Ingredient → the batch the person chose for all of its need. */
export type BatchChoices = Record<string, string>;

const PLACES = 4;

function same(a: number, b: number): boolean {
  return a.toFixed(PLACES) === b.toFixed(PLACES);
}

/**
 * What the run is told to take, ingredient by ingredient.
 *
 * A chosen batch gives the ingredient's whole need. An ingredient nobody
 * chose for is sent as the plan the page showed when every part of that plan
 * names a batch and covers the need — so the run takes exactly what the
 * person saw, or is refused when the shelves moved since. A plan with stock
 * kept outside any batch is not sent: there is no batch to name, and the
 * removal order takes it as the page said.
 */
export function lotChoicesPayload(
  plans: IngredientBatchPlan[],
  choices: BatchChoices,
): IngredientLotChoice[] {
  return plans.flatMap((plan): IngredientLotChoice[] => {
    const chosen = choices[plan.template_id];
    if (chosen) {
      return [
        {
          template_id: plan.template_id,
          lot_id: chosen,
          quantity: String(plan.needed),
        },
      ];
    }
    const parts = plan.plan ?? [];
    const total = parts.reduce((sum, part) => sum + Number(part.quantity), 0);
    if (
      parts.length === 0 ||
      parts.some((part) => !part.lot_id) ||
      !same(total, Number(plan.needed))
    )
      return [];
    return parts.map((part) => ({
      template_id: plan.template_id,
      lot_id: part.lot_id as string,
      quantity: String(part.quantity),
    }));
  });
}

/** The ingredient whose batch a scanned code names, and the batch. */
export function findScannedBatch(
  plans: IngredientBatchPlan[],
  code: string,
): { templateId: string; lotId: string } | null {
  const wanted = code.trim().toLowerCase();
  if (!wanted) return null;
  for (const plan of plans) {
    const batch = (plan.batches ?? []).find(
      (option) => option.lot_name.toLowerCase() === wanted,
    );
    if (batch) return { templateId: plan.template_id, lotId: batch.lot_id };
  }
  return null;
}

/** Ingredients whose chosen batch has less free than the run needs. */
export function shortChoices(
  plans: IngredientBatchPlan[],
  choices: BatchChoices,
): Set<string> {
  const short = new Set<string>();
  for (const plan of plans) {
    const chosen = choices[plan.template_id];
    const batch = (plan.batches ?? []).find(
      (option) => option.lot_id === chosen,
    );
    if (batch && Number(batch.available) < Number(plan.needed))
      short.add(plan.template_id);
  }
  return short;
}
