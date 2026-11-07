import { useEffect, useRef, useState } from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { useTranslation } from "react-i18next";
import { Link2, Loader2, Search, X } from "lucide-react";
import { productTemplatesApi } from "@/lib/api/productTemplates";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { useDebounce } from "@/module-sdk";

interface TemplateOption {
  id: string;
  name: string;
  brand: string | null;
}

interface IngredientTemplateComboboxProps {
  /** Current free-text ingredient name (drives the search query). */
  query: string;
  /** Currently linked template id, if any. */
  value: string | null;
  onChange: (templateId: string | null, templateName: string) => void;
  onQueryChange: (name: string) => void;
  onBlur?: () => void;
  disabled?: boolean;
  error?: boolean;
  className?: string;
}

const MIN_QUERY_LENGTH = 2;

/**
 * Ingredient-name input with async ProductTemplate autocomplete.
 *
 * Typing ≥2 characters searches the product catalog; selecting a
 * suggestion links the ingredient to that template (availability, cost
 * and picking then work). Free text remains allowed — the ingredient
 * simply stays unlinked (shown as "not linked" by the caller).
 *
 * Not `ProductCombobox`, deliberately. That control asks the reader
 * to *pick a product*: it holds the picked one, disables its own input and
 * shows a card with a clear button. Here the typed text is the value — an
 * ingredient called "włoszczyzna" is a legitimate answer with no product
 * behind it — and the catalogue is a suggestion on top of it, not the point.
 * The two searches that really were "pick a product" (the import row and the
 * availability row) did move to the shared one.
 */
