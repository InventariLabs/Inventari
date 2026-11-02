import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { extractApiError } from "@/lib/errors";
import { invalidation } from "@/lib/api/invalidation";
import { recipesApi } from "../api/recipes";
import type { PickingItem, PickingScanResponse } from "../types/core";

/**
 * The dinner is cooked; the question is whether the shelf learns about it.
 *
 * This walks the SAME road "Take from stock" walks — start a picking session
 * for these servings, tick every ingredient the checklist can name off its
 * own recommended item (the tap path, so the server's unit bridge and its
 * refusals decide, never a local guess), then complete the session. Nothing
 * is marked taken that the server did not take: a refused row comes back as
 * an outcome the screen spells out, in the words the picking sheet uses.
 */

/** Why a row came back untaken — a code the screen renders, not a sentence. */
export type NotTakenReason =
  | "nothing_on_shelf"
  | "unit_mismatch"
  | "not_in_recipe"
  | "already_picked"
  | "refused";

export interface NotTakenRow {
  name: string;
  reason: NotTakenReason;
  /** The two readings behind a unit_mismatch, restated for the row. */
  detail?: {
    required: string;
    requiredUom: string | null;
    available: string;
    availableUom: string | null;
  };
}

export interface DeductionOutcome {
  sessionId: string;
  taken: number;
  notTaken: NotTakenRow[];
}

export type DeductionResult =
  /** Every row answered, the session is complete, the run owns the shelf. */
  | { kind: "done"; outcome: DeductionOutcome }
  /** An unfinished session for this recipe already exists — the sheet owns
   * it. Starting under it would deduct someone else's half-read checklist,
   * so nothing is touched here. */
  | { kind: "blocked" }
  /** The road broke mid-walk. What already left the shelf stays taken on the
   * server; the screen says how far it got and offers the rest again. */
  | {
      kind: "failed";
      message: string;
      sessionId: string | null;
      taken: number;
      total: number;
    };

function notTakenFromScan(
  row: PickingItem,
  result: PickingScanResponse,
): NotTakenRow {
  if (result.status === "unit_mismatch" && result.unit_mismatch) {
    return {
      name: row.name,
      reason: "unit_mismatch",
      detail: {
        required: String(result.unit_mismatch.required_quantity),
        requiredUom: result.unit_mismatch.required_uom,
        available: String(result.unit_mismatch.available_quantity),
        availableUom: result.unit_mismatch.available_uom,
      },
    };
  }
  if (
    result.status === "not_in_recipe" ||
    result.status === "already_picked" ||
    result.status === "unit_mismatch"
  ) {
    return { name: row.name, reason: result.status };
  }
  return { name: row.name, reason: "refused" };
}

export function useStockDeduction(recipeId: string) {
  const queryClient = useQueryClient();
  const [running, setRunning] = useState(false);

  /** The walk writes the shelves through the picking API, and the views
   *  that show them sit under a five-minute staleTime with no refetch on
   *  focus — without this an item list opened before the meal kept the
   *  stock from before it. */
  const invalidateStock = useCallback(() => {
    invalidation.picking(queryClient, recipeId);
  }, [queryClient, recipeId]);

  const deduct = useCallback(
    async (
      servings: number,
      failureFallback: string,
    ): Promise<DeductionResult> => {
      setRunning(true);
      let taken = 0;
      let total = 0;
      let sessionId: string | null = null;
      try {
        const session = await recipesApi.startPicking(recipeId, servings);
        // A handed-back session was opened for its own servings; if those are
        // not ours it is an older checklist, and finishing it from here would
        // deduct a meal somebody else is still picking. Our own retry (after
        // a mid-run failure) carries the same number, so it walks on.
        if (session.resumed && session.servings !== servings) {
          return { kind: "blocked" };
        }
        sessionId = session.picking_session_id;
        const rows = session.items_to_pick;
        total = rows.filter((r) => r.status !== "skipped").length;
        const notTaken: NotTakenRow[] = [];
        for (const row of rows) {
          if (row.status === "skipped") continue;
          if (row.status === "picked") {
            // A retry meets the rows the previous pass already took.
            taken += 1;
            continue;
          }
          if (row.status !== "pending" || !row.recommended_item_id) {
            // "missing" knows the product and finds an empty shelf; "unknown"
            // names nothing at all. Either way there is nothing to hand over.
            notTaken.push({ name: row.name, reason: "nothing_on_shelf" });
            continue;
          }
          const result = await recipesApi.scanPicking(
            recipeId,
            session.picking_session_id,
            { item_id: row.recommended_item_id },
          );
          if (result.status === "picked") {
            taken += 1;
          } else {
            notTaken.push(notTakenFromScan(row, result));
          }
        }
        await recipesApi.completePicking(recipeId, session.picking_session_id);
        invalidateStock();
        return {
          kind: "done",
          outcome: {
            sessionId: session.picking_session_id,
            taken,
            notTaken,
          },
        };
      } catch (e: unknown) {
        // What already left the shelf stays taken on the server, so the
        // views behind the screen have to say so too.
        if (taken > 0) invalidateStock();
        return {
          kind: "failed",
          message: extractApiError(e, failureFallback),
          sessionId,
          taken,
          total,
        };
      } finally {
        setRunning(false);
      }
    },
    [recipeId, invalidateStock],
  );

  return { running, deduct };
}
