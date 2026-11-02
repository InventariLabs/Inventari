import * as React from "react";
import { cn } from "@/lib/utils";
import { RequiredStar } from "./fieldLabel";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
  description?: string;
  suffix?: string;
  wrapperClassName?: string;
  labelClassName?: string;
  /**
   * Requiredness. `required` keeps its native meaning — the browser
   * blocks submit and the star joins the label. Forms that validate inline
   * pass `aria-required` instead: same star and announcement, no browser
   * bubble hijacking their error flow. Never bake ` *` into the label string.
   */
  required?: boolean;
}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  (
    {
      className,
      type,
      label,
      error,
      leftIcon,
      rightIcon,
      description,
      suffix,
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
    // Required either natively or semantically (forms with their own inline
    // validation): both get the star and the announcement, only the former
    // the browser's submit blocking.
    const requiredMark =
      required || ariaRequired === true || ariaRequired === "true";
    // Callers rarely pass an id, and without one `htmlFor` pointed at nothing:
    // the label was on screen but missing from the accessibility tree.
    const generatedId = React.useId();
    const inputId = id ?? generatedId;
    // An error a screen reader cannot reach is not reported.
    // The message carries an id, the field points at it, and `role="alert"`
    // announces it when it appears — one mechanism for every form field.
    const errorId = `${inputId}-error`;
    const descriptionId = `${inputId}-description`;
    const describedByIds =
      [error ? errorId : null, description ? descriptionId : null, describedBy]
        .filter(Boolean)
        .join(" ") || undefined;

    return (
      <div className={cn("w-full space-y-1.5", wrapperClassName)}>
        {label && (
          <label
            htmlFor={inputId}
            className={cn(
              // `block`, not the inline default: an inline label sits in a line
              // box sized by the wrapper's inherited line-height, which pushed
              // the field ~8px lower than the `block`-labelled controls beside
              // it (DateInput, Select) in the same grid row.
              "block text-xs font-medium uppercase text-on-secondary ml-1 tracking-wide",
              labelClassName,
            )}
          >
            {label}
            {requiredMark && <RequiredStar />}
          </label>
        )}
        <div className="relative">
          {leftIcon && (
            <div className="absolute left-3 top-1/2 -translate-y-1/2 text-on-muted">
              {leftIcon}
            </div>
          )}
          <input
            id={inputId}
            type={type}
            required={required}
            aria-required={requiredMark || undefined}
            aria-invalid={error ? true : props["aria-invalid"]}
            aria-describedby={describedByIds}
            className={cn(
              // 44px touch target below `md:`, desktop density above it.
              "flex h-11 md:h-10 w-full rounded-lg border border-border bg-surface-card px-3 py-2 text-sm text-on placeholder:text-on-muted",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/20 focus-visible:border-primary-500",
              "transition-all duration-200",
              "disabled:opacity-50 disabled:cursor-not-allowed",
              type === "number" &&
                "[appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none",
              leftIcon && "pl-10",
              rightIcon && "pr-10",
              suffix && "pr-12",
              error &&
                "border-red-500 focus-visible:ring-red-500/20 focus-visible:border-red-500",
              className,
            )}
            ref={ref}
            {...props}
          />
          {rightIcon && (
            <div className="absolute right-3 top-1/2 -translate-y-1/2 text-on-muted">
              {rightIcon}
            </div>
          )}
          {suffix && (
            <div className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm text-on-muted">
              {suffix}
            </div>
          )}
        </div>
        {description && (
          <p id={descriptionId} className="text-xs text-on-muted ml-1">
            {description}
          </p>
        )}
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

Input.displayName = "Input";

export { Input };
