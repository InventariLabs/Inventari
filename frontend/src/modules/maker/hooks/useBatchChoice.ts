import { useEffect, useState } from "react";
import type { IngredientBatchQuery } from "@/modules/maker/api/batches";
import { useIngredientBatches } from "@/modules/maker/hooks/useBatches";
import {
  lotChoicesPayload,
  shortChoices,
  type BatchChoices,
} from "@/modules/maker/lib/batchChoice";

/**
 * The batches a run's ingredients come from: the plan the server makes, the
 * batches the person picked instead, and what the run is told to take.
 *
 * A change of the run itself (product, quantity, place) asks a new plan and
 * forgets the picks, which were made against the old one.
 */
export function useBatchChoice(query: IngredientBatchQuery | null) {
  const plansQuery = useIngredientBatches(query);
  const [choices, setChoices] = useState<BatchChoices>({});
  const queryKey = query ? JSON.stringify(query) : "";
  useEffect(() => {
    setChoices({});
  }, [queryKey]);

  const plans = query ? (plansQuery.data?.ingredients ?? []) : [];

  function choose(templateId: string, lotId: string) {
    setChoices((current) => {
      const next = { ...current };
      if (lotId) next[templateId] = lotId;
      else delete next[templateId];
      return next;
    });
  }

  return {
    plans,
    choices,
    choose,
    /** Ingredients whose chosen batch cannot give what the run needs. */
    short: shortChoices(plans, choices),
    payload: lotChoicesPayload(plans, choices),
    isError: plansQuery.isError,
    error: plansQuery.error,
    refetch: plansQuery.refetch,
  };
}

export type BatchChoice = ReturnType<typeof useBatchChoice>;
