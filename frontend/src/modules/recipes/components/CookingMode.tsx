import { useState, useMemo, useEffect, useCallback, useRef } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import {
  X,
  ChefHat,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ListChecks,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useFocusTrap } from "@/hooks/useFocusTrap";
import { formatQuantityLocale } from "@/utils/formatters";
import { useCreateCookingHistory } from "@/modules/recipes/hooks/useRecipes";
import { FinishedScreen } from "./FinishedScreen";
import { StepCard } from "./StepCard";
import type { RecipeIngredient } from "@/modules/recipes/types/core";
import type { CookingHistoryItem } from "@/modules/recipes/types/nutrition";
import {
  parseInstructions,
  hasMarkdown,
  type ParsedBlock,
} from "./InstructionsView";
import { unitLabel } from "@/lib/i18nHelpers";

export interface CookingModeProps {
  recipeId: string;
  recipeName: string;
  instructions: string;
  ingredients?: RecipeIngredient[];
  /** Servings this run cooks — the number its history entry carries. */
  servings?: number;
  /** The picking run this cook continues, when it follows one.
   *
   * Picking the ingredients and then cooking them is one dinner. Without
   * this the cook opened a second history entry beside the picked one: the
   * picked run stayed unrated and the note landed on an entry reading
   * "nothing picked". */
  pickingSessionId?: string;
  /** Called once the picked run above has been recorded as this dinner.
   *
   * One run belongs to one meal: cooking the same recipe again handed the
   * same run over a second time, and the second rating overwrote the first
   * evening's. Only this screen knows an entry was actually written, so it
   * is the one that says the thread is spent — and it stays silent when the
   * request failed, because then the dinner is still uncooked. */
  onSessionConsumed?: () => void;
  onClose: () => void;
}

function formatQty(value: number | string): string {
  // A quantity on the cooking screen is a quantity anywhere else: the
  // shared formatter decides the places and the decimal mark, and takes the
  // wire's Decimal string as-is. Non-numeric input comes back unchanged.
  return formatQuantityLocale(value, 3);
}

// Time units in EN, PL and their common Polish declined forms
// ("minucie", "minuty", "minutach", "godzinę", ...). The negative
// lookahead replaces \b because ę is a non-word char for \b, and the
// declined forms extend past the bare stem ("minuty" ⊃ "minut").
const UNIT_ALTERNATION =
  "minutach|minuty|minutę|minucie|minuta|minutes|minute|minut|min" +
  "|sekundach|sekundy|sekundę|sekunda|seconds|second|sekund|sec" +
  "|godzinach|godziny|godzinę|godzina|hours|hour|godzin|godz|h";
const UNIT_TAIL = "(?![a-zA-Z])";

const TIME_RE = new RegExp(
  `(\\d+)\\s*(?:-\\s*\\d+\\s*)?(?:${UNIT_ALTERNATION})${UNIT_TAIL}`,
  "i",
);
const UNIT_RE = new RegExp(`(?:${UNIT_ALTERNATION})${UNIT_TAIL}`, "i");

// Inline numbered steps like "1. Boil water. 2. Fry onions." on a single line.
// A segment must start at the text beginning or after a sentence separator
// (".", ";", ":") and the numbers must be sequential from 1.
const INLINE_STEP_SEP_RE = /(?:^|[.;:])\s*(\d+)[.)]\s+/g;

function splitInlineSteps(text: string): string[] | null {
  const matches = Array.from(text.matchAll(INLINE_STEP_SEP_RE));
  if (matches.length < 2) return null;
  const numbers = matches.map((m) => parseInt(m[1], 10));
  const sequentialFromOne =
    numbers[0] === 1 && numbers.every((n, i) => n === i + 1);
  if (!sequentialFromOne) return null;
  const steps: string[] = [];
  for (let i = 0; i < matches.length; i++) {
    const numPart = matches[i][0].match(/\d+[.)]\s+/)!;
    const start =
      (matches[i].index ?? 0) + (numPart.index ?? 0) + numPart[0].length;
    const end =
      i + 1 < matches.length ? (matches[i + 1].index ?? 0) : text.length;
    const body = text
      .slice(start, end)
      .replace(/^[.;:]\s*/, "")
      .trim();
    if (body) steps.push(body);
  }
  return steps.length >= 2 ? steps : null;
}

