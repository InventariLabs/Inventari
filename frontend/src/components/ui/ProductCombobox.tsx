import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Package, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { cn } from "@/lib/utils";
import { useDebounce } from "@/hooks/useDebounce";
import { readableSku } from "@/lib/readableSku";
import { Button } from "./Button";
import { Input } from "./Input";

export interface ProductComboboxOption {
  product_template_id: string;
  name: string;
  sku?: string | null;
  barcode?: string | null;
  brand?: string | null;
  image_url?: string | null;
  is_stub?: boolean;
}

/** Everything an option says about itself before any tie-breaker is added. */
function visibleSignature(product: ProductComboboxOption): string {
  return JSON.stringify([
    product.name,
    readableSku(product.sku),
    product.barcode,
  ]);
}

/**
 * A generated SKU is hidden, so two products with the same name would read
 * the same. Only such twins get their brand and the tail of their id.
 */
function twinHint(
  product: ProductComboboxOption,
  results: ProductComboboxOption[],
): string | null {
  const signature = visibleSignature(product);
  const twins = results.filter((r) => visibleSignature(r) === signature);
  if (twins.length < 2) return null;
  const tail = `#${product.product_template_id.slice(-6)}`;
  return product.brand ? `${product.brand} · ${tail}` : tail;
}

interface ProductComboboxProps<T extends ProductComboboxOption> {
  /** Currently picked product, or null while the user searches. */
  value: T | null;
  onSelect: (product: T) => void;
  /** Called when the picked product is cleared. Optional — omit to hide the clear affordance. */
  onClear?: () => void;
  /** Server-side product search, called with the debounced query. */
  search: (query: string) => Promise<T[]>;
  /**
   * Rendered inside the popover when a finished search matched nothing.
   * Receives the query and the combobox's own select handler, so an
   * "add as new" flow can hand the fresh record straight into the pick.
   * Optional — without it a finished search with no matches closes.
   */
  renderNoResults?: (
    query: string,
    select: (product: T) => void,
  ) => React.ReactNode;
  /**
   * Extra content at the end of each result row (a badge, a marker). The
   * combobox knows nothing about what it marks; the caller decides what a
   * row should say beyond the product's own names.
   */
  renderOptionMeta?: (product: T) => React.ReactNode;
  /** Visible label, like Input's. */
  label?: string;
  /** Label styling, like Input's — callers with non-standard label rows pass their own. */
  labelClassName?: string;
  placeholder?: string;
  /** Prefix for `data-testid` on the input and the result buttons. */
  testId?: string;
  /** Minimum characters before a search fires (default 2). */
  minQueryLength?: number;
  /** Debounce in ms — one query per this many ms of typing (default 250). */
  debounceMs?: number;
  /**
   * Text the box opens with, searched at once. For a caller that already
   * knows what the person is looking for (an ingredient's own name), so the
   * answer — a match, or the "add as new" panel — is there without typing.
   */
  initialQuery?: string;
  /** Longest text the box takes — a caller that creates from it passes the
   *  name column's limit, so the reader meets it while typing. */
  maxLength?: number;
}

/**
 * The non-result branches of the panel: a search in flight says so, and an
 * empty one always answers instead of leaving the field looking broken.
 * Lives outside the combobox so its branches do not count against the
 * component's ESLint complexity gate.
 */
function ProductComboboxMessage<T extends ProductComboboxOption>({
  showLoading,
  query,
  renderNoResults,
  onSelect,
  t,
}: {
  showLoading: boolean;
  query: string;
  renderNoResults?: (
    query: string,
    select: (product: T) => void,
  ) => React.ReactNode;
  onSelect: (product: T) => void;
  t: TFunction;
}) {
  if (showLoading) {
    return (
      <div className="flex items-center gap-2 p-3 text-sm text-on-muted">
        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-accent-600" />
        {t("combobox.searching")}
      </div>
    );
  }
  if (renderNoResults) {
    return <>{renderNoResults(query, onSelect)}</>;
  }
  return (
    <div className="p-3 text-sm text-on-muted">
      {t("combobox.noResults", { query })}
    </div>
  );
}

