import { useState, useMemo, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { usePickingSession } from "../hooks/usePickingSession";
import type {
  PickingItem,
  PickingScanResponse,
  RecipeIngredient,
} from "@/modules/recipes/types/core";
import { toast } from "sonner";
import { findCleanServings, COUNTABLE_UOMS } from "../utils";
import PickingIdlePhase from "./PickingIdlePhase";
import PickingActivePhase from "./PickingActivePhase";
import { formatQuantityValue, toAmount } from "@/utils/formatters";
import { unitLabel } from "@/lib/i18nHelpers";

interface Props {
  recipeId: string;
  recipeName: string;
  defaultServings?: number;
  /** The meal-plan card Cook Now was pressed on. */
  mealPlanEntryId?: string;
  baseServings?: number;
  ingredients?: RecipeIngredient[];
  onClose: (completed?: boolean, sessionId?: string) => void;
}

export default function PickingView({
  recipeId,
  recipeName,
  defaultServings = 1,
  mealPlanEntryId,
  baseServings,
  ingredients: recipeIngredients,
  onClose,
}: Props) {
  const { t } = useTranslation(["recipes", "common"]);
  const [servings, setServings] = useState(defaultServings);

  const {
    state,
    isLoading,
    error,
    refusals,
    startSession,
    scan,
    resolveDisambiguation,
    undoPick,
    dismissOpenedSuggestion,
    completeSession,
    cancelSession,
    refreshSession,
    reset,
  } = usePickingSession(recipeId, mealPlanEntryId);

  const cleanServingsHint = useMemo(() => {
    if (!recipeIngredients || !baseServings) return null;
    const clean = findCleanServings(baseServings, recipeIngredients, servings);
    if (clean.length === 0) return null;
    const countable = recipeIngredients.filter(
      (i) =>
        COUNTABLE_UOMS.has((i.uom_symbol ?? "").toLowerCase()) &&
        (toAmount(i.quantity) ?? 0) > 0,
    );
    const hasFractional = countable.some((ing) => {
      const qty = ((toAmount(ing.quantity) ?? 0) * servings) / baseServings;
      return Math.abs(qty - Math.round(qty)) > 0.001;
    });
    if (!hasFractional) return null;
    const nearby = clean.filter((s) => Math.abs(s - servings) <= 4).slice(0, 3);
    if (nearby.length === 0) return null;
    return t("picking.clean_servings_hint", { counts: nearby.join(", ") });
  }, [servings, baseServings, recipeIngredients, t]);

  // The amount is written the reader's way and without the column's
  // padding; the unit is appended only when the line records one.
  const measured = (quantity: number, uom: string | null) => {
    const amount = formatQuantityValue(quantity);
    return uom ? `${amount} ${uom}` : amount;
  };

  const notifyScanResult = (result: PickingScanResponse | null | undefined) => {
    if (!result) return;
    if (result.status === "picked") {
      toast.success(
        t("picking.scan_result.picked", {
          // A decimal string from the API ("200.000"), written the reader's way.
          quantity: formatQuantityValue(result.quantity_consumed),
          uom: unitLabel(t, result.uom_symbol),
          ingredient: result.ingredient_name ?? "",
        }),
      );
    } else if (result.status === "unit_mismatch" && result.unit_mismatch) {
      // Nothing left the shelf — say what the two readings were and what
      // would make them comparable, instead of a bare failure.
      toast.error(
        t("picking.scan_result.unit_mismatch", {
          ingredient: result.ingredient_name ?? "",
          required: measured(
            result.unit_mismatch.required_quantity,
            result.unit_mismatch.required_uom,
          ),
          available: measured(
            result.unit_mismatch.available_quantity,
            result.unit_mismatch.available_uom,
          ),
        }),
        { description: t("picking.scan_result.unit_mismatch_hint") },
      );
    } else if (result.status === "not_in_recipe") {
      toast.error(t("picking.scan_result.not_in_recipe"));
    } else if (result.status === "already_picked") {
      toast(t("picking.scan_result.already_picked"));
    }
  };

  // A session that was already open comes back instead of a new one, with the
  // servings it was started for. Saying nothing would leave the reader looking
  // at a checklist half ticked off for a number they did not choose.
  const handleStart = async () => {
    const session = await startSession(servings);
    if (session?.resumed) {
      setServings(session.servings);
      toast(t("picking.resumed", { count: session.servings }));
    }
  };

  const handleScan = async (barcode: string) => {
    notifyScanResult(await scan({ barcode }));
  };

  const handleTapIngredient = async (item: PickingItem) => {
    if (!item.recommended_item_id) return;
    notifyScanResult(
      await scan({ item_id: item.recommended_item_id, from_checklist: true }),
    );
  };

  const handleUndoIngredient = async (item: PickingItem) => {
    const result = await undoPick(item.ingredient_id);
    if (result) {
      toast(t("picking.undo_success", { ingredient: result.ingredient_name }));
    }
  };

  const handleComplete = async () => {
    // Capture before completeSession()/reset() drops the session from state —
    // callers (e.g. meal plan rating prompt) need the completed session id.
    const sessionId =
      state.phase === "active" ? state.session.picking_session_id : undefined;
    // A refused completion leaves the session open: no toast, no close, and
    // the error stays above the checklist for the retry.
    if (!(await completeSession())) return;
    toast.success(t("picking.session_complete"));
    reset();
    onClose(true, sessionId);
  };

  const handleCancel = async () => {
    // Nothing went back to the shelf until the server says so.
    if (!(await cancelSession())) return;
    toast(t("picking.cancelled"));
    reset();
    onClose();
  };

  const handleClose = () => {
    // Closing the sheet is not a decision to put anything back: what was
    // picked stays on the session, and the next "Take from stock" resumes
    // it ("Picked up where you left off"), exactly as leaving via the
    // browser's back arrow always did. Putting things back is the named
    // Cancel button's job, and it says so with its toast.
    reset();
    onClose();
  };

  // Fallback: if complete/cancelled phase is reached (shouldn't normally happen)
  useEffect(() => {
    if (state.phase === "complete" || state.phase === "cancelled") {
      const wasComplete = state.phase === "complete";
      reset();
      onClose(wasComplete);
    }
  }, [state.phase, reset, onClose]);

  if (state.phase === "idle") {
    return (
      <PickingIdlePhase
        recipeName={recipeName}
        servings={servings}
        onServingsChange={setServings}
        cleanServingsHint={cleanServingsHint}
        isLoading={isLoading}
        error={error}
        onStart={handleStart}
        // No arguments on purpose: the idle phase hands its button's click
        // event to this, and a caller reads the first argument as "completed".
        onClose={() => onClose()}
        t={t}
      />
    );
  }

  if (state.phase === "complete" || state.phase === "cancelled") {
    return null;
  }

  return (
    <PickingActivePhase
      phase={state.phase}
      session={state.session}
      items={state.items}
      refusals={refusals}
      scanResult={"scanResult" in state ? state.scanResult : undefined}
      recipeName={recipeName}
      servings={servings}
      isLoading={isLoading}
      error={error}
      onScan={handleScan}
      onTapIngredient={handleTapIngredient}
      onUndoIngredient={handleUndoIngredient}
      recipeId={recipeId}
      onLinked={refreshSession}
      onComplete={handleComplete}
      onCancel={handleCancel}
      onClose={handleClose}
      resolveDisambiguation={resolveDisambiguation}
      dismissOpenedSuggestion={dismissOpenedSuggestion}
    />
  );
}