function extractTimerSeconds(text: string): number | null {
  const match = text.match(TIME_RE);
  if (!match) return null;
  const value = parseInt(match[0], 10);
  const unitMatch = text.match(UNIT_RE);
  if (!unitMatch) return null;
  const unit = unitMatch[0].toLowerCase();
  if (/^(sekund|sec|second)/.test(unit)) return value;
  if (/^(godzin|hour|godz|h$)/.test(unit)) return value * 3600;
  return value * 60;
}

export function buildSteps(instructions: string): ParsedBlock[] {
  const inlineSteps = splitInlineSteps(instructions.trim());
  if (inlineSteps && inlineSteps.length >= 2) {
    return inlineSteps.map((body, i) => ({
      type: "step" as const,
      stepNumber: i + 1,
      body,
      title: "",
    }));
  }

  if (hasMarkdown(instructions)) {
    const lines = instructions.split("\n");
    const result: ParsedBlock[] = [];
    let current: ParsedBlock | null = null;
    let stepNum = 0;
    for (const line of lines) {
      const trimmed = line.trim();
      if (/^#{1,6}\s+/.test(trimmed)) {
        // Markdown headings are section labels, not cooking steps.
        continue;
      }
      if (/^\d+\.\s+/.test(trimmed)) {
        if (current) result.push(current);
        stepNum++;
        const title = trimmed.replace(/^\d+\.\s+/, "");
        current = { type: "step", stepNumber: stepNum, title, body: "" };
      } else if (trimmed) {
        if (current) {
          current.body += (current.body ? "\n" : "") + trimmed;
        } else {
          stepNum++;
          current = {
            type: "step",
            stepNumber: stepNum,
            title: "",
            body: trimmed,
          };
        }
      }
    }
    if (current) result.push(current);
    return result.length > 0
      ? result
      : [{ type: "step", stepNumber: 1, body: instructions, title: "" }];
  }

  const parsed = parseInstructions(instructions);
  const onlySteps = parsed.filter((b) => b.type === "step");
  if (onlySteps.length > 0) return onlySteps;

  // The recipe form promises "one step per line (or numbering: 1. 2. 3.)" and
  // this fallback split on blank lines only, so three lines typed exactly as
  // asked came out as one step — step-by-step mode with a single step, and a
  // twelve-hour timer hanging over stirring and baking as well.
  //
  // A blank line anywhere means the author is grouping lines into steps
  // deliberately, and that grouping wins; without one, every line is a step.
  const groupedByBlankLine = /\n\s*\n/.test(instructions);
  const chunks = instructions
    .split(groupedByBlankLine ? /\n\s*\n/ : /\n/)
    .map((p) => p.trim())
    .filter(Boolean);
  if (chunks.length <= 1) {
    return [
      { type: "step", stepNumber: 1, body: instructions.trim(), title: "" },
    ];
  }
  return chunks.map((p, i) => ({
    type: "step" as const,
    stepNumber: i + 1,
    body: p,
    title: "",
  }));
}

interface CookingStepCardProps {
  step: ParsedBlock;
  index: number;
  isActive: boolean;
  timerForStep: number | null;
  timerSeconds: number | null;
  timerRunning: boolean;
  t: TFunction;
  onSelect: (index: number) => void;
  onRef: (el: HTMLDivElement | null) => void;
  onStartTimer: (seconds: number) => void;
  onToggleTimer: () => void;
  onResetTimer: () => void;
}

/** A single step card in CookingMode — keyboard-reachable and labelled.
 * Extracted to keep CookingMode under the complexity caps. */
/**
 * The jump-to-step strip. Each segment is a real button with its own label, so
 * it stays keyboard- and screen-reader-reachable; the 44px touch target lives
 * on the button while the visible bar inside it stays 6px.
 */