/**
 * A single product is the smallest unit every inventory module manipulates,
 * so the search for it was implemented three times — the pricelist and
 * reorder-rule forms, the maker's BoM editor and the putaway rule editor each
 * had their own dropdown, and each had its own flavour of the same bugs (a
 * list clipped by the modal that owned it, no keyboard, no screen-reader
 * vocabulary). This is the shared one: an async server-side combobox that
 * asks the caller's `search` function (debounced at 250ms) and paints the
 * results in a portal so no parent's `overflow` can cut them off.
 *
 * It owns none of the product vocabulary — the caller decides what "search"
 * means (documents API, maker API) and whether picking a product that does
 * not exist yet is possible (`renderNoResults`, the shared home of every
 * "add as new" flow).
 */
export function ProductCombobox<T extends ProductComboboxOption>({
  value,
  onSelect,
  onClear,
  search,
  renderNoResults,
  renderOptionMeta,
  label,
  labelClassName,
  placeholder,
  testId,
  minQueryLength = 2,
  debounceMs = 250,
  initialQuery,
  maxLength,
}: ProductComboboxProps<T>) {
  const { t } = useTranslation("common");
  const inputRef = useRef<HTMLInputElement>(null);
  // A changed query must not be answered by the results of the query before
  // it — a slow response arriving late would overwrite a fast newer one.
  const requestSeq = useRef(0);
  // Callers pass their module's search; some inline it, so the identity can
  // change on every render. The debounce effect must not reset on identity
  // alone, or nothing would ever fire — keep the latest in a ref and read it
  // from the effect.
  const searchRef = useRef(search);
  searchRef.current = search;
  const listboxId = useId();
  const optionId = (index: number) => `${listboxId}-option-${index}`;
  // Read in an initializer of its own: a default in the signature counts a
  // branch against this component's complexity limit.
  const [query, setQuery] = useState(() => initialQuery ?? "");
  const [results, setResults] = useState<T[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  // The query the current `results` belong to — without it the "no results"
  // branch would flash while the debounce is still pending.
  const [searchedQuery, setSearchedQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(-1);

  const trimmedQuery = query.trim();
  const settledQuery = useDebounce(trimmedQuery, debounceMs);

  // Emptying the box empties the list at once. Waiting out the debounce
  // first would leave the previous product's results under a blank field.
  useEffect(() => {
    setSelectedIndex(-1);
    if (trimmedQuery.length < minQueryLength) {
      setResults([]);
      setSearchedQuery("");
      setIsLoading(false);
    }
  }, [trimmedQuery, minQueryLength]);

  useEffect(() => {
    if (settledQuery.length < minQueryLength) return;
    const seq = ++requestSeq.current;
    let cancelled = false;
    setIsLoading(true);
    void (async () => {
      try {
        const data = await searchRef.current(settledQuery);
        if (cancelled || seq !== requestSeq.current) return;
        setResults(data);
        setSearchedQuery(settledQuery);
      } catch {
        if (cancelled || seq !== requestSeq.current) return;
        setResults([]);
        setSearchedQuery(settledQuery);
      } finally {
        if (!cancelled && seq === requestSeq.current) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [settledQuery, minQueryLength]);

  function reset() {
    setQuery("");
    setResults([]);
    setSearchedQuery("");
    setSelectedIndex(-1);
  }

  function select(product: T) {
    onSelect(product);
    reset();
  }

  const searching = query.trim().length >= minQueryLength;
  const showLoading = searching && isLoading;
  const showResults = searching && results.length > 0;

  // `query.trim() === searchedQuery` already pins this to a finished search
  // (the query only matches once its results have landed), so the explicit
  // `!isLoading` here was redundant; dropping it keeps the panel below the
  // ESLint complexity gate. `showLoading` wins when both are true.
  const showEmpty =
    searching && query.trim() === searchedQuery && results.length === 0;
  // The panel now opens for the in-between state too: a search that is still
  // running says "searching" instead of silently leaving the field looking
  // broken, and a search that finished empty always says so (/).
  const dropdownOpen = showResults || showLoading || showEmpty;

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" && showResults) {
      e.preventDefault();
      setSelectedIndex((prev) => (prev < results.length - 1 ? prev + 1 : prev));
    } else if (e.key === "ArrowUp" && showResults) {
      e.preventDefault();
      setSelectedIndex((prev) => (prev > 0 ? prev - 1 : prev));
    } else if (e.key === "Enter" && selectedIndex >= 0 && showResults) {
      e.preventDefault();
      select(results[selectedIndex]);
    } else if (e.key === "Escape") {
      reset();
    }
  };

  // The panel lives in a portal positioned against the input in the viewport:
  // as an absolutely positioned child it ended at the modal's scroll edge
  //opened downwards regardless of the space left, and inherited the
  // modal's pointer-events freeze. Fixed against the rect fixes all three.
  const [panelPos, setPanelPos] = useState<{
    top: number;
    left: number;
    width: number;
    maxHeight: number;
  } | null>(null);

  useEffect(() => {
    if (!dropdownOpen) {
      setPanelPos(null);
      return;
    }
    const update = () => {
      const rect = inputRef.current?.getBoundingClientRect();
      if (!rect) return;
      const gap = 4;
      const estimatedHeight =
        showEmpty || showLoading
          ? 120
          : Math.min(240, Math.max(56, results.length * 48));
      const spaceBelow = window.innerHeight - rect.bottom - gap;
      const up = spaceBelow < estimatedHeight && rect.top > spaceBelow;
      setPanelPos({
        left: rect.left,
        width: rect.width,
        top: up
          ? Math.max(8, rect.top - estimatedHeight - gap)
          : rect.bottom + gap,
        maxHeight: up ? Math.max(96, rect.top - 16) : Math.min(240, spaceBelow),
      });
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [dropdownOpen, results.length, showEmpty, showLoading]);

  // Close when the form scrolls under the fixed panel — otherwise the
  // suggestions drift away from the input they belong to. Only a scroll of
  // something holding the input moves it: the panel's own list does not, nor
  // does the input scrolling its own text sideways, which a long name does
  // when the focus comes back to it — that used to wipe the name the reader
  // had just been refused on.
  useEffect(() => {
    if (!dropdownOpen) return;
    const onScroll = (e: Event) => {
      const scrolled = e.target as Node;
      const input = inputRef.current;
      const movesInput =
        scrolled === document ||
        (scrolled !== input && scrolled.contains(input));
      if (movesInput) reset();
    };
    window.addEventListener("scroll", onScroll, true);
    return () => window.removeEventListener("scroll", onScroll, true);
  }, [dropdownOpen]);

  return (
    <div className="relative">
      <Input
        ref={inputRef}
        type="text"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={dropdownOpen}
        aria-controls={dropdownOpen ? listboxId : undefined}
        aria-activedescendant={
          selectedIndex >= 0 ? optionId(selectedIndex) : undefined
        }
        aria-label={label ? undefined : placeholder}
        label={label}
        labelClassName={labelClassName}
        value={value ? value.name : query}
        onChange={(e) => setQuery(e.target.value)}
        maxLength={maxLength}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={!!value}
        leftIcon={<Search size={16} className="pointer-events-none" />}
        rightIcon={
          isLoading && !value ? (
            <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-accent-600" />
          ) : undefined
        }
        data-testid={testId ? `${testId}-input` : undefined}
      />

      {value && (
        <div className="mt-2 flex items-center gap-2">
          <div className="flex items-center gap-2 text-sm">
            {value.image_url ? (
              <img
                src={value.image_url}
                alt=""
                loading="lazy"
                className="w-8 h-8 rounded-md object-cover"
              />
            ) : (
              <div className="w-8 h-8 rounded-md bg-surface-raised flex items-center justify-center">
                <Package size={14} className="text-on-muted" />
              </div>
            )}
            <div>
              <span className="font-medium text-on">{value.name}</span>
              {readableSku(value.sku) && (
                <span className="ml-2 font-mono text-xs text-on-secondary">
                  {readableSku(value.sku)}
                </span>
              )}
            </div>
          </div>
          {onClear && (
            <Button type="button" variant="ghost" size="sm" onClick={onClear}>
              {t("actions.clear")}
            </Button>
          )}
        </div>
      )}

      {dropdownOpen &&
        panelPos &&
        createPortal(
          <div
            style={{
              position: "fixed",
              top: panelPos.top,
              left: panelPos.left,
              width: panelPos.width,
              maxHeight: panelPos.maxHeight,
              // A modal Radix dialog freezes the page by setting
              // `pointer-events: none` on <body> and re-enabling it on its own
              // layer. This list is portalled to <body> and is not one of
              // those layers, so without its own it inherited the freeze and
              // every suggestion went dead to the mouse.
              pointerEvents: "auto",
            }}
            id={listboxId}
            // Every open state of the panel — results, searching, empty —
            // carries the marker `Sheet` reads to leave Escape to the picker;
            // the listbox role alone covers only the one holding results.
            data-line-item-dropdown
            role={showResults ? "listbox" : undefined}
            className="bg-surface-card border border-border rounded-lg shadow-lg z-[var(--z-modal-nested)] overflow-y-auto overflow-x-hidden ring-1 ring-black/5"
          >
            {showLoading || showEmpty ? (
              <ProductComboboxMessage
                showLoading={showLoading}
                query={query.trim()}
                renderNoResults={renderNoResults}
                onSelect={select}
                t={t}
              />
            ) : (
              results.map((product, idx) => (
                <Button
                  size="content"
                  key={product.product_template_id}
                  id={optionId(idx)}
                  role="option"
                  aria-selected={selectedIndex === idx}
                  type="button"
                  variant="ghost"
                  onClick={() => select(product)}
                  data-testid={testId ? `${testId}-result` : undefined}
                  className={cn(
                    "w-full justify-start gap-3 px-3 py-2.5 rounded-none text-left border-b border-border last:border-b-0 transition-colors",
                    selectedIndex === idx
                      ? "bg-primary-50 dark:bg-primary-900/20 text-primary-900 dark:text-primary-100"
                      : "hover:bg-surface-raised text-on",
                  )}
                >
                  {product.image_url ? (
                    <img
                      src={product.image_url}
                      alt=""
                      loading="lazy"
                      className="w-8 h-8 rounded-md object-cover shrink-0"
                    />
                  ) : (
                    <div className="w-8 h-8 rounded-md bg-surface-raised flex items-center justify-center shrink-0">
                      <Package size={14} className="text-on-muted" />
                    </div>
                  )}
                  <div className="flex-1 min-w-0 text-left">
                    <div className="text-sm font-medium text-on truncate">
                      {product.name}
                    </div>
                    {readableSku(product.sku) && (
                      <div className="font-mono text-xs text-on-secondary">
                        {readableSku(product.sku)}
                      </div>
                    )}
                    {product.barcode && !readableSku(product.sku) && (
                      <div className="font-mono text-xs text-on-secondary">
                        {product.barcode}
                      </div>
                    )}
                    {twinHint(product, results) && (
                      <div className="font-mono text-xs text-on-secondary">
                        {twinHint(product, results)}
                      </div>
                    )}
                  </div>
                  {renderOptionMeta?.(product) && (
                    <div className="shrink-0 self-center">
                      {renderOptionMeta(product)}
                    </div>
                  )}
                </Button>
              ))
            )}
          </div>,
          document.body,
        )}
    </div>
  );
}
