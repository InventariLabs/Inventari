import * as React from "react";
import { cn } from "@/lib/utils";
import { Button } from "./Button";
import { FIELD_LABEL_CLASS, RequiredStar } from "./fieldLabel";

export interface ChoiceOption {
  id: string;
  label: string;
  /**
   * One line saying what choosing this option means. For a choice between
   * two consequences a label alone cannot carry ("Different products" —
   * and then what?), the explanation belongs inside the option rather than
   * in a hint that reads over both.
   */
  description?: string;
  /** Classes for the chosen state, when this option tints differently. */
  selectedClassName?: string;
}

export interface ChoiceGroupProps {
  /** Names the whole group, the way a field label names one control. */
  label: string;
  /** Sits under the label, before the options — a sentence, not a tooltip. */
  hint?: string;
  options: ChoiceOption[];
  value: string;
  onChange: (id: string) => void;
  /**
   * Draws the star and announces the group as required. A `radiogroup` is one
   * of the roles `aria-required` is defined on, which is half the reason this
   * is a radio group and not a row of toggle buttons.
   */
  required?: boolean;
  /**
   * What is missing, once the form has been asked to save without an answer.
   *
   * A required group with no default is a dead end otherwise: the save button
   * greys out and nothing on the screen says which of six fields is the reason
   * — measured on the service-entry dialog, where Save stayed disabled with no
   * toast, no text and no `aria-invalid` anywhere.
   */
  error?: string;
  /**
   * `wrap` flows chips along the line; `grid` gives every option a column;
   * `grid2` is for a pair of options whose explanations need the width.
   */
  layout?: "wrap" | "grid" | "grid2";
  className?: string;
}

const SELECTED_DEFAULT =
  "border-primary-500 bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300";
const UNSELECTED = "border-border text-on-secondary hover:border-primary-400";

/**
 * A row of chips where exactly one is chosen.
 *
 * Three dialogs hand-rolled this: a `<label>` above a `<div>` of buttons. A
 * label can only name a form control, so it named nothing — a reader heard the
 * options with no idea what question they answered, and the chosen one was
 * distinguishable by colour alone. The group carries its own name here, and
 * every option says whether it is the chosen one.
 *
 * It is a `radiogroup`, not a `group` of toggle buttons. The difference is not
 * cosmetic: `role="group"` gives `aria-required` no defined meaning, so the
 * requiredness reached nobody who could not see a greyed-out button, and five
 * independent toggles were announced instead of "Type, required, 1 of 5".
 * With the role come the manners that go with it — arrow keys move the choice,
 * and the group holds a single tab stop rather than one per chip.
 *
 * One rule for every consumer, whichever way it goes: a required group is
 * never a dead end. It either arrives with a default — the way the return
 * dialog's condition does — or it says what is missing through `error`.
 */
export function ChoiceGroup({
  label,
  hint,
  options,
  value,
  onChange,
  required,
  error,
  layout = "wrap",
  className,
}: ChoiceGroupProps) {
  const labelId = React.useId();
  const errorId = React.useId();
  const groupRef = React.useRef<HTMLDivElement>(null);
  const chosenIndex = options.findIndex((option) => option.id === value);

  // Arrow keys move the choice, and moving it moves the focus with it — that
  // is what a radio group does, and what a row of buttons did not.
  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const step =
      e.key === "ArrowRight" || e.key === "ArrowDown"
        ? 1
        : e.key === "ArrowLeft" || e.key === "ArrowUp"
          ? -1
          : 0;
    if (step === 0 || options.length === 0) return;
    e.preventDefault();
    const from = chosenIndex === -1 ? (step > 0 ? -1 : 0) : chosenIndex;
    const next = (from + step + options.length) % options.length;
    onChange(options[next].id);
    const radios =
      groupRef.current?.querySelectorAll<HTMLButtonElement>('[role="radio"]');
    radios?.[next]?.focus();
  };

  return (
    <div className={cn("w-full space-y-1.5", className)}>
      <p id={labelId} className={FIELD_LABEL_CLASS}>
        {label}
        {required && <RequiredStar />}
      </p>
      {hint && <p className="text-xs text-on-muted ml-1">{hint}</p>}
      <div
        ref={groupRef}
        role="radiogroup"
        aria-labelledby={labelId}
        aria-required={required || undefined}
        aria-invalid={error ? true : undefined}
        aria-errormessage={error ? errorId : undefined}
        onKeyDown={handleKeyDown}
        className={cn(
          layout === "grid"
            ? "grid grid-cols-3 gap-2"
            : layout === "grid2"
              ? "grid grid-cols-1 sm:grid-cols-2 gap-2"
              : "flex flex-wrap gap-2",
        )}
      >
        {options.map((option, index) => {
          const chosen = option.id === value;
          return (
            <Button
              key={option.id}
              type="button"
              role="radio"
              size="content"
              variant="outline"
              aria-checked={chosen}
              // One tab stop for the group. With nothing chosen yet the first
              // option holds it, so Tab still reaches the question.
              tabIndex={chosen || (chosenIndex === -1 && index === 0) ? 0 : -1}
              onClick={() => onChange(option.id)}
              className={cn(
                // 44px on a phone, as a chip's `py-1` alone is 26.
                "min-h-11 transition-colors md:min-h-0",
                layout === "grid" || layout === "grid2"
                  ? "rounded-lg px-3 py-2 text-left"
                  : "rounded-full px-3 py-1",
                option.description
                  ? "flex-col items-start justify-start text-sm"
                  : "text-xs",
                chosen
                  ? (option.selectedClassName ?? SELECTED_DEFAULT)
                  : UNSELECTED,
              )}
            >
              <span className="block font-medium">{option.label}</span>
              {option.description && (
                <span className="mt-0.5 block text-xs font-normal opacity-80">
                  {option.description}
                </span>
              )}
            </Button>
          );
        })}
      </div>
      {error && (
        <p id={errorId} role="alert" className="text-xs text-on-danger">
          {error}
        </p>
      )}
    </div>
  );
}