function StepProgressBar({
  steps,
  activeStep,
  onSelect,
  t,
}: {
  steps: number;
  activeStep: number;
  onSelect: (index: number) => void;
  t: TFunction;
}) {
  if (steps <= 1) return null;
  return (
    <div className="px-4 pt-3 pb-1 flex-shrink-0">
      <div className="flex items-center gap-1">
        {Array.from({ length: steps }, (_, i) => (
          <Button
            key={i}
            onClick={() => onSelect(i)}
            variant="ghost"
            size="sm"
            className="flex-1 px-0 py-0 rounded-full hover:bg-transparent active:bg-transparent"
            aria-label={t("cooking_mode.go_to_step", { step: i + 1 })}
            aria-current={i === activeStep ? "step" : undefined}
          >
            <span
              aria-hidden="true"
              className={`block w-full h-1.5 rounded-full ${
                i === activeStep
                  ? "bg-primary-500"
                  : i < activeStep
                    ? "bg-primary-200"
                    : "bg-border"
              }`}
            />
          </Button>
        ))}
      </div>
    </div>
  );
}

function CookingStepCard({
  step,
  index,
  isActive,
  timerForStep,
  timerSeconds,
  timerRunning,
  t,
  onSelect,
  onRef,
  onStartTimer,
  onToggleTimer,
  onResetTimer,
}: CookingStepCardProps) {
  return (
    <div
      ref={onRef}
      role="button"
      aria-label={t("cooking_mode.step_label", { step: index + 1 })}
      aria-current={isActive ? "step" : undefined}
      tabIndex={0}
      onClick={() => onSelect(index)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(index);
        }
      }}
      className={`rounded-xl border transition-all duration-200 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background ${
        isActive
          ? "bg-surface-card border-primary-300 shadow-md ring-1 ring-primary-200 py-5 px-5"
          : "bg-surface border-transparent py-3 px-5"
      }`}
    >
      <StepCard
        step={step}
        isActive={isActive}
        timerForStep={timerForStep}
        timerSeconds={timerSeconds}
        timerRunning={timerRunning}
        t={t}
        onStartTimer={onStartTimer}
        onToggleTimer={onToggleTimer}
        onResetTimer={onResetTimer}
      />
    </div>
  );
}

/**
 * The history entry this cook records, and the one request that writes it.
 *
 * Finishing a cook records its own entry — its own date and servings —
 * instead of letting the rating borrow whichever session closed last. The
 * entry is asked for when the finished screen resolves rather than the
 * moment the cook ends, because only then is it known WHICH run the entry
 * names: the reader is asked there whether the ingredients come off the
 * shelf, and a confirmed deduction hands the entry its own session. What
 * the finished screen still needs is the request, not its result: holding
 * the promise lets a save wait for a slow answer instead of dropping the
 * note the reader just wrote, and lets a failed request be asked again
 * when they press save.
 */
function useCookingEntry(
  recipeId: string,
  servings: number | undefined,
  pickingSessionId: string | undefined,
  onSessionConsumed: (() => void) | undefined,
) {
  const createHistoryEntry = useCreateCookingHistory(recipeId);
  const entryRequest = useRef<Promise<CookingHistoryItem> | null>(null);
  const requestEntry = useCallback(() => {
    const pending = createHistoryEntry.mutateAsync({
      servings,
      sessionId: pickingSessionId,
    });
    entryRequest.current = pending;
    pending.then(
      () => {
        // The picked run is now this dinner's, and no later cook may name it.
        if (pickingSessionId) onSessionConsumed?.();
      },
      () => {
        // A failure must not stay latched onto the ref: the save button asks
        // again, and a rejected promise would refuse forever. The run stays
        // unspent too — nothing was written, so it is still this dinner's.
        if (entryRequest.current === pending) entryRequest.current = null;
      },
    );
    return pending;
  }, [createHistoryEntry, servings, pickingSessionId, onSessionConsumed]);
  const ensureEntry = useCallback(
    async () => (await (entryRequest.current ?? requestEntry())).session_id,
    [requestEntry],
  );
  return { requestEntry, ensureEntry };
}

