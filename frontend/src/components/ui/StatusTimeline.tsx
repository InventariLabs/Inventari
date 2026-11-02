export interface StatusTimelineStep {
  key: string;
  label: string;
  date: string | null;
  state: "complete" | "current" | "upcoming";
}

interface StatusTimelineProps {
  title: string;
  steps: StatusTimelineStep[];
  /** Renders a step's date; owns the empty case (usually an em dash). */
  formatDate: (dateStr: string | null) => string;
}

/**
 * Where a record is in its lifecycle, drawn the same way everywhere.
 *
 * Documents had this axis and purchase orders did not, so two screens showing
 * the same kind of thing read as two products. The steps and their
 * vocabulary belong to the caller; this owns only the drawing.
 *
 * Vertical on phones: three long step labels plus dots and connectors exceed
 * 390px in a row, and the last label was the one clipped.
 */
export function StatusTimeline({
  title,
  steps,
  formatDate,
}: StatusTimelineProps) {
  return (
    <div className="pt-4 border-t border-border space-y-3">
      <p className="text-[10px] font-medium uppercase tracking-widest text-on-muted">
        {title}
      </p>

      <ol
        aria-label={title}
        className="flex flex-col gap-3 sm:flex-row sm:items-start sm:gap-0"
      >
        {steps.map((step, index) => {
          const isComplete = step.state === "complete";
          const isCurrent = step.state === "current";

          return (
            <li
              key={step.key}
              aria-current={isCurrent ? "step" : undefined}
              className="flex items-start gap-2.5 sm:flex-1"
            >
              <span
                aria-hidden="true"
                className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${
                  isCurrent
                    ? "bg-primary-600 ring-4 ring-primary-100"
                    : isComplete
                      ? "bg-primary-600"
                      : "bg-border"
                }`}
              />
              <div className="min-w-0">
                <p
                  className={`text-sm font-medium ${
                    isCurrent
                      ? "text-primary-700"
                      : isComplete
                        ? "text-on"
                        : "text-on-muted"
                  }`}
                >
                  {step.label}
                </p>
                <p className="text-xs text-on-muted">{formatDate(step.date)}</p>
              </div>
              {index < steps.length - 1 && (
                <span
                  aria-hidden="true"
                  className={`mx-2 mt-2.5 h-px flex-1 hidden sm:block ${
                    isComplete ? "bg-primary-300" : "bg-border"
                  }`}
                />
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
