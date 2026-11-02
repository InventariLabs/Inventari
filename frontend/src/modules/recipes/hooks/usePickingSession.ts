import { useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import i18n from "i18next";
import { extractApiError } from "@/lib/errors";
import { invalidation } from "@/lib/api/invalidation";
import { recipesApi } from "@/modules/recipes/api/recipes";
import type {
  PickingStartResponse,
  PickingScanResponse,
  PickingItem,
} from "@/modules/recipes/types/core";

/**
 * What a failed call says when the server sends no sentence of its own — a
 * 5xx, whose detail is for the logs. In the reader's language: the hook's
 * English literals used to reach a Polish reader's banner as they were.
 */
const fallback = {
  start: () => i18n.t("recipes:picking.errors.start"),
  complete: () => i18n.t("recipes:picking.errors.complete"),
  cancel: () => i18n.t("recipes:picking.errors.cancel"),
  scan: () => i18n.t("recipes:picking.errors.scan"),
  undo: () => i18n.t("recipes:picking.errors.undo"),
  refresh: () => i18n.t("recipes:picking.errors.refresh"),
};

type PickingState =
  | { phase: "idle" }
  | { phase: "active"; session: PickingStartResponse; items: PickingItem[] }
  | {
      phase: "disambiguation";
      session: PickingStartResponse;
      items: PickingItem[];
      scanResult: PickingScanResponse;
    }
  | {
      phase: "fefo_mismatch";
      session: PickingStartResponse;
      items: PickingItem[];
      scanResult: PickingScanResponse;
    }
  | {
      phase: "opened_suggestion";
      session: PickingStartResponse;
      items: PickingItem[];
      scanResult: PickingScanResponse;
    }
  | { phase: "complete" }
  | { phase: "cancelled" };

/** Scan outcomes that took nothing off the shelf. */
const REFUSALS = ["unit_mismatch", "not_in_recipe", "already_picked"] as const;

export type PickingRefusal = (typeof REFUSALS)[number];

function refusalOf(status: string): PickingRefusal | null {
  return REFUSALS.includes(status as PickingRefusal)
    ? (status as PickingRefusal)
    : null;
}

function pickedIn(
  items: PickingItem[],
  ingredientId: string | null | undefined,
) {
  return items.map((item) =>
    item.ingredient_id === ingredientId
      ? { ...item, status: "picked" as const }
      : item,
  );
}

/** Where the sheet goes once the last ingredient is off the shelf: over if the
 * database closed the session, otherwise back to the checklist. */
function afterLastPick(
  closed: boolean,
  session: PickingStartResponse,
  items: PickingItem[],
): PickingState {
  return closed ? { phase: "complete" } : { phase: "active", session, items };
}

/**
 * The sealed pick of an opened-pack suggestion, put back: it was taken when
 * the suggestion came up, so using the opened pack means returning it first,
 * or the scan of the opened one is refused as an ingredient already picked.
 * Answers the rows with that ingredient pending again.
 */
async function putSealedPickBack(
  recipeId: string,
  session: PickingStartResponse,
  state: Extract<PickingState, { phase: "opened_suggestion" }>,
): Promise<PickingItem[]> {
  const ingredientId = state.scanResult.ingredient_id;
  if (ingredientId) {
    await recipesApi.undoPick(
      recipeId,
      session.picking_session_id,
      ingredientId,
    );
  }
  return state.items.map((item) =>
    item.ingredient_id === ingredientId
      ? { ...item, status: "pending" as const }
      : item,
  );
}

/** The session the sheet is holding, whatever phase it is shown in. */
function openSessionId(state: PickingState): string | null {
  if (
    state.phase === "idle" ||
    state.phase === "complete" ||
    state.phase === "cancelled"
  ) {
    return null;
  }
  return state.session.picking_session_id;
}

export function usePickingSession(recipeId: string, mealPlanEntryId?: string) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<PickingState>({ phase: "idle" });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // What the server refused to take, per ingredient. The toast that carries
  // the same news lasts a few seconds; the checklist is read for as long as
  // the cooking takes, so the row has to keep saying it.
  const [refusals, setRefusals] = useState<Record<string, PickingRefusal>>({});

  /** Every pick, undo, cancel and session close writes the shelves, and the
   *  views that show them — an items list, an item card, the movement
   *  ledger, the quants and lots, the recipe's availability — sat under a
   *  five-minute staleTime with no refetch on focus: they kept the shelf
   *  from before the scan for as long as the reader stayed on them. */
  const invalidateStock = useCallback(() => {
    invalidation.picking(queryClient, recipeId);
  }, [queryClient, recipeId]);

  const markPicked = (ingredientId: string | null | undefined) => {
    if (!ingredientId) return;
    setRefusals((current) => {
      if (!(ingredientId in current)) return current;
      const { [ingredientId]: _taken, ...rest } = current;
      return rest;
    });
  };

  const noteRefusal = (
    ingredientId: string | null | undefined,
    status: string,
  ) => {
    const refusal = refusalOf(status);
    if (!ingredientId || !refusal) return;
    setRefusals((current) => ({ ...current, [ingredientId]: refusal }));
  };

  const startSession = useCallback(
    async (servings: number): Promise<PickingStartResponse | null> => {
      setIsLoading(true);
      setError(null);
      try {
        const session = await recipesApi.startPicking(
          recipeId,
          servings,
          mealPlanEntryId,
        );
        setRefusals({});
        setState({ phase: "active", session, items: session.items_to_pick });
        // Handed back to the caller because a resumed session is not the one
        // the reader asked for: it carries its own servings and its own
        // half-finished checklist, and the sheet has to say so.
        return session;
      } catch (e: unknown) {
        setError(extractApiError(e, fallback.start()));
        return null;
      } finally {
        setIsLoading(false);
      }
    },
    [recipeId, mealPlanEntryId],
  );

  // Ending a session is the backend's business, and the sheet used to do it in
  // its own state alone: on the last ingredient it went straight to "complete"
  // and the card said "Completed ✓", while the session stayed `active` in the
  // database. Nothing could close it afterwards, and the next "Get
  // ingredients" put every ingredient back on the shelf. Whatever resolves the
  // last ingredient calls this first, and reports the session done only when
  // the database took it: a refusal leaves the session open on the sheet, with
  // the error above the checklist, so the reader can finish it again.
  const finishInDatabase = useCallback(
    async (sessionId: string): Promise<boolean> => {
      try {
        await recipesApi.completePicking(recipeId, sessionId);
        // The close is what writes the session into the recipe's cooking
        // history, so the views refresh after it, not on the scan before it:
        // a history panel refetched then still read "no sessions yet".
        invalidateStock();
        return true;
      } catch (e: unknown) {
        setError(extractApiError(e, fallback.complete()));
        return false;
      }
    },
    [recipeId, invalidateStock],
  );

  const scan = useCallback(
    async (data: {
      barcode?: string;
      item_id?: string;
      from_checklist?: boolean;
    }) => {
      if (state.phase !== "active") return;
      const { session, items } = state;
      setIsLoading(true);
      setError(null);
      try {
        const result = await recipesApi.scanPicking(
          recipeId,
          session.picking_session_id,
          data,
        );
        // Only a pick moved the shelf; a refusal, a disambiguation answer
        // and a FEFO mismatch left it where it was, and refreshing every
        // stock view over them would buy nothing.
        if (result.status === "picked") invalidateStock();

        if (result.status === "disambiguation_required") {
          setState({
            phase: "disambiguation",
            session,
            items,
            scanResult: result,
          });
        } else if (result.status === "fefo_mismatch") {
          setState({
            phase: "fefo_mismatch",
            session,
            items,
            scanResult: result,
          });
        } else if (result.status === "picked" && result.opened_suggestion) {
          // Mark item as picked in local state before showing opened suggestion
          setState({
            phase: "opened_suggestion",
            session,
            items: pickedIn(items, result.ingredient_id),
            scanResult: result,
          });
        } else if (result.status === "picked" && result.session_complete) {
          markPicked(result.ingredient_id);
          // The last ingredient is off the shelf either way; whether the
          // session is over depends on the database having closed it.
          const closed = await finishInDatabase(session.picking_session_id);
          setState(
            afterLastPick(
              closed,
              session,
              pickedIn(items, result.ingredient_id),
            ),
          );
        } else if (result.status === "picked") {
          markPicked(result.ingredient_id);
          setState({
            phase: "active",
            session,
            items: pickedIn(items, result.ingredient_id),
          });
        } else {
          // The request succeeded and the pick did not. The row used to be
          // ticked off here regardless of what the answer said, so a refused
          // scan read as done and the count went up for stock still on the
          // shelf.
          noteRefusal(result.ingredient_id, result.status);
          setState({ phase: "active", session, items });
        }
        return result;
      } catch (e: unknown) {
        setError(extractApiError(e, fallback.scan()));
      } finally {
        setIsLoading(false);
      }
    },
    [state, recipeId, finishInDatabase, invalidateStock],
  );

  const resolveDisambiguation = useCallback(
    async (itemId: string) => {
      // Only the three phases that show an overlay carry a scan result.
      if (!("scanResult" in state)) return;
      const { session } = state;
      let items = state.items;
      if (state.phase === "opened_suggestion") {
        try {
          items = await putSealedPickBack(recipeId, session, state);
        } catch (e: unknown) {
          setError(extractApiError(e, fallback.undo()));
          return;
        }
        invalidateStock();
      }
      setState({ phase: "active", session, items });
      const result = await recipesApi.scanPicking(
        recipeId,
        session.picking_session_id,
        { item_id: itemId },
      );
      if (result.status === "picked") invalidateStock();
      if (result.status === "picked" && result.session_complete) {
        markPicked(result.ingredient_id);
        const closed = await finishInDatabase(session.picking_session_id);
        setState(
          afterLastPick(closed, session, pickedIn(items, result.ingredient_id)),
        );
      } else if (result.status === "picked" && result.opened_suggestion) {
        markPicked(result.ingredient_id);
        setState({
          phase: "opened_suggestion",
          session,
          items: pickedIn(items, result.ingredient_id),
          scanResult: result,
        });
      } else if (result.status === "picked") {
        markPicked(result.ingredient_id);
        setState({
          phase: "active",
          session,
          items: pickedIn(items, result.ingredient_id),
        });
      } else {
        // Picking the candidate the reader chose can still be refused — the
        // unit bridge is checked after the item is known, not before.
        noteRefusal(result.ingredient_id, result.status);
        setState({ phase: "active", session, items });
      }
      return result;
    },
    [state, recipeId, finishInDatabase, invalidateStock],
  );

  const dismissOpenedSuggestion = useCallback(async () => {
    if (state.phase !== "opened_suggestion") return;
    const { session, items } = state;
    if (state.scanResult.session_complete) {
      // A refused close keeps the suggestion where it is; dismissing it again
      // is the retry.
      if (await finishInDatabase(session.picking_session_id)) {
        setState({ phase: "complete" });
      }
    } else {
      setState({ phase: "active", session, items });
    }
  }, [state, finishInDatabase]);

  const dismissFefoMismatch = useCallback(() => {
    if (state.phase !== "fefo_mismatch") return;
    const { session, items } = state;
    setState({ phase: "active", session, items });
  }, [state]);

  const undoPick = useCallback(
    async (ingredientId: string) => {
      const sessionId =
        state.phase === "active" ? state.session.picking_session_id : null;
      if (!sessionId) return;
      const { session, items } = state as Extract<
        typeof state,
        { phase: "active" }
      >;
      setIsLoading(true);
      try {
        const result = await recipesApi.undoPick(
          recipeId,
          sessionId,
          ingredientId,
        );
        // The stock went back on the shelf, so the views showing it move.
        invalidateStock();
        const updated = items.map((item) =>
          item.ingredient_id === result.ingredient_id
            ? { ...item, status: "pending" as const }
            : item,
        );
        setState({ phase: "active", session, items: updated });
        return result;
      } catch (e: unknown) {
        setError(extractApiError(e, fallback.undo()));
      } finally {
        setIsLoading(false);
      }
    },
    [state, recipeId, invalidateStock],
  );

  // Both answer whether the database took the request: the caller reports
  // "complete" or "cancelled" only on true, so a refusal leaves the session on
  // the sheet with its error instead of closing over it.
  const completeSession = useCallback(async (): Promise<boolean> => {
    if (state.phase !== "active") return false;
    setIsLoading(true);
    try {
      await recipesApi.completePicking(
        recipeId,
        state.session.picking_session_id,
      );
      invalidateStock();
      setState({ phase: "complete" });
      return true;
    } catch (e: unknown) {
      setError(extractApiError(e, fallback.complete()));
      return false;
    } finally {
      setIsLoading(false);
    }
  }, [state, recipeId, invalidateStock]);

  const cancelSession = useCallback(async (): Promise<boolean> => {
    const sessionId = openSessionId(state);
    if (!sessionId) return false;
    setIsLoading(true);
    try {
      await recipesApi.cancelPicking(recipeId, sessionId);
      // Cancel puts back every pick the session took — the shelves moved.
      invalidateStock();
      setState({ phase: "cancelled" });
      return true;
    } catch (e: unknown) {
      setError(extractApiError(e, fallback.cancel()));
      return false;
    } finally {
      setIsLoading(false);
    }
  }, [state, recipeId, invalidateStock]);

  /** Re-read the session after linking an ingredient at the shelf.
   *  The picks already made are kept by the backend; only the rows still
   *  open are resolved against stock again. */
  const refreshSession = useCallback(async () => {
    if (state.phase !== "active") return;
    const { session } = state;
    try {
      const fresh = await recipesApi.readPicking(
        recipeId,
        session.picking_session_id,
      );
      // Linking the ingredient is the way out of `unit_mismatch` and
      // `not_in_recipe`, so the fresh reading replaces the trace as well.
      setRefusals({});
      setState({ phase: "active", session: fresh, items: fresh.items_to_pick });
    } catch (e: unknown) {
      setError(extractApiError(e, fallback.refresh()));
    }
  }, [state, recipeId]);

  const reset = useCallback(() => {
    setState({ phase: "idle" });
    setError(null);
    setRefusals({});
  }, []);

  return {
    state,
    isLoading,
    error,
    refusals,
    startSession,
    scan,
    resolveDisambiguation,
    undoPick,
    dismissFefoMismatch,
    dismissOpenedSuggestion,
    completeSession,
    cancelSession,
    refreshSession,
    reset,
  };
}
