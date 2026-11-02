import * as React from "react";
import { cn } from "@/lib/utils";
import { RequiredStar } from "./fieldLabel";

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
  wrapperClassName?: string;
  labelClassName?: string;
}

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  (
    {
      className,
      label,
      error,
      wrapperClassName,
      labelClassName,
      id,
      required,
      "aria-required": ariaRequired,
      "aria-describedby": describedBy,
      ...props
    },
    ref,
  ) => {
    // See Input.tsx — required natively or via `aria-required` (inline-
    // validating forms); both get the star, only native blocks submit.
    const requiredMark =
      required || ariaRequired === true || ariaRequired === "true";
    // See Input.tsx — the label needs an id to point at, and callers rarely
    // supply one. The same file carries the error-reporting contract.
    const generatedId = React.useId();
    const textareaId = id ?? generatedId;
    const errorId = `${textareaId}-error`;
    const describedByIds =
      [error ? errorId : null, describedBy].filter(Boolean).join(" ") ||
      undefined;

    return (
      <div className={cn("w-full space-y-1.5", wrapperClassName)}>
        {label && (
          <label
            htmlFor={textareaId}
            className={cn(
              // See Input.tsx — `block` keeps the label out of an inherited
              // line box, so the field starts at the same height as its
              // neighbours.
              "block text-xs font-medium uppercase text-on-secondary ml-1 tracking-wide",
              labelClassName,
            )}
          >
            {label}
            {requiredMark && <RequiredStar />}
          </label>
        )}
        <textarea
          id={textareaId}
          required={required}
          aria-required={requiredMark || undefined}
          aria-invalid={error ? true : props["aria-invalid"]}
          aria-describedby={describedByIds}
          className={cn(
            "flex w-full rounded-lg border border-border bg-surface-card px-3 py-2 text-sm text-on placeholder:text-on-muted",
            "focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500",
            "transition-all duration-200",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            "min-h-24 resize-y",
            error &&
              "border-red-500 focus:ring-red-500/20 focus:border-red-500",
            className,
          )}
          ref={ref}
          {...props}
        />
        {error && (
          <p
            id={errorId}
            role="alert"
            className="text-xs text-red-600 font-medium ml-1"
          >
            {error}
          </p>
        )}
      </div>
    );
  },
);

Textarea.displayName = "Textarea";

export { Textarea };
