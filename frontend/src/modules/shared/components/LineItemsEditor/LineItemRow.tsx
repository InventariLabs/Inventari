import { memo, useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronDown, ChevronUp, Package, Trash2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { QuantityInput } from "@/components/ui/QuantityInput";
import { LineItemSearchDropdown } from "./LineItemSearchDropdown";
import { LineItemOptionalPanel } from "./LineItemOptionalPanel";
import {
  LineItemValueFieldsDesktop,
  LineItemValueFieldsMobile,
} from "./LineItemValueFields";
import type {
  LineItem,
  LineItemErrors,
  LineItemProduct,
  LineItemSearchState,
  LineItemsEditorFeatures,
  LineItemsEditorLabels,
  LineItemsMode,
  RenderUomSelect,
} from "./types";

interface LineItemRowProps {
  line: LineItem;
  index: number;
  mode: LineItemsMode;
  features: LineItemsEditorFeatures;
  labels: LineItemsEditorLabels;
  search: LineItemSearchState;
  renderUomSelect: RenderUomSelect;
  gridClass: string;
  isOptionalExpanded: boolean;
  formatLineValue?: (line: LineItem) => string;
  onToggleOptional: () => void;
  onUpdate: (updates: Partial<LineItem>) => void;
  onRemove: () => void;
  onSelectProduct: (product: LineItemProduct) => void;
  rowTestId?: string;
  optionalPanelTestId?: string;
  error?: LineItemErrors;
  /** What the host draws under the row, if anything (a module's own field). */
  extra?: ReactNode;
}

// The ids a row hands its controls and its suggestion listbox, so the
// editor's test ids and aria wiring stay in step.
const rowFieldIds = (index: number) => ({
  nameFieldId: `line-item-${index}-name`,
  listboxId: `line-item-${index}-suggestions`,
  quantityFieldId: `line-item-${index}-quantity`,
  unitPriceFieldId: `line-item-${index}-unit-price`,
  taxRateFieldId: `line-item-${index}-tax-rate`,
});

/**
 * The picker's interaction — focus, dismissal, keyboard selection and the
 * blur grace window — kept out of the row so the row stays layout. The two
 * booleans differ on purpose: `panelOpen` is what renders the panel (empty
 * "No products found" included), `suggestionsOpen` is the listbox the input
 * announces through aria, and the empty panel has none.
 */
function useLineItemPicker({
  search,
  line,
  onUpdate,
  onSelectProduct,
}: {
  search: LineItemSearchState;
  line: LineItem;
  onUpdate: (updates: Partial<LineItem>) => void;
  onSelectProduct: (product: LineItemProduct) => void;
}) {
  const [isFocused, setIsFocused] = useState(false);
  // A picker dismissed with Escape while the input kept the focus: `isFocused`
  // stays true, and typing is what brings the panel back.
  const [pickerDismissed, setPickerDismissed] = useState(false);
  const [pickedIndex, setSelectedIndex] = useState(-1);
  // The first match is the highlighted one until the arrows move off it, so
  // Enter takes what the list shows as chosen — the rule Receive follows. The
  // list of an earlier query, still on screen while the next is in flight, is
  // not offered: Enter belongs to what is typed now.
  const selectedIndex =
    pickedIndex >= 0
      ? pickedIndex
      : search.results.length > 0 && !search.isLoading
        ? 0
        : -1;

  const handleSearchChange = (value: string) => {
    // Typing re-opens a picker dismissed with Escape: an input that never
    // lost the focus gets no second focus event to reopen it.
    setPickerDismissed(false);
    onUpdate({ name: value });
    setSelectedIndex(-1);
    if (value.trim().length >= 2) {
      search.onQuery(value);
    } else {
      search.onClear();
    }
  };

  const handleSelect = (product: LineItemProduct) => {
    onSelectProduct(product);
    search.onClear();
    setSelectedIndex(-1);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // The picker owns the first Escape whether or not it holds results: the
    // empty "No products found" panel is still a panel, and falling through
    // on zero results left the press to the sheet — which raised its discard
    // question while the panel stayed open. The next Escape is the sheet's.
    if (e.key === "Escape") {
      search.onClear();
      setSelectedIndex(-1);
      setPickerDismissed(true);
      return;
    }

    if (search.results.length === 0) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex(
        selectedIndex < search.results.length - 1
          ? selectedIndex + 1
          : selectedIndex,
      );
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex(selectedIndex > 0 ? selectedIndex - 1 : selectedIndex);
    } else if (e.key === "Enter" && selectedIndex >= 0) {
      e.preventDefault();
      handleSelect(search.results[selectedIndex]);
    }
  };

  // The blur grace timer is delayed work on the global timer queue: a row
  // that goes away inside the 200 ms window — a removed line, a closed
  // editor, a test environment torn down — used to fire its state set on a
  // dead component. The id is kept so unmount can take the timer back.
  const blurTimerRef = useRef<number | null>(null);

  // Runs whether or not the blur ever fired: the grace window may be
  // pending while this row never mounts its other cleanups.
  useEffect(() => {
    return () => {
      if (blurTimerRef.current !== null) {
        clearTimeout(blurTimerRef.current);
        blurTimerRef.current = null;
      }
    };
  }, []);

  const handleBlur = () => {
    if (blurTimerRef.current !== null) {
      clearTimeout(blurTimerRef.current);
    }
    blurTimerRef.current = window.setTimeout(() => {
      blurTimerRef.current = null;
      setIsFocused(false);
    }, 200);
  };

  const handleFocus = () => {
    // A blur whose grace window is still open must not fire after the focus
    // came back, or it closes the panel under an input that holds the focus.
    if (blurTimerRef.current !== null) {
      clearTimeout(blurTimerRef.current);
      blurTimerRef.current = null;
    }
    setIsFocused(true);
    setPickerDismissed(false);
    // A line that opens with a name already in it — a saved draft, a pasted
    // list — has not been searched yet. Its panel said "No products found"
    // and offered to make a product of a name the list may well hold.
    if (line.name.trim().length >= 2) search.onQuery(line.name);
  };

  const panelOpen = isFocused && !pickerDismissed;
  const dismiss = () => setPickerDismissed(true);
  const typedName = line.name.trim();
  const createNew = search.createNew;

  return {
    isFocused,
    panelOpen,
    suggestionsOpen: panelOpen && search.results.length > 0,
    selectedIndex,
    handleSearchChange,
    handleSelect,
    handleKeyDown,
    handleBlur,
    handleFocus,
    // What the suggestion panel is told about this line's search.
    dropdown: {
      results: search.results,
      isLoading: search.isLoading,
      scope: search.scope,
      selectedIndex,
      lineName: line.name,
      onSelect: handleSelect,
      onRequestClose: dismiss,
      createLabel: createNew?.label(typedName),
      onCreate: createNew && (() => createNew.onCreate(line.key, typedName)),
    },
  };
}

