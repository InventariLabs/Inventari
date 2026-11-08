import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { Calendar, X } from "lucide-react";
import {
  addDays,
  addMonths,
  addWeeks,
  addYears,
  endOfMonth,
  format,
  isSameDay,
  isSameMonth,
  isValid,
  parseISO,
  startOfMonth,
  startOfWeek,
} from "date-fns";
import { cn } from "@/lib/utils";
import { DateInputNav } from "./DateInputNav";
import { RequiredStar } from "./fieldLabel";
import { Button } from "@/components/ui/Button";
import {
  Sheet,
  SheetBody,
  SheetHeader,
  Z_TIER_TO_VAR,
  type SheetZTier,
} from "@/components/ui/Sheet";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { formatDate, formatLocale } from "@/utils/formatters";

/**
 * The date field for the whole app.
 *
 * It replaces `input[type=date]`, which formatted itself from the browser's
 * locale while the rest of the UI used the app's, forced a light colour
 * scheme, and offered the same three shortcuts to every field regardless of
 * what the date meant.
 *
 * Panel placement follows UI_GUIDELINES §4.3: a popover on desktop, a sheet
 * from the bottom on phones.
 */

/**
 * Relative jumps a field can offer. Which ones appear is the field's call —
 * an expiry date thinks in "in a month", a purchase date does not.
 *
 * A shortcut earns its place in the bar only if the date it sets lies outside
 * the month grid the panel opens on, or if it is the overwhelmingly common
 * value for that field. "Today" and "yesterday" are already one click away on
 * the open grid, so a button for them saves nothing and implies they are what
 * the field usually holds. See UI_GUIDELINES §2.8.
 */
export type DatePresetId =
  | "today"
  | "yesterday"
  | "plus1Week"
  | "plus2Weeks"
  | "plus1Month"
  | "plus3Months"
  | "plus6Months"
  | "plus1Year"
  | "plus2Years"
  | "plus3Years"
  | "minus1Week"
  | "minus1Month";

const PRESET_OFFSETS: Record<DatePresetId, (from: Date) => Date> = {
  today: (d) => d,
  yesterday: (d) => addDays(d, -1),
  plus1Week: (d) => addWeeks(d, 1),
  plus2Weeks: (d) => addWeeks(d, 2),
  plus1Month: (d) => addMonths(d, 1),
  plus3Months: (d) => addMonths(d, 3),
  plus6Months: (d) => addMonths(d, 6),
  plus1Year: (d) => addYears(d, 1),
  plus2Years: (d) => addYears(d, 2),
  plus3Years: (d) => addYears(d, 3),
  minus1Week: (d) => addWeeks(d, -1),
  minus1Month: (d) => addMonths(d, -1),
};

const VALUE_FORMAT = "yyyy-MM-dd";

/**
 * The tier the calendar opens on, as a popover or as a phone's sheet: the
 * one `Select` and `SearchableCombobox` use (UI_GUIDELINES §4.1). On the
 * standard modal tier it opened behind any nested sheet that held the
 * field — the lot-and-expiry question among them — painted under the
 * backdrop, so a click on a day landed on the backdrop and closed the
 * question.
 */
const PANEL_LAYER = "confirm" satisfies SheetZTier;

interface DateInputProps {
  /** ISO date (`yyyy-MM-dd`), or "" for no date. */
  value: string;
  onChange: (value: string) => void;
  presets?: DatePresetId[];
  /** Rendered above the trigger, matching the `Input` component's label. */
  label?: string;
  placeholder?: string;
  error?: string;
  disabled?: boolean;
  required?: boolean;
  /** Earliest / latest selectable date, ISO (`yyyy-MM-dd`). */
  min?: string;
  max?: string;
  className?: string;
  /**
   * Classes for the box the field occupies — width, its share of a row, the
   * space around it. `className` describes the trigger itself.
   */
  wrapperClassName?: string;
  id?: string;
  "aria-label"?: string;
}

function parseValue(value: string): Date | null {
  if (!value) return null;
  const parsed = parseISO(value);
  return isValid(parsed) ? parsed : null;
}

/** Today in the user's own timezone. `toISOString()` would answer with UTC,
 * which is yesterday for anyone east of Greenwich after midnight. */
