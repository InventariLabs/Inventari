import { useMemo } from "react";
import { useDebounce } from "@/module-sdk";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import {
  putawayApi,
  type PutawayPreviewLine,
  type PutawayPreviewLineInput,
} from "@/modules/warehouse/api/putaway";
import type { ReceiveDraftLine } from "@/modules/warehouse/components/receive/receiveDraft";

/** How long the sheet rests before the planner is asked about it. */
const PREVIEW_DEBOUNCE_MS = 350;

interface PlanRequestEntry {
  key: string;
  input: PutawayPreviewLineInput;
}

/**
 * Where the lines on the receive sheet will land, as the reader fills it in.
 *
 * The planner runs on the server — the same decision the posting will run —
 * and this hook only decides *when* to ask. Rows without a catalogue product
 * or without a count are left out: they are not a delivery yet, and asking
 * about them would produce a shelf for an empty line. The debounce is what
 * keeps typing a quantity from being one request per keystroke.
 */
export function useReceiptPlan(
  lines: ReceiveDraftLine[],
  targetLocationId: string | null,
) {
  const request = useMemo(() => {
    const entries: PlanRequestEntry[] = [];
    for (const line of lines) {
      const quantity = Number(line.quantity);
      if (!Number.isFinite(quantity) || quantity <= 0) continue;
      if (!line.productTemplateId && !line.itemId) continue;
      entries.push({
        key: line.key,
        input: {
          item_id: line.itemId,
          product_template_id: line.productTemplateId,
          quantity: line.quantity,
          uom_id: line.uomId,
          target_location_id: line.targetLocationId,
        },
      });
    }
    return { entries, inputs: entries.map((entry) => entry.input) };
  }, [lines]);

  const settled = useDebounce(request, PREVIEW_DEBOUNCE_MS);

  const query = useModuleQuery<PutawayPreviewLine[]>("warehouse", {
    queryKey: queryKeys.documents.putawayPreview(
      targetLocationId,
      JSON.stringify(settled.inputs),
    ),
    queryFn: () =>
      putawayApi.previewReceiptPlan(targetLocationId!, settled.inputs),
    extraEnabled: Boolean(targetLocationId) && settled.inputs.length > 0,
    // A plan that failed is a sentence under the table, not a page error;
    // retrying on every focus would hide the failure behind churn.
    retry: false,
    staleTime: 10_000,
  });

  const plansByKey = useMemo(() => {
    const plans = new Map<string, PutawayPreviewLine>();
    (query.data ?? []).forEach((plan, index) => {
      const entry = settled.entries[index];
      if (entry) plans.set(entry.key, plan);
    });
    return plans;
  }, [query.data, settled.entries]);

  return {
    plansByKey,
    /** A plan is being recomputed; the previous one is still on screen. */
    isFetching: query.isFetching,
    error: query.error,
  };
}
