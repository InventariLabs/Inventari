import * as React from "react";
import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { DynamicIcon } from "./DynamicIcon";
import { RequiredStar } from "./fieldLabel";

export interface SelectOption {
  id: string;
  name: string;
  icon?: string;
  color?: string;
}

const SelectGroup = SelectPrimitive.Group;
const SelectLabel = SelectPrimitive.Label;
const SelectSeparator = SelectPrimitive.Separator;

const SelectContent = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Portal>
    <SelectPrimitive.Content
      ref={ref}
      className={cn(
        "relative z-[var(--z-confirm)] max-h-96 min-w-[8rem] overflow-hidden rounded-xl border border-border bg-surface-card text-on shadow-lg",
        "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2",
        className,
      )}
      {...props}
    >
      <SelectPrimitive.Viewport className="p-1">
        {children}
      </SelectPrimitive.Viewport>
    </SelectPrimitive.Content>
  </SelectPrimitive.Portal>
));
SelectContent.displayName = SelectPrimitive.Content.displayName;

const SelectItem = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item> & {
    icon?: string;
  }
>(({ className, children, icon, ...props }, ref) => (
  <SelectPrimitive.Item
    ref={ref}
    className={cn(
      "relative flex w-full cursor-pointer select-none items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium outline-none",
      // Checked row: brand tint, neutral label (see UI_GUIDELINES §1.1) — the
      // `dark:text-primary-300` override resolved to a dark teal on a dark
      // popover for the default palette and to the profile's own dark step for
      // a repainted one.
      "focus:bg-surface-raised data-[state=checked]:bg-primary-50 data-[state=checked]:text-on data-[state=checked]:font-semibold",
      "data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
      className,
    )}
    {...props}
  >
    {icon && (
      <div className="w-7 h-7 rounded-md flex items-center justify-center shrink-0 bg-surface-inset text-on-muted">
        <DynamicIcon name={icon} size={16} strokeWidth={2.5} />
      </div>
    )}
    <span className="flex-1 truncate">
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    </span>
    <SelectPrimitive.ItemIndicator>
      {/* `primary-600` carries in both themes (≥3:1, the graphics threshold);
          the `dark:` override pointed at a step that flips to a dark tint. */}
      <Check size={14} className="shrink-0 text-primary-600" />
    </SelectPrimitive.ItemIndicator>
  </SelectPrimitive.Item>
));
SelectItem.displayName = SelectPrimitive.Item.displayName;

interface SimpleSelectProps {
  options: SelectOption[];
  value: string;
  onChange: (id: string) => void;
  placeholder?: string;
  error?: string;
  className?: string;
  size?: "sm" | "default";
  /**
   * Renders the field label in the shared wrapper, the way Input and
   * NativeSelect do. A hand-rolled `<label>` next to the trigger is what
   * produced 0px label-to-field gaps on several forms — the wrapper owns
   * that spacing so every control keeps the same vertical rhythm.
   */
  label?: string;
  /**
   * Marks the field required: an aria-hidden star joins the label and
   * `aria-required` carries the state on the trigger. No native
   * `required` here — the control is a button, not a form input.
   */
  required?: boolean;
  /**
   * The name for a trigger that has no visible `label` of its own — a filter
   * on a control bar, where the words beside it belong to the row rather than
   * to this control. Without it the trigger is announced as its current
   * value: "All locations", with nothing saying what is all locations.
   */
  "aria-label"?: string;
  wrapperClassName?: string;
  labelClassName?: string;
  id?: string;
}

const SimpleSelect = React.forwardRef<HTMLButtonElement, SimpleSelectProps>(
  (
    {
      options,
      value,
      onChange,
      placeholder,
      error,
      className,
      size = "default",
      label,
      required,
      "aria-label": ariaLabel,
      wrapperClassName,
      labelClassName,
      id,
    },
    ref,
  ) => {
    // pattern: an English literal in a default parameter shows up in
    // every language. The caller can still pass its own placeholder.
    const { t } = useTranslation("common");
    const placeholderText = placeholder ?? t("actions.select");
    // See Input.tsx — the label needs an id to point at, and callers rarely
    // supply one.
    const generatedId = React.useId();
    const triggerId = id ?? generatedId;
    const select = (
      <SelectPrimitive.Root value={value} onValueChange={onChange}>
        <SelectPrimitive.Trigger
          ref={ref}
          id={triggerId}
          aria-label={ariaLabel}
          aria-required={required || undefined}
          className={cn(
            // One control scale (UI_GUIDELINES §2.10): same height, radius and
            // border weight as Input/NativeSelect/DateInput. This trigger used
            // to be 12px-round with a 2px border next to 8px/1px selects in the
            // same dialog.
            "flex w-full items-center justify-between gap-3 rounded-lg border bg-surface-card text-sm font-semibold",
            "focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500",
            "data-[placeholder]:text-on-secondary",
            "disabled:cursor-not-allowed disabled:opacity-50",
            size === "sm" ? "h-9 px-3 text-xs" : "h-11 md:h-10 px-3",
            // Filled is not a state (§2.10): the border and background stay
            // neutral whether or not a value is selected; the placeholder
            // is muted via data-[placeholder] above.
            error ? "border-red-500 text-on" : "border-border text-on",
            className,
          )}
        >
          <SelectPrimitive.Value placeholder={placeholderText} />
          {error && (
            <span className="text-xs text-red-600 font-medium">{error}</span>
          )}
          <ChevronDown size={18} className="shrink-0 text-on-muted" />
        </SelectPrimitive.Trigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.id} value={option.id} icon={option.icon}>
              {option.name}
            </SelectItem>
          ))}
        </SelectContent>
      </SelectPrimitive.Root>
    );

    // The box is always here, labelled or not — `wrapperClassName` must land
    // somewhere on every call site. When the wrapper appeared only with a
    // label, the prop was accepted, type-checked and silently thrown away on
    // every other call site, which is the worst of the three. `NativeSelect`
    // already fixed and documented the same shape; this is now its twin.
    return (
      <div className={cn("w-full space-y-1.5", wrapperClassName)}>
        {label && (
          <label
            htmlFor={triggerId}
            className={cn(
              "text-xs font-medium uppercase text-on-secondary ml-1 tracking-wide block",
              labelClassName,
            )}
          >
            {label}
            {required && <RequiredStar />}
          </label>
        )}
        {select}
      </div>
    );
  },
);
SimpleSelect.displayName = "SimpleSelect";

const Select = SimpleSelect;

export {
  Select,
  SelectGroup,
  SelectLabel,
  SelectSeparator,
  SelectContent,
  SelectItem,
};
