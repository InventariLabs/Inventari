import * as React from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { Check, Plus, Search, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { Badge } from "./Badge";
import { DynamicIcon } from "./DynamicIcon";
import { Sheet, type SheetZTier } from "./Sheet";
import { RequiredStar } from "./fieldLabel";

const LAYER_TO_CLASS: Record<SheetZTier, string> = {
  modal: "z-[var(--z-modal)]",
  "modal-nested": "z-[var(--z-modal-nested)]",
  confirm: "z-[var(--z-confirm)]",
  fullscreen: "z-[var(--z-fullscreen)]",
};

interface ComboboxOption {
  id: string;
  name: string;
  icon?: string;
  color?: string;
  /** Optional breadcrumb path shown under the name, e.g. "Workstations / Floor 1 - Row A". */
  path?: string;
  /**
   * Optional tag pill beside the name — e.g. which module a location belongs
   * to when the picker offers module-owned locations.
   */
  badge?: string;
}

export interface SearchableComboboxProps {
  options: ComboboxOption[];
  value: string;
  onChange: (id: string) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  /**
   * What the dropdown says when it has no options. A node, not a string:
   * the honest answer is sometimes longer than a sentence and carries the
   * way out — a link to the setting that is hiding the options.
   */
  emptyMessage?: React.ReactNode;
  createLabel?: string;
  /**
   * The options are still on their way. An empty list is then not an answer:
   * the panel says it is loading, and offers no "create new" door — the one
   * it would offer is for a record the list may be about to show.
   */
  loading?: boolean;
  title?: string;
  /**
   * The caller's own trigger, in place of the field. One element that takes
   * a ref and spreads props — a `Button` — because on desktop the popover
   * stamps its trigger props (`aria-expanded` among them) on this element
   * itself, not on a wrapper that may not carry them.
   */
  trigger?: React.ReactElement;
  onClose?: () => void;
  onCreateNew?: (query: string) => void;
  /**
   * Hands the typed query to the caller, who looks it up on the server. The
   * options are then taken as the answer to that query and not narrowed again
   * here: a list too long to load whole cannot be filtered by the browser.
   * Called with "" when the panel closes. While `loading` is set, Enter does
   * not pick — the first row may belong to the previous query.
   */
  onSearchChange?: (query: string) => void;
  /**
   * Validation message. Same contract as Input and Textarea: the trigger
   * gets aria-invalid and points at the message, which announces itself.
   */
  error?: string;
  /** Set on the trigger so a form can move focus to the first bad field. */
  id?: string;
  /**
   * Whether "none of these" is an answer the reader is allowed to give.
   *
   * Off by default: on a required field an empty value is not a state the
   * form can be saved in. Where the field is optional, leaving it out has to
   * be reachable — without it the only move on a picker is swapping one value
   * for another, and a category assigned by accident stays on the record for
   * good.
   */
  clearable?: boolean;
  /** What choosing nothing is called here, e.g. "No category". */
  clearLabel?: string;
  /** Visible label above the trigger, wired via htmlFor/id. Mirrors Input. */
  label?: string;
  /**
   * Marks the field required: an aria-hidden star joins the label and
   * `aria-required` carries the state on the trigger. No native
   * `required` here — the control is a button, not a form input; its role
   * is `combobox`, the one `aria-required` means something on.
   */
  required?: boolean;
  labelClassName?: string;
  wrapperClassName?: string;
  /**
   * The tier of the surface this picker was opened from.
   *
   * A picker paints above ordinary dialogs by default, which is enough almost
   * everywhere. It is not enough inside a fullscreen one: the panel then opens
   * *behind* the form that owns it, and the reader sees a list they cannot
   * reach. Name the owner's tier and the panel joins it — same rule as
   * `ActionMenu`'s `layer`.
   */
  layer?: SheetZTier;
  /** The trigger cannot be opened — a field the reader may not change. */
  disabled?: boolean;
  /** Names the trigger when the field has no visible label (a cell in a row). */
  "aria-label"?: string;
}

/**
 * "None of these", as a row in the list rather than a control beside it.
 *
 * In the list because that is where the other answers are, and because it
 * then works the same in the popover and in the sheet below `sm:` — a small
 * ✕ on the trigger would have to be built twice and would sit inside a touch
 * target that already means "open the list".
 */
const ClearOption: React.FC<{
  shown: boolean;
  label?: string;
  onSelect: () => void;
}> = ({ shown, label, onSelect }) => {
  const { t } = useTranslation("common");
  if (!shown) return null;
  return (
    <button
      type="button"
      onClick={onSelect}
      className="w-full flex items-center gap-3 p-2.5 mb-0.5 rounded-lg hover:bg-surface-raised text-on-secondary transition-all text-left"
    >
      <div className="w-8 h-8 rounded-md bg-surface-inset text-on-muted flex items-center justify-center shrink-0">
        <X size={16} strokeWidth={2} />
      </div>
      <span className="flex-1 min-w-0 font-medium text-sm truncate">
        {label ?? t("actions.clear")}
      </span>
    </button>
  );
};

interface ComboboxPanelProps {
  titleId: string;
  title?: string;
  searchQuery: string;
  setSearchQuery: (q: string) => void;
  searchPlaceholder?: string;
  visibleOptions: ComboboxOption[];
  value: string;
  emptyMessage?: React.ReactNode;
  clearable?: boolean;
  clearLabel?: string;
  handleSelect: (id: string) => void;
  handleOpenChange: (next: boolean) => void;
  /**
   * Closes without the `onClose` callback — what "create new" has always
   * done, unlike the X in the header, which reports the close.
   */
  setOpen: (next: boolean) => void;
  onCreateNew?: (query: string) => void;
  createLabel?: string;
  loading?: boolean;
}

/**
 * Header, search and list — one markup for both branches, so the popover and
 * the sheet cannot drift apart.
 *
 * Its own component because the control around it holds the open/closed
 * plumbing and the trigger, and the two together ran past what the lint
 * budget calls one job.
 */
const ComboboxPanel: React.FC<ComboboxPanelProps> = ({
  titleId,
  title,
  searchQuery,
  setSearchQuery,
  searchPlaceholder,
  visibleOptions,
  value,
  emptyMessage,
  clearable,
  clearLabel,
  handleSelect,
  handleOpenChange,
  setOpen,
  onCreateNew,
  createLabel,
  loading,
}) => {
  const { t } = useTranslation("common");
  const waiting = Boolean(loading) && visibleOptions.length === 0;
  return (
    <>
      <div className="flex items-center justify-between p-3 border-b border-border shrink-0">
        <h3 id={titleId} className="text-base font-semibold text-on">
          {title}
        </h3>
        <button
          type="button"
          aria-label={t("a11y.close")}
          onClick={() => handleOpenChange(false)}
          className="w-7 h-7 rounded-full hover:bg-surface-raised flex items-center justify-center text-on-muted hover:text-on-secondary transition-colors"
        >
          <X size={16} />
        </button>
      </div>

      <div className="p-3 border-b border-border shrink-0">
        <div className="relative">
          <Search
            className="absolute left-3 top-1/2 -translate-y-1/2 text-on-muted"
            size={16}
          />
          <input
            type="text"
            aria-label={searchPlaceholder ?? t("common:actions.search")}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => {
              // The sheet renders inside the form it belongs to, so a bare
              // Enter here would submit that form with the field still
              // unanswered. Enter takes the first match instead — what the
              // phone keyboard's "Go" key is asking for anyway.
              if (e.key !== "Enter") return;
              e.preventDefault();
              if (!loading && visibleOptions.length > 0)
                handleSelect(visibleOptions[0].id);
            }}
            placeholder={searchPlaceholder}
            className="w-full h-11 md:h-10 pl-9 pr-9 bg-surface border border-border rounded-lg outline-none focus:border-primary-500 focus:bg-surface-card transition-all text-sm"
            autoFocus
          />
          {searchQuery && (
            <button
              type="button"
              aria-label={t("actions.clear")}
              onClick={() => setSearchQuery("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-on-muted hover:text-on-secondary"
            >
              <X size={14} />
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-1">
        <ClearOption
          shown={Boolean(clearable) && Boolean(value)}
          label={clearLabel}
          onSelect={() => handleSelect("")}
        />
        {waiting ? (
          <div className="py-10 text-center">
            <p className="text-sm text-on-muted font-medium">
              {t("messages.loading")}
            </p>
          </div>
        ) : visibleOptions.length === 0 ? (
          <div className="py-10 text-center">
            <p className="text-sm text-on-muted font-medium">{emptyMessage}</p>
          </div>
        ) : (
          <div className="space-y-0.5">
            {visibleOptions.map((option) => {
              const isSelected = option.id === value;
              return (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => handleSelect(option.id)}
                  title={option.name}
                  className={cn(
                    "w-full flex items-center gap-3 p-2.5 rounded-lg transition-all text-left",
                    // Selected row: brand tint, neutral label
                    // (UI_GUIDELINES §1.1).
                    isSelected
                      ? "bg-primary-50 text-on font-semibold"
                      : "hover:bg-surface-raised text-on-secondary",
                  )}
                >
                  {option.icon && (
                    <div
                      className={cn(
                        "w-8 h-8 rounded-md flex items-center justify-center shrink-0",
                        isSelected
                          ? "bg-primary-50 text-primary-700 dark:bg-primary-500/15 dark:text-primary-500"
                          : "bg-surface-inset text-on-muted",
                      )}
                    >
                      <DynamicIcon
                        name={option.icon}
                        size={16}
                        strokeWidth={2}
                      />
                    </div>
                  )}
                  <span className="flex-1 min-w-0">
                    <span className="block font-medium text-sm truncate">
                      {option.name}
                    </span>
                    {option.path && (
                      <span className="block text-xs text-on-muted truncate">
                        {option.path}
                      </span>
                    )}
                  </span>
                  {option.badge && (
                    <Badge variant="secondary" className="shrink-0">
                      {option.badge}
                    </Badge>
                  )}
                  {isSelected && (
                    <Check
                      size={16}
                      className="shrink-0 text-primary-600"
                      strokeWidth={2.5}
                    />
                  )}
                </button>
              );
            })}
          </div>
        )}

        {/* The door shows for a typed query, and also for an empty one when
            the list itself is empty: an organization with zero partners
            opens this panel to the empty message and used to find nothing
            but the header close — nobody types into an empty register, so
            the create way out has to be there before anything is typed. */}
        {onCreateNew &&
          createLabel &&
          !loading &&
          (searchQuery.trim() || visibleOptions.length === 0) && (
            <button
              type="button"
              onClick={() => {
                onCreateNew(searchQuery);
                setOpen(false);
                setSearchQuery("");
              }}
              className="w-full flex items-center gap-2 p-2.5 mt-1 rounded-lg border border-dashed border-border text-on-secondary hover:border-primary-400 hover:text-primary-600 hover:bg-primary-500/5 transition-all text-left"
            >
              <Plus size={16} className="shrink-0" />
              <span className="text-sm font-medium">
                {createLabel.replace(/\{\{query\}\}/g, searchQuery)}
              </span>
            </button>
          )}
      </div>
    </>
  );
};

/** The words the field falls back to when its caller passes none. */
function useComboboxText(given: {
  placeholder?: string;
  searchPlaceholder?: string;
  emptyMessage?: React.ReactNode;
  title?: string;
}) {
  const { t } = useTranslation("common");
  return {
    placeholderText: given.placeholder ?? t("actions.select"),
    searchPlaceholderText: given.searchPlaceholder ?? t("actions.search"),
    emptyText: given.emptyMessage ?? t("noResults"),
    titleText: given.title ?? t("actions.select"),
  };
}

export const SearchableCombobox: React.FC<SearchableComboboxProps> = ({
  options,
  value,
  onChange,
  placeholder,
  searchPlaceholder,
  emptyMessage,
  createLabel,
  loading,
  title,
  trigger,
  onClose,
  onCreateNew,
  onSearchChange,
  error,
  id,
  label,
  required,
  clearable = false,
  clearLabel,
  layer,
  labelClassName,
  wrapperClassName,
  disabled,
  "aria-label": ariaLabel,
}) => {
  // Below `sm:` the panel is a bottom sheet, not a popover (UI_GUIDELINES
  // §4.3) — see the comment on the mobile branch for why.
  // Same pattern Select.tsx settled on: an English literal in a default
  // parameter is English in every language, and a caller that wants its own
  // wording still passes one.
  const { placeholderText, searchPlaceholderText, emptyText, titleText } =
    useComboboxText({ placeholder, searchPlaceholder, emptyMessage, title });

  const isDesktop = useMediaQuery("(min-width: 640px)");
  const [open, setOpen] = React.useState(false);
  // Radix hands focus back to the trigger when the panel closes. When it
  // closed through "create new" and the layer that door opens has taken
  // focus into its name field, the hand-back took it away again. A door
  // that opens nothing focusable (a handler that only sets a value) leaves
  // focus nowhere, so the trigger gets it back then.
  const keepFocusOnClose = React.useRef(false);
  const [searchQuery, setQuery] = React.useState("");
  const setSearchQuery = (next: string) => {
    setQuery(next);
    onSearchChange?.(next);
  };
  const generatedId = React.useId();
  const triggerId = id ?? generatedId;
  const errorId = `${triggerId}-error`;
  const titleId = `${triggerId}-title`;
  const panelId = `${triggerId}-panel`;

  // Both scans are skipped where they would answer nothing. A screen may
  // hold one closed picker per row over a list of a thousand, and a scan per
  // row per render is the square of the list — paid on every keystroke
  // somewhere else on the screen.
  const selectedOption = value
    ? options.find((opt) => opt.id === value)
    : undefined;
  const visibleOptions = open
    ? filteredOptions(options, searchQuery, !onSearchChange)
    : NO_OPTIONS;

  const handleSelect = (id: string) => {
    onChange(id);
    setOpen(false);
    setSearchQuery("");
    if (onClose) onClose();
  };

  const handleCreateNew = onCreateNew
    ? (query: string) => {
        keepFocusOnClose.current = true;
        onCreateNew(query);
        // Two frames on: the panel is gone and a layer the door opened has
        // had its effects run. If nobody took focus, it is on the page body
        // and the trigger is where it belongs.
        requestAnimationFrame(() =>
          requestAnimationFrame(() => {
            const active = document.activeElement;
            if (!active || active === document.body) {
              document.getElementById(triggerId)?.focus();
            }
          }),
        );
      }
    : undefined;

  const handleOpenChange = (isOpen: boolean) => {
    setOpen(isOpen);
    if (!isOpen) {
      setSearchQuery("");
      if (onClose) onClose();
    }
  };

  const defaultTrigger = (
    <button
      type="button"
      // A button that opens a list of values to pick one from: what Radix
      // makes the trigger of `Select`. It is also the role that carries
      // `aria-required` — on a plain button axe reports the attribute as
      // not allowed, and readers drop it. The label names it via `htmlFor`.
      role="combobox"
      id={triggerId}
      onClick={() => setOpen(true)}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-invalid={error ? true : undefined}
      aria-required={required || undefined}
      aria-describedby={error ? errorId : undefined}
      // Radix sets both on the desktop trigger; the sheet below `sm:` has no
      // Radix around it, so the trigger states them itself and the two
      // branches announce the same thing.
      aria-haspopup="dialog"
      aria-expanded={open}
      // A combobox names the popup it opens. Ours, not Radix's id, so the
      // sheet below `sm:` carries the same one.
      aria-controls={panelId}
      className={cn(
        // 44px touch target below `md:`, desktop density above it; 1px border
        // and 12px padding are the shared control scale (UI_GUIDELINES §2.10).
        // Filled is not a state: having a value never recolors the border or
        // the weight — only error and focus do — so the trigger reads the
        // same as the Input beside it (§2.10).
        "w-full h-11 md:h-10 px-3 bg-surface-card border rounded-lg transition-all outline-none text-sm text-left flex items-center justify-between gap-3",
        // The other half of that sentence: `outline-none` alone left the
        // trigger with no focus indicator at all, and once `filled` stopped
        // tinting the border there was nothing left to see. Same ring as
        // Input, so keyboard focus reads identically across a form row.
        "focus-visible:ring-2 focus-visible:ring-primary-500/20 focus-visible:border-primary-500",
        error
          ? "border-red-500 text-on focus-visible:ring-red-500/20 focus-visible:border-red-500"
          : "border-border",
        value ? "text-on" : "text-on-muted",
        disabled && "cursor-not-allowed opacity-60",
      )}
    >
      {selectedOption ? (
        <div className="flex items-center gap-3 flex-1 min-w-0">
          {selectedOption.icon && (
            <div className="w-5 h-5 text-primary-600 flex items-center justify-center shrink-0">
              <DynamicIcon
                name={selectedOption.icon}
                size={16}
                strokeWidth={2}
              />
            </div>
          )}
          <span className="min-w-0">
            <span className="block truncate">{selectedOption.name}</span>
            {selectedOption.path && (
              <span className="block truncate text-xs text-on-muted">
                {selectedOption.path}
              </span>
            )}
          </span>
        </div>
      ) : (
        <span className="min-w-0 truncate">{placeholderText}</span>
      )}
      <svg
        className="w-4 h-4 shrink-0 text-on-muted"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M19 9l-7 7-7-7"
        />
      </svg>
    </button>
  );

  const triggerNode = trigger ? (
    <div onClick={() => setOpen(true)}>{trigger}</div>
  ) : (
    defaultTrigger
  );

  /**
   * Header, search and list — one markup for both branches, so the popover
   * and the sheet cannot drift apart.
   *
   * The three are flex children of whatever wraps them: header and search
   * keep their height, the list takes the rest and scrolls. `min-h-0` is
   * what lets it shrink below its content size — without it `overflow-y-auto`
   * never engages and the tail of a long list is unreachable.
   */
  // Built only while open. Both branches below mount it that way already —
  // the sheet behind `open &&`, the popover because Radix unmounts closed
  // content — but the element tree was constructed on every render either
  // way. One closed picker per row, each holding every other row, is how the
  // storage reorganization sheet came to build 1.7 million nodes for a list
  // nobody had opened.
  const panel = !open ? null : (
    <ComboboxPanel
      titleId={titleId}
      title={titleText}
      searchQuery={searchQuery}
      setSearchQuery={setSearchQuery}
      searchPlaceholder={searchPlaceholderText}
      visibleOptions={visibleOptions}
      value={value}
      emptyMessage={emptyText}
      clearable={clearable}
      clearLabel={clearLabel}
      handleSelect={handleSelect}
      handleOpenChange={handleOpenChange}
      setOpen={setOpen}
      onCreateNew={handleCreateNew}
      createLabel={createLabel}
      loading={loading}
    />
  );

  const field = (control: React.ReactNode) => (
    <div className={cn("w-full space-y-1.5", wrapperClassName)}>
      {label && (
        <label
          htmlFor={triggerId}
          className={cn(
            // Same label geometry as Input: block, uppercase, 6px stack
            // owned by this wrapper (UI_GUIDELINES §2.10).
            "block text-xs font-medium uppercase text-on-secondary ml-1 tracking-wide",
            labelClassName,
          )}
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

  /**
   * A phone gets the sheet, not the popover.
   *
   * The panel is around 550px tall — taller than the space under a trigger
   * sitting halfway down a form — so Radix flipped it above the trigger and
   * clamped it against the top of the *layout* viewport, which on a phone is
   * behind the browser's own chrome. Measured on a 390x620 viewport: the
   * panel started at -118px and the search field, the first thing the reader
   * is meant to type into, sat entirely off-screen between -48px and -4px.
   * A bottom sheet has no such geometry to get wrong.
   */
  if (!isDesktop) {
    return field(
      <>
        {triggerNode}
        {open && (
          <Sheet
            open
            onClose={() => handleOpenChange(false)}
            // Above the form it was opened from, whether that form is a sheet
            // or a dialog — and level with it when the caller names a higher
            // tier, because nothing paints above a fullscreen one.
            zIndex={layer ?? "modal-nested"}
            aria-labelledby={titleId}
            id={panelId}
          >
            {panel}
          </Sheet>
        )}
      </>,
    );
  }

  return field(
    <PopoverPrimitive.Root open={open} onOpenChange={handleOpenChange}>
      {/* The caller's trigger itself, not the `div` the sheet branch wraps it
          in: the trigger props land on the element they name. */}
      <PopoverPrimitive.Trigger asChild>
        {trigger ?? defaultTrigger}
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          id={panelId}
          aria-labelledby={titleId}
          className={cn(
            LAYER_TO_CLASS[layer ?? "confirm"],
            "flex flex-col overflow-hidden bg-surface-card rounded-xl shadow-xl border border-border p-1 animate-in fade-in-0 zoom-in-95 duration-200",
          )}
          sideOffset={4}
          collisionPadding={8}
          onCloseAutoFocus={(event) => {
            if (!keepFocusOnClose.current) return;
            keepFocusOnClose.current = false;
            event.preventDefault();
          }}
          style={{
            width: "var(--radix-popover-trigger-width)",
            // Never taller than the room Radix measured for it: a short
            // window shrinks the list instead of pushing the search field
            // off the top of the screen.
            maxHeight:
              "min(600px, var(--radix-popover-content-available-height))",
          }}
        >
          {panel}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>,
  );
};

const NO_OPTIONS: ComboboxOption[] = [];

function filteredOptions(
  options: ComboboxOption[],
  searchQuery: string,
  narrow: boolean,
) {
  // A caller that searches on the server has already narrowed them.
  if (!narrow || !searchQuery.trim()) return options;
  const query = searchQuery.toLowerCase();
  // The path is shown under the name, so it is part of what the reader sees
  // and part of what they type: "receiving" has to find every shelf under it.
  return options.filter(
    (opt) =>
      opt.name.toLowerCase().includes(query) ||
      (opt.path?.toLowerCase().includes(query) ?? false),
  );
}