/** What a line keeps of a product once it is unpicked. */
const CLEARED_PRODUCT = {
  item_id: null,
  product_template_id: null,
  sku: null,
  barcode: null,
  brand: null,
  image_url: null,
};

/** The chevron that opens or closes a row's optional fields. */
function OptionalToggle({
  expanded,
  labels,
  onToggle,
  buttonSize,
  iconSize,
  className,
}: {
  expanded: boolean;
  labels: LineItemsEditorLabels;
  onToggle: () => void;
  buttonSize: "inline" | "iconSm";
  iconSize: number;
  className: string;
}) {
  const label = expanded
    ? labels.hideOptionalFields
    : labels.showOptionalFields;
  return (
    <Button
      type="button"
      onClick={onToggle}
      variant="ghost"
      size={buttonSize}
      className={className}
      title={label}
      aria-label={label}
    >
      {expanded ? (
        <ChevronUp size={iconSize} />
      ) : (
        <ChevronDown size={iconSize} />
      )}
    </Button>
  );
}

export const LineItemRow = memo(function LineItemRow({
  line,
  index,
  features,
  labels,
  search,
  renderUomSelect,
  gridClass,
  isOptionalExpanded,
  formatLineValue,
  onToggleOptional,
  onUpdate,
  onRemove,
  onSelectProduct,
  rowTestId,
  optionalPanelTestId,
  error,
  extra,
}: LineItemRowProps) {
  const [expiryFieldOpen, setExpiryFieldOpen] = useState(
    Boolean(line.expiry_date),
  );
  const picker = useLineItemPicker({ search, line, onUpdate, onSelectProduct });

  const hasProduct = Boolean(line.item_id || line.product_template_id);
  const lineValue =
    features.valueFields && formatLineValue ? formatLineValue(line) : "";

  const handleClearProduct = () => onUpdate(CLEARED_PRODUCT);

  useEffect(() => {
    if (line.expiry_date) setExpiryFieldOpen(true);
  }, [line.expiry_date]);

  const ids = rowFieldIds(index);
  // The list existed and the arrow keys moved through it, but nothing said
  // so: no role, no aria-expanded, no way to know which entry is current.
  const optionId = (optionIndex: number) =>
    `${ids.listboxId}-option-${optionIndex}`;

  return (
    <div
      className={cn(
        "rounded-xl border border-border bg-surface p-3 sm:p-4 xl:rounded-none xl:border-x-0 xl:border-b-0 xl:border-t-0 xl:bg-transparent xl:px-4 xl:py-3 transition-all",
        picker.isFocused &&
          "relative z-30 ring-1 ring-primary-500/20 xl:ring-0",
      )}
    >
      <div
        data-testid={rowTestId}
        className={`space-y-3 xl:grid xl:items-center xl:gap-3 xl:space-y-0 ${gridClass}`}
      >
        <div className="flex min-w-0 items-center gap-2.5 xl:min-h-[44px]">
          {line.image_url ? (
            <img
              src={line.image_url}
              alt=""
              loading="lazy"
              className="w-10 h-10 rounded-lg object-cover shrink-0"
            />
          ) : (
            <div className="hidden xl:flex w-10 h-10 rounded-lg bg-surface-raised items-center justify-center shrink-0">
              <Package size={16} className="text-on-muted" />
            </div>
          )}
          <div className="min-w-0 flex-1">
            {hasProduct ? (
              <div>
                <div className="flex items-center justify-between group/name">
                  <div className="min-w-0 flex-1">
                    {(line.sku || line.barcode) && ( // ui-pattern: heavy-weight — the SKU and barcode are codes and the monospace bold is the code treatment the typography table keeps
                      <span className="block text-xs font-mono font-bold text-on-secondary tracking-tight mb-0.5">
                        {[line.sku, line.barcode].filter(Boolean).join(" / ")}
                      </span>
                    )}
                    <span className="text-sm font-medium text-on block truncate">
                      {line.name}
                    </span>
                    {line.brand && (
                      <span className="text-xs text-on-muted">
                        {line.brand}
                      </span>
                    )}
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="iconSm"
                    className="-mr-1 text-on-muted transition-opacity hover:text-red-500 md:opacity-0 md:group-hover/name:opacity-100 md:group-focus-within/name:opacity-100"
                    onClick={handleClearProduct}
                    title={labels.clearProduct}
                    aria-label={labels.clearProduct}
                  >
                    <X size={14} />
                  </Button>
                </div>
                {/* A chosen product replaces the input, and with it the only
                    place an error about this line had to render. The reader
                    was left with a toast naming a rule and a row that showed
                    nothing wrong. */}
                {error?.name && (
                  <p
                    role="alert"
                    data-testid={`line-item-product-error-${index}`}
                    className="text-xs text-red-600 font-medium mt-0.5"
                  >
                    {error.name}
                  </p>
                )}
              </div>
            ) : (
              <div className="relative">
                {(line.sku || line.barcode || labels.adHocBadge) && (
                  <div className="absolute -top-[22px] right-2 z-10 flex items-center gap-1.5">
                    {(line.sku || line.barcode) && (
                      <span className="rounded border border-border bg-surface-raised px-1 py-px text-[10px] font-mono font-bold text-on-secondary tracking-tight">
                        {[line.sku, line.barcode].filter(Boolean).join(" / ")}
                      </span>
                    )}
                    {labels.adHocBadge && (
                      <Badge
                        variant="warning"
                        data-testid={`line-item-adhoc-badge-${index}`}
                        title={labels.adHocBadgeTooltip}
                        aria-label={labels.adHocBadgeTooltip}
                        className="cursor-default"
                      >
                        {labels.adHocBadge}
                      </Badge>
                    )}
                  </div>
                )}
                <Input
                  id={ids.nameFieldId}
                  type="text"
                  role="combobox"
                  // The name outlives the placeholder: after the first
                  // keystroke the placeholder is gone, the name is not.
                  aria-label={labels.item}
                  aria-autocomplete="list"
                  aria-expanded={picker.suggestionsOpen}
                  aria-controls={
                    picker.suggestionsOpen ? ids.listboxId : undefined
                  }
                  aria-activedescendant={
                    picker.suggestionsOpen && picker.selectedIndex >= 0
                      ? optionId(picker.selectedIndex)
                      : undefined
                  }
                  required
                  value={line.name}
                  onChange={(event) =>
                    picker.handleSearchChange(event.target.value)
                  }
                  onKeyDown={picker.handleKeyDown}
                  onFocus={picker.handleFocus}
                  onBlur={picker.handleBlur}
                  placeholder={labels.item}
                  className="h-10 px-2 font-medium"
                  error={error?.name}
                />

                {picker.panelOpen && (
                  <LineItemSearchDropdown
                    {...picker.dropdown}
                    noResultsLabel={labels.noResults}
                    adHocLabel={labels.noResultsAdHoc}
                    inStockLabel={labels.inStock}
                    expiryLabel={labels.expiryLabel}
                    storageLabel={labels.storageLabel}
                    addedLabel={labels.addedLabel}
                    anchorId={ids.nameFieldId}
                    listboxId={ids.listboxId}
                    optionId={optionId}
                  />
                )}
              </div>
            )}
          </div>
          <Button
            type="button"
            variant="ghost"
            size="iconSm"
            onClick={onRemove}
            aria-label={labels.removeLine}
            className="shrink-0 text-red-500 hover:bg-red-50 dark:hover:bg-red-950/20 xl:hidden"
          >
            <Trash2 size={16} />
          </Button>
        </div>

        <div className="grid grid-cols-2 gap-3 xl:contents">
          <QuantityInput
            id={ids.quantityFieldId}
            uomId={line.uom_id}
            required
            label={labels.quantity}
            value={line.quantity}
            onQuantityChange={(quantity) => {
              if (quantity !== null) onUpdate({ quantity });
            }}
            className="h-10 px-2 text-center"
            wrapperClassName="xl:space-y-0"
            labelClassName="xl:sr-only"
            error={error?.quantity}
          />
          <div className="space-y-1.5 xl:space-y-0 xl:self-center">
            {/* A `<span>` and not a `<label>`, because the control beside it
                arrives through `renderUomSelect` and there is no id here to
                point `htmlFor` at. `block` all the same: inline, it would sit
                in a line box the wrapper's line-height sizes, and the select
                under it would land about 8px below the QuantityInput sharing
                its grid row — the field's own label is `block`.
                `xl:sr-only` is deliberate: from `xl` up the row flattens into
                the table grid, which prints its own column headers. */}
            <span className="block text-xs font-medium uppercase text-on-secondary ml-1 tracking-wide xl:sr-only">
              {labels.unit}
            </span>
            {renderUomSelect(line.uom_id ?? null, (uomId) =>
              onUpdate({ uom_id: uomId }),
            )}
          </div>
        </div>

        {features.valueFields && (
          <LineItemValueFieldsDesktop
            line={line}
            features={features}
            labels={labels}
            unitPriceFieldId={ids.unitPriceFieldId}
            taxRateFieldId={ids.taxRateFieldId}
            lineValue={lineValue}
            onUpdate={onUpdate}
          />
        )}

        <div className="hidden xl:flex justify-end">
          <Button
            type="button"
            variant="ghost"
            size="iconSm"
            onClick={onRemove}
            aria-label={labels.removeLine}
            className="shrink-0 text-red-500 hover:bg-red-50 dark:hover:bg-red-950/20"
          >
            <Trash2 size={16} />
          </Button>
        </div>

        {features.optionalFields && (
          <OptionalToggle
            expanded={isOptionalExpanded}
            labels={labels}
            onToggle={onToggleOptional}
            buttonSize="inline"
            iconSize={14}
            className="hidden xl:flex text-on-muted hover:text-on-secondary"
          />
        )}
      </div>

      {features.valueFields && (
        <LineItemValueFieldsMobile
          line={line}
          features={features}
          labels={labels}
          unitPriceFieldId={ids.unitPriceFieldId}
          taxRateFieldId={ids.taxRateFieldId}
          lineValue={lineValue}
          onUpdate={onUpdate}
        />
      )}

      {features.optionalFields && (
        <div className="mt-1 flex justify-end xl:hidden">
          <OptionalToggle
            expanded={isOptionalExpanded}
            labels={labels}
            onToggle={onToggleOptional}
            buttonSize="iconSm"
            iconSize={16}
            className="rounded-md text-on-muted hover:text-on-secondary hover:bg-surface-raised/60"
          />
        </div>
      )}

      {features.optionalFields && isOptionalExpanded && (
        <LineItemOptionalPanel
          index={index}
          line={line}
          expiryFieldOpen={expiryFieldOpen}
          labels={labels}
          testId={optionalPanelTestId}
          onUpdate={onUpdate}
          onExpiryToggle={() =>
            setExpiryFieldOpen((v) => {
              if (!v && line.expiry_date) {
                onUpdate({ expiry_date: "" });
              }
              return !v;
            })
          }
        />
      )}

      {/* A host with nothing to add renders nothing, and the empty wrapper
          takes no room. */}
      <div className="empty:hidden xl:pl-14">{extra}</div>
    </div>
  );
});
