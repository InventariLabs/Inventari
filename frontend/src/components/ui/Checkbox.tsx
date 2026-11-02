import * as React from "react";
import { cn } from "@/lib/utils";

export interface CheckboxProps extends Omit<
  React.InputHTMLAttributes<HTMLInputElement>,
  "type"
> {
  label?: React.ReactNode;
  indeterminate?: boolean;
  /**
   * A bare checkbox is 16×16; on a phone that is below the 44px floor. This
   * wraps it in a label that is 44×44 below `md:` — the whole square toggles
   * it — and drops back to the box itself above, so the desktop layout and
   * its row heights do not move. Ignored when `label` already wraps it.
   */
  touchTarget?: boolean;
}

const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, label, indeterminate, touchTarget, id, ...props }, ref) => {
    const localRef = React.useRef<HTMLInputElement>(null);
    const generatedId = React.useId();
    // The touch-target label points at its box by id, so the pair is wired
    // even where the caller gave none.
    const inputId = id ?? (touchTarget ? generatedId : undefined);

    React.useImperativeHandle(ref, () => localRef.current!);

    React.useEffect(() => {
      if (localRef.current) {
        localRef.current.indeterminate = !!indeterminate;
      }
    }, [indeterminate]);

    const checkbox = (
      <input
        type="checkbox"
        id={inputId}
        ref={localRef}
        className={cn(
          "h-4 w-4 rounded border-border text-primary-600 focus:ring-primary-500 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed transition-all",
          className,
        )}
        {...props}
      />
    );

    if (label) {
      return (
        <label
          htmlFor={id}
          className={cn(
            "flex items-center gap-2 cursor-pointer select-none",
            props.disabled && "cursor-not-allowed opacity-50",
          )}
        >
          {checkbox}
          {typeof label === "string" ? (
            <span className="text-sm text-on-secondary">{label}</span>
          ) : (
            label
          )}
        </label>
      );
    }

    if (touchTarget) {
      return (
        <label
          htmlFor={inputId}
          className={cn(
            "inline-flex min-h-11 min-w-11 cursor-pointer items-center justify-center md:min-h-0 md:min-w-0",
            props.disabled && "cursor-not-allowed",
          )}
        >
          {checkbox}
        </label>
      );
    }

    return checkbox;
  },
);

Checkbox.displayName = "Checkbox";

export { Checkbox };