function today(): Date {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

export function DateInput({
  value,
  onChange,
  presets = [],
  label,
  placeholder,
  error,
  disabled,
  required,
  min,
  max,
  className,
  wrapperClassName,
  id,
  "aria-label": ariaLabel,
}: DateInputProps) {
  const { t } = useTranslation(["common"]);
  const isDesktop = useMediaQuery("(min-width: 640px)");
  const [open, setOpen] = useState(false);
  // See Input.tsx — without an id the `htmlFor` pointed at nothing, so the
  // label was on screen but missing from the accessibility tree.
  const generatedId = useId();
  const triggerId = id ?? generatedId;
  const panelId = `${triggerId}-panel`;
  const errorId = `${triggerId}-error`;

  const selected = parseValue(value);
  const [focusedDay, setFocusedDay] = useState<Date>(selected ?? today());
  const gridRef = useRef<HTMLDivElement>(null);

  // Reopening on a different value should start where that value is, and the
  // keyboard belongs in the grid: opening left focus on the first preset
  // button, where the arrow keys do nothing.
  useEffect(() => {
    if (!open) return;
    setFocusedDay(parseValue(value) ?? today());
    gridRef.current?.focus();
  }, [open, value]);

  const locale = formatLocale();

  // The same numeric day every other screen prints — the picker used to
  // spell it as "25 lis 2026" beside "30.11.2026" on the page behind it.
  const formatted = selected ? formatDate(value) : "";

  const monthLabel = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, {
        month: "long",
        year: "numeric",
      }).format(focusedDay),
    [focusedDay, locale],
  );

  const weekdayLabels = useMemo(() => {
    const formatter = new Intl.DateTimeFormat(locale, { weekday: "short" });
    const firstDay = startOfWeek(focusedDay, { weekStartsOn: 1 });
    return Array.from({ length: 7 }, (_, i) =>
      formatter.format(addDays(firstDay, i)),
    );
  }, [focusedDay, locale]);

  const days = useMemo(() => {
    const gridStart = startOfWeek(startOfMonth(focusedDay), {
      weekStartsOn: 1,
    });
    const cells = 42; // six weeks, so the panel never changes height
    return Array.from({ length: cells }, (_, i) => addDays(gridStart, i));
  }, [focusedDay]);

  const outOfRange = (date: Date) => {
    const iso = format(date, VALUE_FORMAT);
    return Boolean((min && iso < min) || (max && iso > max));
  };

  const commit = (date: Date) => {
    if (outOfRange(date)) return;
    onChange(format(date, VALUE_FORMAT));
    setOpen(false);
  };

  const handleGridKeyDown = (e: React.KeyboardEvent) => {
    const moves: Record<string, () => Date> = {
      ArrowLeft: () => addDays(focusedDay, -1),
      ArrowRight: () => addDays(focusedDay, 1),
      ArrowUp: () => addDays(focusedDay, -7),
      ArrowDown: () => addDays(focusedDay, 7),
      PageUp: () => addMonths(focusedDay, -1),
      PageDown: () => addMonths(focusedDay, 1),
      Home: () => startOfMonth(focusedDay),
      End: () => endOfMonth(focusedDay),
    };

    const move = moves[e.key];
    if (move) {
      e.preventDefault();
      setFocusedDay(move());
      return;
    }

    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      commit(focusedDay);
    }
  };

  const panel = (
    <div
      className="p-4 space-y-4"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          setOpen(false);
        }
      }}
    >
      {presets.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {presets.map((preset) => (
            <Button
              key={preset}
              type="button"
              variant="outline"
              size="sm"
              data-testid="date-preset"
              disabled={outOfRange(PRESET_OFFSETS[preset](today()))}
              onClick={() => commit(PRESET_OFFSETS[preset](today()))}
              className="text-xs font-medium"
            >
              {t(`common:datePresets.${preset}`)}
            </Button>
          ))}
        </div>
      )}

      <DateInputNav
        monthLabel={monthLabel}
        onStep={(months) => setFocusedDay(addMonths(focusedDay, months))}
        onStepYear={(years) => setFocusedDay(addYears(focusedDay, years))}
      />

      <div
        ref={gridRef}
        role="grid"
        aria-label={monthLabel}
        tabIndex={0}
        onKeyDown={handleGridKeyDown}
        className="focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400 rounded-lg"
      >
        <div className="grid grid-cols-7 mb-1">
          {weekdayLabels.map((weekday) => (
            <span
              key={weekday}
              className="text-[10px] font-medium uppercase text-on-secondary text-center py-1"
            >
              {weekday}
            </span>
          ))}
        </div>
        <div className="grid grid-cols-7 gap-0.5">
          {days.map((day) => {
            const disabledDay = outOfRange(day);
            const isSelected = selected ? isSameDay(day, selected) : false;
            const isFocused = isSameDay(day, focusedDay);
            const isToday = isSameDay(day, today());
            const outside = !isSameMonth(day, focusedDay);

            return (
              <button
                key={day.toISOString()}
                type="button"
                // 44px keeps the tap target within reach on a phone.
                className={cn(
                  "h-11 w-full rounded-lg text-sm font-medium tabular-nums transition-colors",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400",
                  outside ? "text-on-muted" : "text-on",
                  disabledDay && "opacity-40 cursor-not-allowed",
                  isToday && !isSelected && "ring-1 ring-primary-300",
                  isSelected
                    ? "bg-primary-700 text-white hover:bg-primary-800 dark:bg-primary-800 dark:hover:bg-primary-900"
                    : "hover:bg-surface-raised",
                  isFocused && !isSelected && "bg-surface-raised",
                )}
                aria-selected={isSelected}
                // Today is marked with a ring; without this it is announced
                // like any other day, and there is no shortcut bar to fall
                // back on now that the grid already shows it.
                aria-current={isToday ? "date" : undefined}
                disabled={disabledDay}
                aria-label={new Intl.DateTimeFormat(locale, {
                  dateStyle: "long",
                }).format(day)}
                onClick={() => commit(day)}
              >
                {day.getDate()}
              </button>
            );
          })}
        </div>
      </div>

      {value && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => {
            onChange("");
            setOpen(false);
          }}
          className="w-full text-xs font-medium text-on-secondary"
          leftIcon={<X size={14} />}
        >
          {t("common:actions.clear")}
        </Button>
      )}
    </div>
  );

  const triggerButton = (
    <button
      type="button"
      // The role that carries `aria-required` and `aria-expanded`: on a plain
      // button axe reports the first as not allowed, and readers drop it.
      // The field's label names it, wired by `htmlFor` or wrapped around it.
      role="combobox"
      id={triggerId}
      disabled={disabled}
      aria-haspopup="dialog"
      aria-expanded={open}
      // A combobox names the popup it opens. Ours, not Radix's id, so the
      // sheet below `sm:` carries the same one.
      aria-controls={panelId}
      aria-label={ariaLabel}
      aria-required={required}
      aria-invalid={error ? true : undefined}
      aria-describedby={error ? errorId : undefined}
      onClick={() => setOpen((o) => !o)}
      className={cn(
        // One control scale (UI_GUIDELINES §2.10) — this trigger was 44px tall
        // with a 12px radius next to 40px/8px selects in the same dialog.
        "flex items-center w-full h-11 md:h-10 px-3 rounded-lg border bg-surface-card text-left",
        "focus:outline-none focus-visible:border-primary-400 focus-visible:ring-2 focus-visible:ring-primary-400/20 transition-all",
        error ? "border-red-500" : "border-border",
        disabled && "opacity-50 cursor-not-allowed",
        className,
      )}
    >
      <Calendar size={15} className="text-on-muted shrink-0 mr-2.5" />
      <span
        className={cn(
          "flex-1 min-w-0 truncate text-sm font-medium",
          formatted ? "text-on" : "text-on-muted",
        )}
      >
        {formatted || placeholder || t("common:datePicker.empty")}
      </span>
    </button>
  );

  // The box is always there, labelled or not — the same shape `Input`,
  // `Textarea`, `Select` and `NativeSelect` render, so a caller sizing a date
  // field sizes it the same way it sizes any other field.
  const field = (control: React.ReactNode) => (
    <div className={cn("w-full space-y-1.5", wrapperClassName)}>
      {label && (
        <label
          htmlFor={triggerId}
          className="text-xs font-medium uppercase text-on-secondary ml-1 tracking-wide block"
        >
          {label}
          {required && <RequiredStar />}
        </label>
      )}
      {control}
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

  if (!isDesktop) {
    return (
      <>
        {field(triggerButton)}
        {open && (
          <Sheet
            open
            onClose={() => setOpen(false)}
            aria-label={t("common:datePicker.label")}
            id={panelId}
            zIndex={PANEL_LAYER}
          >
            {/* The sheet had no header: nothing on it said who opened it and
                nothing on it closed it, so a reader who opened a date field by
                mistake had Escape or a background tap and no way to see either.
                Every other sheet in the app carries this row. */}
            <SheetHeader
              title={t("common:datePicker.label")}
              onClose={() => setOpen(false)}
            />
            <SheetBody>{panel}</SheetBody>
          </Sheet>
        )}
      </>
    );
  }

  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
      {/* The button, not the field around it: the trigger props Radix adds
          (`aria-expanded` among them) belong on the element they describe. */}
      {field(
        <PopoverPrimitive.Trigger asChild>
          {triggerButton}
        </PopoverPrimitive.Trigger>,
      )}
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          id={panelId}
          role="dialog"
          aria-label={t("common:datePicker.label")}
          align="start"
          sideOffset={6}
          collisionPadding={8}
          // Radix flips the panel to the side with more room, but a panel
          // taller than that room still ran off the screen: at 1280x577 its
          // top sat 48px above the window and the shortcut row was cut off with
          // no way to scroll to it. It now takes the room there is, and
          // scrolls inside it.
          className="w-[20rem] max-h-[var(--radix-popover-content-available-height)] overflow-y-auto rounded-2xl border border-border bg-surface-card shadow-lg"
          style={{ zIndex: Z_TIER_TO_VAR[PANEL_LAYER] }}
        >
          {panel}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
