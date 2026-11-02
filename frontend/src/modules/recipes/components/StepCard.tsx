import { Timer, Pause, Play, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/Button";
import type { TFunction } from "i18next";
import type { ParsedBlock } from "./InstructionsView";

interface StepCardProps {
  step: ParsedBlock;
  isActive: boolean;
  timerForStep: number | null;
  timerSeconds: number | null;
  timerRunning: boolean;
  t: TFunction;
  onStartTimer: (seconds: number) => void;
  onToggleTimer: () => void;
  onResetTimer: () => void;
}

export function StepCard({
  step,
  isActive,
  timerForStep,
  timerSeconds,
  timerRunning,
  t,
  onStartTimer,
  onToggleTimer,
  onResetTimer,
}: StepCardProps) {
  return (
    <div className="flex items-start gap-3">
      <div
        className={`flex-shrink-0 rounded-full flex items-center justify-center transition-all duration-200 ${
          isActive
            ? "w-8 h-8 bg-primary-800 text-white"
            : "w-6 h-6 bg-surface-card border border-border text-on-muted"
        }`}
      >
        <span className={`font-medium ${isActive ? "text-sm" : "text-xs"}`}>
          {step.stepNumber}
        </span>
      </div>
      <div className="flex-1 min-w-0">
        {step.title && (
          <h3
            className={`font-semibold transition-all duration-200 ${
              isActive ? "text-2xl text-on mb-2" : "text-base text-on-secondary"
            }`}
          >
            {step.title}
          </h3>
        )}
        {step.body.trim() && (
          <p
            className={`whitespace-pre-wrap leading-relaxed transition-all duration-200 ${
              isActive ? "text-2xl text-on-secondary" : "text-sm text-on-muted"
            }`}
          >
            {step.body.trim()}
          </p>
        )}

        {isActive && timerForStep && timerSeconds === null && (
          <Button
            size="content"
            variant="ghost"
            onClick={(e) => {
              e.stopPropagation();
              onStartTimer(timerForStep);
            }}
            className="mt-4 w-full gap-2 px-4 py-2.5 bg-primary-50 border border-primary-500 rounded-xl text-on font-semibold hover:bg-primary-50"
          >
            <Timer size={16} />
            {t("recipes:cooking_mode.start_timer", {
              time: formatTimer(timerForStep),
            })}
          </Button>
        )}

        {isActive && timerSeconds !== null && (
          <div className="mt-4 flex flex-col items-center gap-2">
            <div
              className={`text-3xl font-mono tabular-nums ${
                timerSeconds === 0 ? "text-red-500 animate-pulse" : "text-on"
              }`}
            >
              {formatTimer(timerSeconds)}
            </div>
            <div className="flex items-center gap-2">
              {timerSeconds > 0 && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggleTimer();
                  }}
                  className="gap-1.5"
                >
                  {timerRunning ? (
                    <>
                      <Pause size={16} /> {t("recipes:cooking_mode.pause")}
                    </>
                  ) : (
                    <>
                      <Play size={16} /> {t("recipes:cooking_mode.resume")}
                    </>
                  )}
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onResetTimer();
                }}
                className="gap-1.5"
              >
                <RotateCcw size={16} /> {t("recipes:cooking_mode.reset")}
              </Button>
            </div>
            {timerSeconds === 0 && (
              <p className="text-sm font-medium text-red-600">
                {t("recipes:cooking_mode.timer_done")}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function formatTimer(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) {
    return `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  }
  return `${m}:${s.toString().padStart(2, "0")}`;
}
