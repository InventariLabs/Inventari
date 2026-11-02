import React from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { RequiredStar } from "./fieldLabel";

export interface NativeSelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
  /** Field hint under the control, wired to the select through
   *  `aria-describedby` — the same contract `Input.description` has. */
  description?: string;
  wrapperClassName?: string;
  labelClassName?: string;
}

const NativeSelect = React.forwardRef<HTMLSelectElement, NativeSelectProps>(
  (
    {
      className,
      label,
      error,
      description,
      children,
      wrapperClassName,
      labelClassName,
      id,
      required,
      "aria-required": ariaRequired,
      "aria-describedby": describedBy,
      "aria-invalid": ariaInvalid,
      ...props
    },
    ref,
  ) => {
    // See Input.tsx — required natively or via `aria-required` (inline-
    // validating forms); both get the star, only native blocks submit.
    const requiredMark =
      required || ariaRequired === true || ariaRequired === "true";
    // See Input.tsx — the label needs an id to point at, and callers rarely
    // supply one.
    const generatedId = React.useId();
    const selectId = id ?? generatedId;
    // See Input.tsx — a hint a screen reader cannot reach is decoration,
    // not documentation: the select points at it through aria-describedby.
    const descriptionId = `${selectId}-description`;
    // See Input.tsx — an error a screen reader cannot reach is not reported:
    // the message carries an id, the select points at it and says it is
    // invalid.
    const errorId = `${selectId}-error`;
    const describedByIds =
      [error ? errorId : null, description ? descriptionId : null, describedBy]
        .filter(Boolean)
        .join(" ") || undefined;

    // The chevron is drawn here rather than left to the platform. A bare
    // `<select>` renders whatever arrow the OS and browser agree on, so the
    // same form showed three different disclosure indicators side by side —
    // a system arrow, `Select`'s lucide chevron and `FieldBuilder`'s. Only the
    // *indicator* is ours: the control stays a native `<select>`, so a phone
    // still opens the system picker (UI_GUIDELINES §2.10).
    const select = (
      <div className="relative">
        <select
          id={selectId}
          required={required}
          aria-required={requiredMark || undefined}
          aria-invalid={error ? true : ariaInvalid}
          aria-describedby={describedByIds}
          className={cn(
            // 44px touch target below `md:`, desktop density above it.
            "w-full h-11 md:h-10 pl-3 pr-10 rounded-lg",
            "appearance-none",
            "border border-border bg-surface-card",
            "text-sm text-on",
            "focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500",
            "transition-all duration-200",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            "dark:[color-scheme:dark]",
            error &&
              "border-red-500 focus:ring-red-500/20 focus:border-red-500",
            className,
          )}
          ref={ref}
          {...props}
        >
          {children}
        </select>
        <ChevronDown
          size={18}
          aria-hidden="true"
          className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 shrink-0 text-on-muted"
        />
      </div>
    );

    // The box is always here, labelled or not. When it appeared only with a
    // label, `wrapperClassName` was silently dropped on every other call site
    // — the prop was accepted, type-checked, and thrown away, which is the
    // worst of the three. `Input`, `Textarea` and `Select` never had the
    // conditional; this one is now the same shape as its siblings.
    return (
      <div className={cn("w-full space-y-1.5", wrapperClassName)}>
        {label && (
          <label
            htmlFor={selectId}
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
        {select}
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

NativeSelect.displayName = "NativeSelect";

export { NativeSelect };
