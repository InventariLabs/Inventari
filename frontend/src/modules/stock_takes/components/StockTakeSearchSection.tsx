import { useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { categoryLabel } from "@/lib/i18nHelpers";
import { Search, Plus } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { ScannerReadyHint } from "@/components/ui/ScannerReadyHint";
import {
  SCANNER_INPUT_ATTRIBUTE,
  useScannerInput,
} from "@/hooks/useScannerInput";
import { productCode, type Item } from "@/types";
import StockTakeAddItemForm from "./StockTakeAddItemForm";
import StockTakeScanCamera from "./StockTakeScanCamera";

interface Props {
  status: string;
  searchQuery: string;
  onSearchChange: (value: string) => void;
  /** Hits that belong to this count: on its list or in its place. */
  searchHere: Item[];
  /** Hits anywhere else in the organization. */
  searchElsewhere: Item[];
  searchFailed: boolean;
  /** A code entered (Enter), read by a hardware scanner or by the camera. */
  onSubmitCode: (code: string) => void;
  isAddingNewItem: boolean;
  onToggleAddNewItem: () => void;
  newItemName: string;
  onNewItemNameChange: (value: string) => void;
  newItemBarcode: string;
  onNewItemBarcodeChange: (value: string) => void;
  newItemQuantity: number;
  onNewItemQuantityChange: (value: number) => void;
  newItemCategoryId: string;
  onNewItemCategoryIdChange: (value: string) => void;
  newItemUomId: string;
  onNewItemUomIdChange: (value: string) => void;
  createPending: boolean;
  createError: unknown;
  onAddItem: (item: Item) => void;
  onCreateNewItem: () => void;
}

export default function StockTakeSearchSection({
  status,
  searchQuery,
  onSearchChange,
  searchHere,
  searchElsewhere,
  searchFailed,
  onSubmitCode,
  isAddingNewItem,
  onToggleAddNewItem,
  newItemName,
  onNewItemNameChange,
  newItemBarcode,
  onNewItemBarcodeChange,
  newItemQuantity,
  onNewItemQuantityChange,
  newItemCategoryId,
  onNewItemCategoryIdChange,
  newItemUomId,
  onNewItemUomIdChange,
  createPending,
  createError,
  onAddItem,
  onCreateNewItem,
}: Props) {
  const { t } = useTranslation(["stock_takes", "common"]);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const isCounting = status === "in_progress";

  useEffect(() => {
    if (isCounting) {
      searchInputRef.current?.focus();
    }
  }, [isCounting]);

  // A scanner's code counts wherever the focus is — in the search box too,
  // which is where it usually is.
  useScannerInput(onSubmitCode, { enabled: isCounting });

  if (!isCounting) return null;

  const renderHit = (item: Item) => {
    const code = productCode(item);
    return (
      <Button
        size="content"
        key={item.id}
        variant="ghost"
        onClick={() => onAddItem(item)}
        className="w-full py-3 justify-between border-b last:border-b-0 hover:bg-surface active:bg-surface rounded-none active:scale-100"
      >
        <div className="min-w-0 text-left">
          <p className="font-medium">{item.name}</p>
          <p className="text-sm text-on-secondary">
            {code && `${t("item.barcode")}: ${code}`}
            {item.category &&
              ` • ${categoryLabel(t, item.category.code, item.category.name)}`}
          </p>
        </div>
        <Plus size={18} className="text-primary-600" />
      </Button>
    );
  };

  const group = (id: string, label: string, items: Item[]) =>
    items.length > 0 && (
      <div role="group" aria-labelledby={id}>
        <p
          id={id}
          className="px-3 pt-2 pb-1 text-xs font-medium uppercase tracking-wide text-on-muted bg-surface"
        >
          {label}
        </p>
        {items.map(renderHit)}
      </div>
    );

  return (
    <div className="bg-surface-card rounded-xl p-4 border shadow-sm">
      <div>
        <Input
          ref={searchInputRef}
          data-testid="stock-take-counting-input"
          type="text"
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          onKeyDown={(e) => {
            // Enter counts what was typed, the way a scan does: a code names
            // the row and saves it; anything else stays here as a search.
            if (e.key === "Enter" && searchQuery.trim()) {
              e.preventDefault();
              onSubmitCode(searchQuery);
            }
          }}
          placeholder={t("search.placeholder")}
          aria-label={t("search.placeholder")}
          leftIcon={<Search size={20} className="text-on-muted" />}
          autoComplete="off"
          {...{ [SCANNER_INPUT_ATTRIBUTE]: "" }}
        />
        <ScannerReadyHint className="mt-1.5" />
      </div>

      {searchQuery.length >= 2 &&
        searchHere.length + searchElsewhere.length > 0 && (
          <div className="mt-2 border rounded-lg max-h-60 overflow-y-auto">
            {group("stock-take-search-here", t("search.here"), searchHere)}
            {group(
              "stock-take-search-elsewhere",
              t("search.elsewhere"),
              searchElsewhere,
            )}
          </div>
        )}
      {searchQuery.length >= 2 && searchFailed && (
        <p role="alert" className="mt-2 text-sm text-red-600">
          {t("search.failed")}
        </p>
      )}
      <StockTakeScanCamera onCode={onSubmitCode} />
      <Button
        size="content"
        variant="ghost"
        onClick={onToggleAddNewItem}
        className="mt-2 px-0 text-primary-700 hover:underline hover:bg-transparent active:bg-transparent active:scale-100 min-h-11 md:min-h-0 min-w-11 md:min-w-0"
      >
        <Plus size={16} />
        {t("addNewItem")}
      </Button>

      {isAddingNewItem && (
        <StockTakeAddItemForm
          name={newItemName}
          barcode={newItemBarcode}
          quantity={newItemQuantity}
          categoryId={newItemCategoryId}
          uomId={newItemUomId}
          isPending={createPending}
          error={createError}
          onNameChange={onNewItemNameChange}
          onBarcodeChange={onNewItemBarcodeChange}
          onQuantityChange={onNewItemQuantityChange}
          onCategoryIdChange={onNewItemCategoryIdChange}
          onUomIdChange={onNewItemUomIdChange}
          onSubmit={onCreateNewItem}
        />
      )}
    </div>
  );
}