export default function CookingMode({
  recipeId,
  recipeName,
  instructions,
  ingredients,
  servings,
  pickingSessionId,
  onSessionConsumed,
  onClose,
}: CookingModeProps) {
  const { t } = useTranslation("recipes");
  // The run the dinner's entry names: one a picking sheet handed over, or
  // the deduction the reader confirms on the finished screen. They exclude
  // each other — the question is only asked when no picking preceded.
  const [deductionSessionId, setDeductionSessionId] = useState<
    string | undefined
  >(undefined);
  const { ensureEntry } = useCookingEntry(
    recipeId,
    servings,
    pickingSessionId ?? deductionSessionId,
    onSessionConsumed,
  );
  const steps = useMemo(() => buildSteps(instructions), [instructions]);
  const stepRefs = useRef<(HTMLDivElement | null)[]>([]);

  // the overlay is a modal dialog — focus starts inside it and Tab
  // cycles through the overlay instead of escaping to the page behind.
  // Through the shared trap, which also hands focus back to whatever
  // opened the overlay when it closes; the private copy did not.
  const dialogRef = useFocusTrap<HTMLDivElement>(true);

  const [activeStep, setActiveStep] = useState(0);
  const [finished, setFinished] = useState(false);
  const [showIngredients, setShowIngredients] = useState(false);
  const [timerSeconds, setTimerSeconds] = useState<number | null>(null);
  const [timerRunning, setTimerRunning] = useState(false);
  const [timerInitial, setTimerInitial] = useState<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const isFirst = activeStep === 0;
  const isLast = activeStep === steps.length - 1;

  // Detect timer in active step
  const detectedTimer = useMemo(() => {
    const step = steps[activeStep];
    const fullText = (step?.title ?? "") + " " + (step?.body ?? "");
    return extractTimerSeconds(fullText);
  }, [steps, activeStep]);

  // Wake Lock
  useEffect(() => {
    let wakeLock: WakeLockSentinel | null = null;
    async function acquire() {
      try {
        if ("wakeLock" in navigator) {
          wakeLock = await navigator.wakeLock.request("screen");
        }
      } catch {
        // not supported or denied
      }
    }
    acquire();
    return () => {
      wakeLock?.release();
    };
  }, []);

  // Timer tick
  useEffect(() => {
    if (timerRunning && timerSeconds !== null && timerSeconds > 0) {
      timerRef.current = setInterval(() => {
        setTimerSeconds((prev) => {
          if (prev === null || prev <= 1) {
            setTimerRunning(false);
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [timerRunning, timerSeconds]);

  // Timer done — vibrate
  useEffect(() => {
    if (timerSeconds === 0 && timerInitial !== null) {
      if ("vibrate" in navigator) navigator.vibrate([200, 100, 200, 100, 200]);
    }
  }, [timerSeconds, timerInitial]);

  const startTimer = useCallback((seconds: number) => {
    setTimerSeconds(seconds);
    setTimerInitial(seconds);
    setTimerRunning(true);
  }, []);

  const resetTimer = useCallback(() => {
    setTimerRunning(false);
    setTimerSeconds(null);
    setTimerInitial(null);
  }, []);

  // Scroll active step into view
  useEffect(() => {
    const el = stepRefs.current[activeStep];
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [activeStep]);

  const selectStep = useCallback(
    (index: number) => {
      if (index !== activeStep) {
        resetTimer();
      }
      setActiveStep(index);
    },
    [activeStep, resetTimer],
  );

  // Keyboard: Escape to close, Up/Down to navigate steps
  useEffect(() => {
    if (finished) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose();
      } else if (e.key === "ArrowDown" || e.key === "ArrowRight") {
        e.preventDefault();
        setActiveStep((s) => {
          const next = Math.min(s + 1, steps.length - 1);
          if (next !== s) resetTimer();
          return next;
        });
      } else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
        e.preventDefault();
        setActiveStep((s) => {
          const prev = Math.max(s - 1, 0);
          if (prev !== s) resetTimer();
          return prev;
        });
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose, steps.length, resetTimer, finished]);

  const goNext = useCallback(() => {
    if (!isLast) {
      resetTimer();
      setActiveStep((s) => s + 1);
    }
  }, [isLast, resetTimer]);

  const goPrev = useCallback(() => {
    if (!isFirst) {
      resetTimer();
      setActiveStep((s) => s - 1);
    }
  }, [isFirst, resetTimer]);

  const handleFinish = useCallback(() => {
    resetTimer();
    // The entry is NOT asked here any more: the finished screen first asks
    // whether the ingredients come off the shelf, and its answer decides
    // which run the entry names. Every way out of that screen records the
    // dinner before it closes.
    setFinished(true);
  }, [resetTimer]);

  if (finished) {
    return (
      <FinishedScreen
        recipeId={recipeId}
        recipeName={recipeName}
        ensureEntry={ensureEntry}
        onClose={onClose}
        canDeduct={!pickingSessionId && !!ingredients?.length}
        servings={servings}
        onDeducted={setDeductionSessionId}
      />
    );
  }

  return createPortal(
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-label={recipeName}
      tabIndex={-1}
      className="fixed inset-0 z-[var(--z-fullscreen)] bg-surface flex flex-col outline-none"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-surface-card flex-shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <ChefHat size={18} className="text-primary-500 flex-shrink-0" />
          <span className="text-base font-semibold text-on truncate">
            {recipeName}
          </span>
        </div>
        <Button
          onClick={onClose}
          variant="ghost"
          size="icon"
          className="hover:bg-surface"
          aria-label={t("cooking_mode.close")}
        >
          <X size={16} className="text-on-secondary" />
        </Button>
      </div>

      {/* Ingredients — collapsible, closed by default */}
      {ingredients && ingredients.length > 0 && (
        <div className="px-4 pt-3 flex-shrink-0">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowIngredients((v) => !v)}
            aria-expanded={showIngredients}
            className="w-full justify-between gap-2 border border-border bg-surface-card"
          >
            <span className="flex items-center gap-2 min-w-0">
              <ListChecks
                size={16}
                className="text-primary-500 flex-shrink-0"
              />
              <span className="text-sm font-semibold text-on truncate">
                {t("cooking_mode.ingredients")}
              </span>
              <span className="text-xs text-on-secondary">
                ({ingredients.length})
              </span>
            </span>
            <ChevronDown
              size={16}
              className={`text-on-secondary flex-shrink-0 transition-transform ${
                showIngredients ? "rotate-180" : ""
              }`}
            />
          </Button>
          {showIngredients && (
            <ul className="mt-2 rounded-xl border border-border bg-surface-card p-3 space-y-1.5">
              {ingredients.map((ing) => (
                <li
                  key={ing.id ?? ing.name}
                  className="flex items-baseline justify-between gap-3 text-sm"
                >
                  <span className="text-on min-w-0">{ing.name}</span>
                  <span className="text-on-secondary whitespace-nowrap">
                    {formatQty(ing.quantity)} {unitLabel(t, ing.uom_symbol)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <StepProgressBar
        steps={steps.length}
        activeStep={activeStep}
        onSelect={selectStep}
        t={t}
      />

      {/* All steps — magnifying glass style */}
      <div
        className={`flex-1 overflow-y-auto px-4 py-4 space-y-3 ${
          steps.length === 1 ? "flex items-center justify-center" : ""
        }`}
      >
        {steps.map((step, i) => (
          <CookingStepCard
            key={i}
            step={step}
            index={i}
            isActive={i === activeStep}
            timerForStep={i === activeStep ? detectedTimer : null}
            timerSeconds={i === activeStep ? timerSeconds : null}
            timerRunning={timerRunning}
            t={t}
            onSelect={selectStep}
            onRef={(el) => {
              stepRefs.current[i] = el;
            }}
            onStartTimer={startTimer}
            onToggleTimer={() => setTimerRunning((r) => !r)}
            onResetTimer={resetTimer}
          />
        ))}
      </div>

      {/* Navigation bar — 48px touch targets, clear of the home
          indicator and the Safari bottom bar. */}
      <div className="px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] border-t border-border bg-surface-card flex items-center gap-2 flex-shrink-0">
        <Button
          size="content"
          variant="ghost"
          onClick={goPrev}
          disabled={isFirst}
          className="gap-1 h-12 px-5 text-base"
        >
          <ChevronLeft size={16} />
          {t("cooking_mode.prev")}
        </Button>
        <div className="flex-1" />
        {isLast ? (
          <Button
            size="content"
            onClick={handleFinish}
            className="gap-1.5 h-12 px-5 text-base"
          >
            <ChefHat size={16} />
            {t("cooking_mode.finish")}
          </Button>
        ) : (
          <Button
            size="content"
            variant="ghost"
            onClick={goNext}
            className="gap-1 h-12 px-5 text-base"
          >
            {t("cooking_mode.next")}
            <ChevronRight size={16} />
          </Button>
        )}
      </div>
    </div>,
    document.body,
  );
}
