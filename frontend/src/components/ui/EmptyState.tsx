import * as React from "react";
import { ArrowRight, type LucideIcon } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { cn } from "@/lib/utils";

export interface EmptyStateStep {
  title: string;
  description?: string;
}

export interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: string;
  primaryAction?: React.ReactNode;
  secondaryAction?: React.ReactNode;
  steps?: EmptyStateStep[];
  variant?: "default" | "compact" | "steps";
  className?: string;
}

export const EmptyState = React.forwardRef<HTMLDivElement, EmptyStateProps>(
  (
    {
      icon: Icon,
      title,
      description,
      primaryAction,
      secondaryAction,
      steps,
      variant = "default",
      className,
    },
    ref,
  ) => {
    const iconWrap = Icon ? (
      <div
        className={cn(
          "mx-auto flex items-center justify-center rounded-2xl bg-surface-inset text-on-muted",
          variant === "compact" ? "w-12 h-12 mb-3" : "w-20 h-20 mb-5",
        )}
        aria-hidden="true"
      >
        <Icon size={variant === "compact" ? 24 : 36} strokeWidth={1.75} />
      </div>
    ) : null;

    const actions = (primaryAction || secondaryAction) && (
      <div
        className={cn(
          "flex flex-wrap items-center justify-center gap-2",
          variant === "compact" ? "mt-3" : "mt-6",
        )}
      >
        {primaryAction}
        {secondaryAction}
      </div>
    );

    const stepList =
      steps && steps.length > 0 ? (
        <ol
          className="mt-6 space-y-3 text-left max-w-md mx-auto"
          aria-label={title}
        >
          {steps.map((step, idx) => (
            <li
              key={idx}
              className="flex gap-3 rounded-xl border border-border bg-surface-card p-3"
            >
              <span
                className="shrink-0 w-7 h-7 rounded-full bg-primary-50 text-on text-xs font-medium flex items-center justify-center"
                aria-hidden="true"
              >
                {idx + 1}
              </span>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-on leading-snug">
                  {step.title}
                </p>
                {step.description && (
                  <p className="text-xs text-on-secondary mt-0.5 leading-snug">
                    {step.description}
                  </p>
                )}
              </div>
            </li>
          ))}
        </ol>
      ) : null;

    if (variant === "compact") {
      return (
        <Card
          ref={ref}
          className={cn("p-5 text-center", className)}
          data-testid="empty-state"
        >
          <div className="flex items-center gap-3 text-left">
            {Icon && (
              <div className="shrink-0 w-10 h-10 rounded-xl bg-surface-inset text-on-muted flex items-center justify-center">
                <Icon size={20} strokeWidth={1.75} />
              </div>
            )}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-on leading-tight">
                {title}
              </p>
              {description && (
                <p className="text-xs text-on-muted mt-0.5">{description}</p>
              )}
            </div>
            {primaryAction}
          </div>
        </Card>
      );
    }

    return (
      <Card
        ref={ref}
        className={cn(
          "p-10 text-center border-dashed",
          variant === "steps" && "p-8",
          className,
        )}
        data-testid="empty-state"
      >
        {iconWrap}
        {/* h2, not h3: an empty state stands in for the page's content, so it
            is the first level under the page title (UI_GUIDELINES §2.11). */}
        <h2
          className={cn(
            "font-semibold text-on leading-tight",
            variant === "steps" ? "text-base" : "text-lg",
          )}
        >
          {title}
        </h2>
        {description && (
          <p
            className={cn(
              "text-on-muted mx-auto leading-relaxed",
              variant === "steps"
                ? "text-xs mt-1 max-w-sm"
                : "text-sm mt-2 max-w-md",
            )}
          >
            {description}
          </p>
        )}
        {stepList}
        {actions}
      </Card>
    );
  },
);

EmptyState.displayName = "EmptyState";

export default EmptyState;

export function EmptyStateAction({
  label,
  onClick,
  variant = "primary",
  leftIcon: LeftIcon = ArrowRight,
}: {
  label: string;
  onClick?: () => void;
  /** The header owns the view's one filled action; an empty state sitting
   * under it carries the same entry as an outline instead of a second
   * filled button. */
  variant?: "primary" | "outline";
  leftIcon?: LucideIcon;
}) {
  const classes = cn(
    "inline-flex items-center justify-center gap-2 font-medium transition-all duration-200 active:scale-[0.98] select-none",
    "h-9 px-4 text-sm rounded-lg",
    variant === "outline"
      ? "border border-border bg-surface-card hover:bg-surface-raised text-on-secondary"
      : "bg-primary-700 dark:bg-primary-800 text-white hover:bg-primary-800 dark:hover:bg-primary-900 shadow-sm",
  );
  return (
    <button type="button" onClick={onClick} className={classes}>
      {LeftIcon && <LeftIcon size={16} />}
      {label}
    </button>
  );
}
