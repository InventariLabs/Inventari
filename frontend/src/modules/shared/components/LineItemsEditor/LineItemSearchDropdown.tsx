import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { createPortal } from "react-dom";
import { Package, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import LoadingSpinner from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/Button";
import type { LineItemProduct, LineItemSearchScope } from "./types";
import { formatDate, formatQuantityValue } from "@/utils/formatters";
import { unitLabel } from "@/lib/i18nHelpers";
import { readableSku } from "@/lib/readableSku";

interface LineItemSearchDropdownProps {
  results: LineItemProduct[];
  isLoading: boolean;
  selectedIndex: number;
  lineName: string;
  noResultsLabel: string;
  /** Under the no-results line: what happens to the typed name anyway. */
  adHocLabel?: string;
  /** Label prefixing a stock hit's quantity; omitted for catalogue searches. */
  inStockLabel?: string;
  expiryLabel?: string;
  /** Label prefixing the shelf a stock hit stands on. */
  storageLabel?: string;
  /** Label prefixing a stock hit's landing date. */
  addedLabel?: string;
  /** Set when the search is limited to one place. */
  scope?: LineItemSearchScope;
  /** Offered under a search that found nothing: make the name a product. */
  createLabel?: string;
  onCreate?: () => void;
  onSelect: (product: LineItemProduct) => void;
  /** DOM id of the input this dropdown anchors to. When provided, the list
   * renders in a portal positioned against the input — inside a
   * modal the old inline `absolute` list was clipped by the scrolling form
   * container. Without an anchor the legacy inline behaviour is kept. */
  anchorId?: string;
  /** Called when a scroll moves the input while the dropdown is open in
   * portal mode — the parent should close the dropdown (the fixed list must
   * not detach from its input). */
  onRequestClose?: () => void;
  /** DOM id for the list, so the input can point at it with aria-controls. */
  listboxId?: string;
  /** Builds the id of the option at `index`, for aria-activedescendant. */
  optionId?: (index: number) => string;
}

/** Everything a row says besides its record code. */
function visibleSignature(product: LineItemProduct): string {
  return JSON.stringify([
    product.name,
    readableSku(product.sku),
    product.barcode,
    product.serial_number,
    product.created_at ? formatDate(product.created_at) : null,
    product.expiry_date,
    product.location_name,
    product.available_quantity,
    product.uom_symbol,
  ]);
}

/** Brand and id tail for a row that reads like a sibling. A stock hit
 *  carries its record id; a catalogue hit only its template's. */
function twinHint(product: LineItemProduct): string | null {
  const id = product.item_id ?? product.product_template_id;
  if (!id) return null;
  const tail = `#${id.slice(-6)}`;
  return product.brand ? `${product.brand} · ${tail}` : tail;
}

export function LineItemSearchDropdown({
  results,
  isLoading,
  selectedIndex,
  lineName,
  noResultsLabel,
  adHocLabel,
  inStockLabel,
  expiryLabel,
  storageLabel,
  addedLabel,
  scope,
  createLabel,
  onCreate,
  onSelect,
  anchorId,
  onRequestClose,
  listboxId,
  optionId,
}: LineItemSearchDropdownProps) {
  const { t } = useTranslation("common");
  const dropdownRef = useRef<HTMLDivElement>(null);
  // Where the input stood when the panel was last placed against it.
  const placedAt = useRef<{ top: number; left: number } | null>(null);
  const [pos, setPos] = useState<{
    top: number;
    left: number;
    width: number;
    maxHeight: number;
  } | null>(null);

  const hasList = results.length > 0;
  const hasNoResults =
    results.length === 0 && lineName.length >= 2 && !isLoading;
  const showDropdown = hasList || hasNoResults;
  const elsewhere = hasNoResults ? (scope?.elsewhere ?? []) : [];
  const anchor = anchorId ? document.getElementById(anchorId) : null;

  useLayoutEffect(() => {
    if (!showDropdown || !anchor) {
      setPos(null);
      return;
    }
    const update = () => {
      const rect = anchor.getBoundingClientRect();
      placedAt.current = { top: rect.top, left: rect.left };
      const gap = 4;
      const itemCount = Math.max(results.length, 1);
      const estimatedHeight = Math.min(240, Math.max(48, itemCount * 44));
      // What the person can see, not what the window measures: an on-screen
      // keyboard shrinks the visual viewport and leaves the window as it was.
      const visibleBottom = window.visualViewport?.height ?? window.innerHeight;
      const spaceBelow = visibleBottom - rect.bottom - gap;
      const up = spaceBelow < estimatedHeight && rect.top > spaceBelow;
      setPos({
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
    window.visualViewport?.addEventListener("resize", update);
    return () => {
      window.removeEventListener("resize", update);
      window.visualViewport?.removeEventListener("resize", update);
    };
  }, [showDropdown, results.length, anchor]);

  // A fixed list must not stay behind when a scroll carries its input away.
  // Only a scroll of something holding the input can do that, and even then
  // the list goes only if the input really moved from where the panel was
  // placed: a scroll event can reach us for a layout move that happened
  // before the list opened, or for a container that scrolled without
  // shifting the input. The list's own scroll and the input scrolling its own
  // text move nothing either.
  useEffect(() => {
    if (!showDropdown || !anchor) return;
    const onScroll = (e: Event) => {
      const scrolled = e.target as Node;
      if (scrolled === anchor || !scrolled.contains(anchor)) return;
      const placed = placedAt.current;
      const rect = anchor.getBoundingClientRect();
      if (placed && placed.top === rect.top && placed.left === rect.left) {
        return;
      }
      onRequestClose?.();
    };
    window.addEventListener("scroll", onScroll, true);
    return () => window.removeEventListener("scroll", onScroll, true);
  }, [showDropdown, anchor, onRequestClose]);

  if (results.length === 0 && isLoading) {
    return (
      <div className="absolute right-3 top-1/2 -translate-y-1/2">
        <LoadingSpinner />
      </div>
    );
  }

  // The panel exists only when it has something to say: results, or a
  // finished search that found none. Focusing an untouched field used to
  // open it with "no results" printed before anything was searched — and
  // every open panel is what the sheet's Escape handling watches for.
  if (!showDropdown) return null;

  // The record code is for rows that would otherwise read the same; on a
  // row that already differs from its neighbours it is noise.
  const signatureCounts = new Map<string, number>();
  for (const product of results) {
    const signature = visibleSignature(product);
    signatureCounts.set(signature, (signatureCounts.get(signature) ?? 0) + 1);
  }

  const scopeHint = scope && (
    <p className="px-3 pt-2 text-xs text-on-muted">{scope.hint}</p>
  );

  const listContent = hasList ? (
    results.map((product, idx) => (
      <Button
        size="content"
        // The stock search answers with records: two of them can share a
        // template, and a record catalogued as nothing has no template at
        // all. The record's own id is what tells the rows apart; the
        // template's id only serves the catalogue search, which carries none.
        key={product.item_id ?? product.product_template_id ?? `row-${idx}`}
        id={optionId?.(idx)}
        role="option"
        aria-selected={selectedIndex === idx}
        type="button"
        variant="ghost"
        className={cn(
          "w-full justify-start gap-3 px-3 py-2 text-left transition-colors",
          selectedIndex === idx
            ? "bg-primary-50 dark:bg-primary-900/20 text-primary-900 dark:text-primary-100"
            : "hover:bg-surface-raised text-on",
        )}
        onClick={() => onSelect(product)}
      >
        {product.image_url ? (
          <img
            src={product.image_url}
            alt=""
            loading="lazy"
            className="w-8 h-8 rounded object-cover"
          />
        ) : (
          <div className="w-8 h-8 rounded bg-surface-raised flex items-center justify-center shrink-0">
            <Package size={14} className="text-on-muted" />
          </div>
        )}
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium truncate">{product.name}</div>
          <div className="flex flex-wrap gap-2 text-xs text-on-secondary">
            {readableSku(product.sku) && (
              <span className="font-mono">{readableSku(product.sku)}</span>
            )}
            {product.barcode && (
              <span className="font-mono">{product.barcode}</span>
            )}
            {product.serial_number && (
              <span className="font-mono">{product.serial_number}</span>
            )}
            {/* Twins that match on everything else the row prints — two
                records created in the same minute share the landing date, two
                catalogue products may share a name once their generated SKUs
                are hidden — are told apart by their brand and the tail of
                their id, which never ties. Only they get it. */}
            {(signatureCounts.get(visibleSignature(product)) ?? 0) > 1 &&
              twinHint(product) && (
                <span className="font-mono">{twinHint(product)}</span>
              )}
            {product.created_at && (
              <span>
                {addedLabel ? `${addedLabel}: ` : ""}
                {formatDate(product.created_at)}
              </span>
            )}
            {product.expiry_date && (
              <span>
                {expiryLabel ? `${expiryLabel}: ` : ""}
                {product.expiry_date}
              </span>
            )}
            {/* The search walks a location's subtree, so same-named rows can
                stand on different shelves — the shelf is what tells them
                apart, and where the picker walks. */}
            {product.location_name && (
              <span>
                {storageLabel ? `${storageLabel}: ` : ""}
                {product.location_name}
              </span>
            )}
            {product.available_quantity != null && (
              <span>
                {inStockLabel ? `${inStockLabel}: ` : ""}
                {formatQuantityValue(product.available_quantity)}
                {product.uom_symbol
                  ? ` ${unitLabel(t, product.uom_symbol)}`
                  : ""}
              </span>
            )}
          </div>
        </div>
      </Button>
    ))
  ) : (
    <>
      <p className="text-xs text-on-muted text-center py-2">
        {noResultsLabel}
        {adHocLabel && (
          <span className="block pt-0.5" data-testid="line-item-adhoc-hint">
            {adHocLabel}
          </span>
        )}
      </p>
      {onCreate && createLabel && (
        <div className="border-t border-border p-2">
          <Button
            size="content"
            type="button"
            variant="ghost"
            onClick={() => {
              onCreate();
              onRequestClose?.();
            }}
            leftIcon={<Plus size={16} />}
            // The same offer `ProductQuickCreateSearch` makes elsewhere.
            className="w-full justify-start rounded-lg border border-dashed border-accent/40 bg-accent/10 px-3 py-2.5 text-left text-sm text-accent-700 hover:bg-accent/20 dark:text-accent-300"
            data-testid="line-item-create-product"
          >
            {createLabel}
          </Button>
        </div>
      )}
      {scope && elsewhere.length > 0 && (
        <div className="border-t border-border px-3 py-2">
          {/* Information, not options: a line for a product the source
              location does not hold could not be carried out. */}
          <ul className="space-y-1 text-sm text-on">
            {elsewhere.map((product, idx) => (
              <li
                key={product.item_id ?? product.product_template_id ?? idx}
                className="truncate"
              >
                <span className="font-medium">{product.name}</span>
                {product.location_name && (
                  <span className="text-on-secondary">
                    {" — "}
                    <span>{scope.elsewhereLabel(product.location_name)}</span>
                  </span>
                )}
              </li>
            ))}
          </ul>
          <Button
            type="button"
            variant="link"
            size="sm"
            className="mt-1"
            onClick={() => {
              scope.onChange();
              onRequestClose?.();
            }}
          >
            {scope.changeLabel}
          </Button>
        </div>
      )}
    </>
  );

  if (anchor && pos) {
    return createPortal(
      <div
        ref={dropdownRef}
        data-line-item-dropdown
        style={{
          position: "fixed",
          top: pos.top,
          left: pos.left,
          width: pos.width,
          maxHeight: pos.maxHeight,
        }}
        id={listboxId}
        role={hasList ? "listbox" : undefined}
        className="bg-surface-card border border-border rounded-lg shadow-xl z-[var(--z-modal-nested)] overflow-y-auto overflow-x-hidden ring-1 ring-black/5"
      >
        {scopeHint}
        {listContent}
      </div>,
      document.body,
    );
  }

  return (
    <div
      data-line-item-dropdown
      id={listboxId}
      role={hasList ? "listbox" : undefined}
      className="absolute top-full left-0 z-[var(--z-modal)] mt-1 w-full bg-surface-card border border-border rounded-lg shadow-xl max-h-60 overflow-y-auto overflow-x-hidden ring-1 ring-black/5"
    >
      {scopeHint}
      {listContent}
    </div>
  );
}
