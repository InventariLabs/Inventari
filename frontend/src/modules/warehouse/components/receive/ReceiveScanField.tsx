import { forwardRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Search } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { documentsProductsApi } from "@/modules/warehouse/api/documents_products";
import type { ProductSearchResult } from "@/modules/warehouse/api/documents";
import { useProductSearch } from "@/modules/warehouse/hooks/useProductSearch";
import { cn } from "@/lib/utils";

interface Props {
  disabled: boolean;
  onSelect: (product: ProductSearchResult) => void;
}

/**
 * The scan/search field at the top of the sheet.
 *
 * A barcode reader types its code and presses Enter; a person types a name
 * and either clicks a row or presses Enter for the first. Both land on the
 * same callback. The list is the catalogue search the rest of the module
 * uses, so the screen names products the same way every other document does.
 */
export const ReceiveScanField = forwardRef<HTMLInputElement, Props>(
  function ReceiveScanField({ disabled, onSelect }, ref) {
    const { t } = useTranslation("warehouse");
    const [highlighted, setHighlighted] = useState(0);
    const [missed, setMissed] = useState<string | null>(null);
    const { query, setQuery, results, isLoading, error, search, selectResult } =
      useProductSearch({ onSelect });

    const open = query.trim().length > 0;

    const choose = (product: ProductSearchResult) => {
      setMissed(null);
      setHighlighted(0);
      selectResult(product);
    };

    const chooseFirst = async () => {
      const typed = query.trim();
      if (!typed) return;
      // The list on screen may still answer an earlier query: the shared
      // hook keeps it while the next one is in flight, so a slow reply does
      // not blank the picker. Enter belongs to what is typed now, so while
      // that answer is owed the list is not accepted — a barcode entered
      // over a name search would otherwise add the name's first hit.
      if (!isLoading && results.length > 0) {
        choose(results[Math.min(highlighted, results.length - 1)]);
        return;
      }
      // A scanner's Enter arrives the instant its code does, usually before
      // the keystroke search has answered. Asking once, directly, is what
      // keeps a scan from being a miss — and waiting for the pending answer
      // would drop the scan a person sends while the list is still loading.
      const found = await documentsProductsApi.productSearch(typed, 5);
      if (found.length > 0) {
        choose(found[0]);
      } else {
        setMissed(typed);
      }
    };

    return (
      <div className="relative min-w-0 flex-1">
        <Input
          ref={ref}
          type="text"
          disabled={disabled}
          value={query}
          leftIcon={<Search size={16} />}
          placeholder={t("receive.scanPlaceholder")}
          aria-label={t("receive.scanLabel")}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls="receive-scan-results"
          onChange={(event) => {
            const value = event.target.value;
            setHighlighted(0);
            setMissed(null);
            setQuery(value);
            // Every keystroke asks; the hook keeps only the answer to the
            // last question, so a slow reply to "ba" cannot replace "bar".
            void search(value);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setHighlighted((current) =>
                Math.min(current + 1, Math.max(results.length - 1, 0)),
              );
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setHighlighted((current) => Math.max(current - 1, 0));
            } else if (event.key === "Escape") {
              setMissed(null);
              setQuery("");
            } else if (event.key === "Enter") {
              event.preventDefault();
              void chooseFirst();
            }
          }}
        />
        {open && (
          <div
            id="receive-scan-results"
            role="listbox"
            aria-label={t("receive.scanLabel")}
            className="absolute left-0 right-0 top-full z-[var(--z-popover)] mt-1 max-h-72 overflow-y-auto rounded-lg border border-border bg-surface-card p-1 shadow-xl"
          >
            {error ? (
              <p role="alert" className="px-2 py-1.5 text-sm text-on-danger">
                {error}
              </p>
            ) : results.length > 0 ? (
              results.map((product, index) => (
                <Button
                  key={`${product.product_template_id ?? "item"}-${product.item_id ?? index}`}
                  type="button"
                  variant="ghost"
                  size="row"
                  role="option"
                  aria-selected={index === highlighted}
                  className={cn(
                    "w-full flex-col items-start justify-start gap-0 rounded-md px-2 py-1.5 text-left",
                    index === highlighted
                      ? "bg-surface-raised"
                      : "hover:bg-surface-raised",
                  )}
                  onMouseEnter={() => setHighlighted(index)}
                  onClick={() => choose(product)}
                >
                  <span className="text-sm text-on">{product.name}</span>
                  {(product.sku || product.barcode) && (
                    <span className="text-xs text-on-secondary">
                      {product.sku || product.barcode}
                    </span>
                  )}
                </Button>
              ))
            ) : (
              <p className="px-2 py-1.5 text-sm text-on-secondary">
                {isLoading
                  ? t("receive.scanSearching")
                  : missed
                    ? t("receive.noProductFound", { code: missed })
                    : t("receive.scanTypeMore")}
              </p>
            )}
          </div>
        )}
      </div>
    );
  },
);