export default function IngredientTemplateCombobox({
  query,
  value,
  onChange,
  onQueryChange,
  onBlur,
  disabled,
  error,
  className,
}: IngredientTemplateComboboxProps) {
  const { t } = useTranslation("recipes");
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<TemplateOption[]>([]);
  const [loading, setLoading] = useState(false);
  const debouncedQuery = useDebounce(query, 250);
  const activeSearch = useRef("");
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Fetch suggestions when the debounced query changes.
  useEffect(() => {
    const q = debouncedQuery.trim();
    if (q.length < MIN_QUERY_LENGTH) {
      setOptions([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    activeSearch.current = q;
    productTemplatesApi
      .search(q)
      .then((templates) => {
        if (cancelled || activeSearch.current !== q) return;
        setOptions(
          templates.map((tpl) => ({
            id: tpl.id,
            name: tpl.name,
            brand: tpl.brand ?? null,
          })),
        );
      })
      .catch(() => {
        if (!cancelled) setOptions([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedQuery]);

  // Radix Popover handles outside clicks and Escape.

  const selectTemplate = (option: TemplateOption) => {
    onChange(option.id, option.name);
    setOpen(false);
  };

  // The suggestions are ordinary buttons in a portal, so the keyboard has to
  // be walked from here: a `<button>` fires `click` on Enter and Space and
  // never `mousedown`, which is where accepting a suggestion used to live.
  // The mousedown handler stays — it is what beats the input's `blur` on a
  // real press — and the keyboard gets its own way in beside it.
  const optionButtons = () =>
    Array.from(
      listRef.current?.querySelectorAll<HTMLButtonElement>(
        "[data-suggestion]",
      ) ?? [],
    );

  const focusOption = (index: number) => {
    const buttons = optionButtons();
    if (buttons.length === 0) return;
    const wrapped = (index + buttons.length) % buttons.length;
    buttons[wrapped]?.focus();
  };

  const handleInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== "ArrowDown" || !showDropdown) return;
    e.preventDefault();
    focusOption(0);
  };

  const handleOptionKeyDown = (
    e: React.KeyboardEvent<HTMLButtonElement>,
    option: TemplateOption,
    index: number,
  ) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      selectTemplate(option);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      focusOption(index + 1);
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      // Up from the first suggestion goes back to what was typed, so the
      // list is a detour and not a trap.
      if (index === 0) inputRef.current?.focus();
      else focusOption(index - 1);
    }
  };

  // The list is for the field in front of the reader. Once focus goes to any
  // other control — the unit picker under the name, most often — it closes,
  // so two popovers are never open over each other. Focus walking into the
  // list (ArrowDown) or back to the field keeps it open.
  const closeUnlessFocusStaysInList = (next: EventTarget | null) => {
    if (next instanceof Node) {
      if (listRef.current?.contains(next)) return;
      if (inputRef.current?.contains(next)) return;
    }
    setOpen(false);
  };

  const clearTemplate = () => {
    onChange(null, query);
  };

  const showDropdown = open && options.length > 0;

  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
      <PopoverPrimitive.Trigger asChild>
        <div className={cn("relative flex-1 min-w-0", className)}>
          <div className="relative flex items-center">
            <Search
              size={13}
              className="absolute left-2.5 text-on-muted pointer-events-none"
            />
            <input
              ref={inputRef}
              type="text"
              aria-label={t("form.ingredient_name")}
              value={query}
              onChange={(e) => {
                onQueryChange(e.target.value);
                setOpen(true);
              }}
              onBlur={(e) => {
                onBlur?.();
                closeUnlessFocusStaysInList(e.relatedTarget);
              }}
              onKeyDown={handleInputKeyDown}
              disabled={disabled}
              placeholder={t("form.ingredient_name")}
              className={cn(
                "w-full pl-8 pr-7 py-1.5 text-sm bg-transparent border-0 shadow-none focus:ring-0 h-auto",
                error ? "text-red-600 placeholder:text-red-400" : "",
              )}
            />
            {loading && (
              <Loader2
                size={13}
                className="absolute right-2 animate-spin text-on-muted pointer-events-none"
              />
            )}
            {value && !loading && (
              <Button
                type="button"
                onClick={clearTemplate}
                aria-label={t("form.ingredient_unlink")}
                title={t("form.ingredient_unlink")}
                variant="ghost"
                size="inline"
                className="absolute right-1.5 p-0.5 rounded text-on-muted hover:text-on-secondary"
              >
                <X size={16} />
              </Button>
            )}
          </div>
        </div>
      </PopoverPrimitive.Trigger>

      {/* Portal: the dropdown used `absolute` inside the ingredient
          card (overflow-hidden) and was clipped — "pcs"/link suggestions in
          later rows were unclickable. */}
      {showDropdown && (
        <PopoverPrimitive.Portal>
          <PopoverPrimitive.Content
            ref={listRef}
            className="z-[var(--z-popover)] max-h-56 overflow-y-auto rounded-xl border border-border bg-surface-card shadow-xl p-1"
            sideOffset={4}
            // The typed name is the value here; the list is a suggestion on
            // top of it. Focus stays in the field until ArrowDown asks for the
            // list, so opening it never interrupts typing.
            onOpenAutoFocus={(e) => e.preventDefault()}
          >
            {options.map((option, index) => (
              <Button
                key={option.id}
                type="button"
                data-suggestion
                onMouseDown={(e) => {
                  e.preventDefault();
                  selectTemplate(option);
                }}
                onKeyDown={(e) => handleOptionKeyDown(e, option, index)}
                onBlur={(e) => closeUnlessFocusStaysInList(e.relatedTarget)}
                variant="ghost"
                size="contentSm"
                className="w-full px-2.5 py-2 justify-start text-left gap-2"
              >
                <Link2 size={16} className="shrink-0 text-primary-600" />
                <span className="flex-1 min-w-0">
                  <span className="block text-sm text-on truncate">
                    {option.name}
                  </span>
                  {option.brand && (
                    <span className="block text-xs text-on-muted truncate">
                      {option.brand}
                    </span>
                  )}
                </span>
                <span className="text-xs text-primary-600 shrink-0">
                  {t("form.ingredient_link")}
                </span>
              </Button>
            ))}
          </PopoverPrimitive.Content>
        </PopoverPrimitive.Portal>
      )}
    </PopoverPrimitive.Root>
  );
}
