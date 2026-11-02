import { createPortal } from "react-dom";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { ChefHat, Star, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";
import { SheetActions, SheetFooter } from "@/components/ui/Sheet";
import { useFocusTrap } from "@/hooks/useFocusTrap";
import { formatQuantityValue } from "@/utils/formatters";
import { invalidation } from "@/lib/api/invalidation";
import { usePatchCookingHistory } from "@/modules/recipes/hooks/useRecipes";
import {
  useStockDeduction,
  type NotTakenRow,
  type DeductionOutcome,
} from "../hooks/useStockDeduction";
import { recipesApi } from "../api/recipes";

interface FinishedScreenProps {
  recipeId: string;
  recipeName: string;
  /** The entry this cooking writes on, awaited or asked for again.
   *
   * Borrowing the newest closed session wrote a rating onto a different
   * dinner (wrong day, wrong servings), so the cook records its own. The
   * screen waits for that record rather than reading it: the rating is
   * typed in the seconds after the request goes out, and a save that did
   * not wait dropped the note whenever the answer was slow — and said
   * nothing at all when it never came. */
  ensureEntry: () => Promise<string>;
  onClose: () => void;
  /** Whether to ask about the shelf at all: the cook that followed a picking
   * run had its ingredients carried already, and a recipe that names no
   * ingredients has nothing to carry. */
  canDeduct?: boolean;
  /** The servings this run cooked — the number the deduction works on. */
  servings?: number;
  /** Handed the session the deduction ran on, so the dinner's entry names it
   * and the history reads "picked", not "nothing picked". */
  onDeducted?: (sessionId: string) => void;
}

interface FailureState {
  message: string;
  sessionId: string | null;
  taken: number;
  total: number;
}

function DeductionSection({
  recipeId,
  servings,
  onDeducted,
  onBusyChange,
  onFailureChange,
}: {
  recipeId: string;
  servings: number;
  onDeducted?: (sessionId: string) => void;
  onBusyChange: (busy: boolean) => void;
  onFailureChange: (failure: FailureState | null) => void;
}) {
  const { t } = useTranslation("recipes");
  const { running, deduct } = useStockDeduction(recipeId);
  const [answer, setAnswer] = useState<"waiting" | "declined" | "taken">(
    "waiting",
  );
  const [outcome, setOutcome] = useState<DeductionOutcome | null>(null);
  const [blocked, setBlocked] = useState(false);
  const [failure, setFailure] = useState<FailureState | null>(null);

  const measured = (quantity: string, uom: string | null) => {
    const amount = formatQuantityValue(quantity);
    return uom ? `${amount} ${uom}` : amount;
  };

  const reasonSentence = (row: NotTakenRow) => {
    switch (row.reason) {
      case "nothing_on_shelf":
        return t("cooking_mode.deduct_reason_missing");
      case "unit_mismatch":
        return t("cooking_mode.deduct_reason_unit_mismatch", {
          required: measured(
            row.detail?.required ?? "",
            row.detail?.requiredUom ?? null,
          ),
          available: measured(
            row.detail?.available ?? "",
            row.detail?.availableUom ?? null,
          ),
        });
      case "not_in_recipe":
        return t("cooking_mode.deduct_reason_not_in_recipe");
      case "already_picked":
        return t("cooking_mode.deduct_reason_already_picked");
      default:
        return t("cooking_mode.deduct_reason_refused");
    }
  };

  const reportFailure = (next: FailureState | null) => {
    setFailure(next);
    onFailureChange(next);
  };

  const run = async () => {
    // The busy flag is the guard that keeps "Skip" and "Save" from closing the
    // screen while the walk owns the shelf. It is set here, around the walk
    // itself, rather than mirrored from `running` in an effect: an effect
    // reports one render late on BOTH ends, so a click in the frame the walk
    // starts got through the guard, and a click in the frame its result landed
    // was swallowed by the flag the next effect pass had not cleared yet.
    onBusyChange(true);
    try {
      const result = await deduct(servings, t("cooking_mode.deduct_fallback"));
      if (result.kind === "done") {
        // The walk finished, so the session from an earlier failed pass (if
        // any) is spent — remembering it would have closing the screen cancel
        // a dinner that is already complete.
        reportFailure(null);
        setOutcome(result.outcome);
        setAnswer("taken");
        onDeducted?.(result.outcome.sessionId);
      } else if (result.kind === "blocked") {
        reportFailure(null);
        setBlocked(true);
      } else {
        reportFailure({
          message: result.message,
          sessionId: result.sessionId,
          taken: result.taken,
          total: result.total,
        });
      }
    } finally {
      onBusyChange(false);
    }
  };

  if (answer === "declined") return null;

  return (
    <section
      aria-label={t("cooking_mode.deduct_question")}
      data-testid="deduct-section"
      className="w-full max-w-md rounded-xl border border-border bg-surface-card p-4 space-y-3"
    >
      {answer === "waiting" && !running && (
        <>
          <p className="text-sm font-medium text-on text-center">
            {t("cooking_mode.deduct_question")}
          </p>
          <div className="flex justify-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setAnswer("declined")}
              data-testid="deduct-decline"
            >
              {t("cooking_mode.deduct_decline")}
            </Button>
            <Button onClick={run} data-testid="deduct-confirm">
              {t("cooking_mode.deduct_confirm")}
            </Button>
          </div>
        </>
      )}

      {running && (
        <p role="status" className="text-sm text-on-muted text-center">
          {t("cooking_mode.deduct_taking")}
        </p>
      )}

      {answer === "taken" && outcome && (
        <div data-testid="deduct-result" className="space-y-2">
          <p className="text-sm font-medium text-success-600 text-center">
            {t("cooking_mode.deduct_done", { count: outcome.taken })}
          </p>
          {outcome.notTaken.length > 0 && (
            <div className="text-sm text-on-muted space-y-1">
              <p className="font-medium">
                {t("cooking_mode.deduct_not_taken_heading")}
              </p>
              <ul className="list-disc list-inside space-y-1">
                {outcome.notTaken.map((row, index) => (
                  <li key={`${row.name}-${row.reason}-${index}`}>
                    {row.name} — {reasonSentence(row)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {blocked && (
        <p
          role="alert"
          data-testid="deduct-blocked"
          className="text-sm text-on-danger"
        >
          {t("cooking_mode.deduct_blocked")}
        </p>
      )}

      {!blocked && failure && (
        <div data-testid="deduct-failure" className="space-y-2">
          <p role="alert" className="text-sm text-on-danger">
            {t("cooking_mode.deduct_failed", { message: failure.message })}
          </p>
          <p className="text-sm text-on-muted">
            {t("cooking_mode.deduct_progress", {
              taken: failure.taken,
              total: failure.total,
            })}
          </p>
          <p className="text-xs text-on-muted">
            {t("cooking_mode.deduct_close_restores")}
          </p>
          <div className="flex justify-center">
            <Button
              variant="outline"
              size="sm"
              onClick={run}
              data-testid="deduct-retry"
            >
              {t("cooking_mode.deduct_retry")}
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}

export function FinishedScreen({
  recipeId,
  recipeName,
  ensureEntry,
  onClose,
  canDeduct = false,
  servings,
  onDeducted,
}: FinishedScreenProps) {
  const { t } = useTranslation("recipes");
  const [notes, setNotes] = useState("");
  const [rating, setRating] = useState(0);
  const [saving, setSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const [entryFailed, setEntryFailed] = useState(false);
  const [deductBusy, setDeductBusy] = useState(false);
  const [failure, setFailure] = useState<FailureState | null>(null);
  const patchHistory = usePatchCookingHistory(recipeId);
  const queryClient = useQueryClient();
  // The same three things the cooking screen this one replaces already does:
  // hold the focus, answer Escape, and say what it is. Without them the
  // keyboard walks the page underneath a screen that covers the viewport.
  const dialogRef = useFocusTrap<HTMLDivElement>(true);

  /**
   * Every way out records the dinner first — the entry is asked here and no
   * longer when "Done" is pressed, because only now is it known WHICH run
   * the entry names: the deduction, if the reader confirmed it, else the
   * run a picking sheet handed over, else no run at all.
   */
  const resolveScreen = useCallback(
    async (withPatch: boolean) => {
      if (saving || deductBusy) return;
      setSaving(true);
      // A deduction that broke mid-road left its session open. Cancelling is
      // the promise the failure text made: what was taken goes back, and the
      // next "Take from stock" starts clean instead of resuming a half-read
      // checklist nobody remembers opening.
      if (failure?.sessionId) {
        recipesApi
          .cancelPicking(recipeId, failure.sessionId)
          // Cancel puts the failed run's picks back on the shelf; the stock
          // views behind the screen have to show the restored stock.
          .then(() => invalidation.picking(queryClient, recipeId))
          .catch(() => undefined);
      }
      setEntryFailed(false);
      setSaveFailed(false);
      try {
        const sessionId = await ensureEntry();
        if (withPatch && (notes.trim() || rating !== 0)) {
          try {
            await patchHistory.mutateAsync({
              sessionId,
              data: {
                notes: notes.trim() || null,
                rating: rating || null,
              },
            });
          } catch {
            // The note stays on screen; closing here is how a written note
            // used to disappear without a word.
            setSaveFailed(true);
            return;
          }
        }
        onClose();
      } catch {
        setEntryFailed(true);
      } finally {
        setSaving(false);
      }
    },
    [
      saving,
      deductBusy,
      failure,
      recipeId,
      queryClient,
      ensureEntry,
      notes,
      rating,
      patchHistory,
      onClose,
    ],
  );

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") void resolveScreen(false);
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [resolveScreen]);

  return createPortal(
    // The cooking screen swaps to this one in a single frame — a hard cut
    // between two full-screen layers. The fade says a screen changed.
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby="cooking-finished-title"
      tabIndex={-1}
      className="fixed inset-0 z-[var(--z-fullscreen)] bg-surface flex flex-col outline-none animate-in fade-in duration-300 motion-reduce:animate-none"
    >
      <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-surface-card flex-shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <ChefHat size={18} className="text-success-500 flex-shrink-0" />
          <span className="text-base font-semibold text-on truncate">
            {recipeName}
          </span>
        </div>
        <Button
          onClick={() => void resolveScreen(false)}
          variant="ghost"
          size="icon"
          className="hover:bg-surface"
          aria-label={t("cooking_mode.close")}
        >
          <X size={16} className="text-on-secondary" />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-8 flex flex-col items-center gap-6">
        <div className="text-center">
          <div className="w-14 h-14 rounded-full bg-accent-50 flex items-center justify-center mx-auto mb-3">
            <ChefHat size={28} className="text-accent-600" />
          </div>
          <h2
            id="cooking-finished-title"
            className="text-base font-semibold text-on"
          >
            {t("cooking_mode.finished_title")}
          </h2>
          <p className="text-sm text-on-muted mt-1">
            {t("cooking_mode.finished_subtitle")}
          </p>
        </div>

        {canDeduct && (
          <DeductionSection
            recipeId={recipeId}
            servings={servings ?? 1}
            onDeducted={onDeducted}
            onBusyChange={setDeductBusy}
            onFailureChange={setFailure}
          />
        )}

        <div className="flex items-center gap-1">
          {[1, 2, 3, 4, 5].map((star) => (
            <Button
              key={star}
              onClick={() => setRating(star === rating ? 0 : star)}
              variant="ghost"
              size="iconSm"
              aria-label={t("cooking.rateSession", { count: star })}
              title={t("cooking.rateSession", { count: star })}
            >
              <Star
                size={16}
                className={
                  star <= rating
                    ? "text-amber-400 fill-amber-400"
                    : "text-on-muted"
                }
              />
            </Button>
          ))}
        </div>

        {/* The width belongs to the box: `max-w-md` on the control narrows the
            textarea inside a wrapper still spanning the row, so `items-center`
            has nothing to centre and the note sits at the left edge. `w-full`
            is gone from `className` because the control already is. */}
        {entryFailed && (
          <p role="alert" className="text-sm text-on-danger text-center">
            {t("cooking_mode.entry_failed")}
          </p>
        )}
        {saveFailed && (
          <p role="alert" className="text-sm text-on-danger text-center">
            {t("cooking_mode.save_failed")}
          </p>
        )}

        <Textarea
          wrapperClassName="max-w-md"
          aria-label={t("cooking_mode.notes_placeholder")}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder={t("cooking_mode.notes_placeholder")}
          className="h-32 rounded-xl border border-border bg-surface-card px-4 py-3 text-sm text-on placeholder:text-on-muted resize-none focus:outline-none focus:ring-2 focus:ring-primary-300"
        />
      </div>

      <SheetFooter>
        <SheetActions>
          <Button
            variant="outline"
            onClick={() => void resolveScreen(false)}
            disabled={saving}
          >
            {t("cooking_mode.skip_notes")}
          </Button>
          <Button onClick={() => void resolveScreen(true)} isLoading={saving}>
            {t("cooking_mode.save_and_close")}
          </Button>
        </SheetActions>
      </SheetFooter>
    </div>,
    document.body,
  );
}
