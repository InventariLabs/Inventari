import { useCallback, useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useTorchAvailable } from "@/hooks/useScanCamera";
import {
  LineItemsEditor,
  type LineItem,
  type LineItemProduct,
  type LineItemsEditorLabels,
  type RenderUomSelect,
} from "@/modules/shared/components/LineItemsEditor";
import { UomSelect } from "@/modules/shared/components/UomSelect";
import { DocumentQuickAddPanel } from "@/modules/warehouse/components/DocumentQuickAddPanel";
import {
  type QuickAddLineDraft,
  type ReceiptDraftLine,
} from "@/modules/warehouse/components/documentFormShared";
import { useProductSearch } from "@/modules/warehouse/hooks/useProductSearch";
import { documentsApi } from "@/modules/warehouse/api/documents";
import { formatMoney } from "@/utils/formatters";
import { totalAmounts } from "@/utils/money";

interface DocumentLinesEditorProps {
  lines: ReceiptDraftLine[];
  quickAddOpen: boolean;
  quickAddValue: QuickAddLineDraft;
  /** The quick-add panel makes the product it describes (a receipt). */
  quickAddMakesProduct?: boolean;
  quickAddCreating?: boolean;
  scanOpen: boolean;
  scanLoading: boolean;
  scannerError: string | null;
  isCameraActive: boolean;
  isTorchOn: boolean;
  showValueFields?: boolean;
  showTaxField?: boolean;
  /**
   * The rate the server stamps on any line saved without one
   * (`_apply_simple_rate_tax`). The totals below have to count it, or the
   * form quotes one amount and the document is created for another.
   */
  defaultTaxRate?: string;
  currency?: string | null;
  partnerId?: string | null;
  /**
   * When set, the line search offers the stock standing in this location and
   * every result carries an item id. Dispatch documents need one; a receipt
   * has nothing on the shelf yet, so it searches the catalogue instead.
   */
  stockLocationId?: string | null;
  /**
   * Name of that location and the way to change it. With both, the search
   * says it is limited to the location and, for a product that stands only
   * elsewhere, says where.
   */
  stockLocationName?: string | null;
  onChangeSource?: () => void;
  /** The lines of this document must name a stock record, not a product. */
  needsStockRow?: boolean;
  /**
   * The executor of this document pulls across records (dispatch, scrap) —
   * the search may fold identical records into one row per shelf. A
   * transfer moves a single record and keeps the rows one by one.
   */
  mergeStockRows?: boolean;
  lineErrors?: Record<string, { name?: string; quantity?: string }>;
  onAddEmptyLine: () => void;
  onConsolidate?: () => void;
  onQuickAddChange: (updates: Partial<QuickAddLineDraft>) => void;
  onQuickAddSubmit: () => void;
  onQuickAddCancel: () => void;
  onScanToggle: () => void;
  onToggleTorch: () => void;
  onManualCode: (code: string) => void;
  onRemoveLine: (index: number) => void;
  onUpdateLine: (index: number, updates: Partial<ReceiptDraftLine>) => void;
  /** Drawn under each line; return null for a line with nothing to add. */
  renderLineExtra?: (line: ReceiptDraftLine) => ReactNode;
  /**
   * Whether picking a product for THIS line yielded a price suggestion.
   * The form's empty-price warning promises one, and the promise is about
   * lines: a miss on one line says nothing about the next, so the result
   * travels with the line's key.
   */
  onPriceHintResult?: (lineKey: string, suggested: boolean) => void;
  /**
   * Set where every line has to name a catalogue product (a receipt): a
   * typed name the search does not find is offered as a new product.
   */
  onCreateProduct?: (lineKey: string, name: string) => void;
}

const NULLABLE_FIELDS = [
  "item_id",
  "product_template_id",
  "sku",
  "barcode",
  "brand",
  "image_url",
  "serial_number",
] as const;

const REQUIRED_STRING_FIELDS = [
  "batch_number",
  "expiry_date",
  "notes",
] as const;

function toReceiptLineUpdates(
  updates: Partial<LineItem>,
): Partial<ReceiptDraftLine> {
  const { key: _ignoredKey, ...rest } = updates;
  const result: Record<string, unknown> = { ...rest };
  for (const field of NULLABLE_FIELDS) {
    if (result[field] === null) {
      result[field] = undefined;
    }
  }
  for (const field of REQUIRED_STRING_FIELDS) {
    if (field in result && result[field] === undefined) {
      result[field] = "";
    }
  }
  return result as Partial<ReceiptDraftLine>;
}

function computeLineValue(
  quantity: number,
  price: string,
  currency?: string | null,
  locale?: string,
): string {
  const parsed = parseFloat(price);
  if (!isFinite(parsed) || parsed < 0) return "";
  return formatMoney(quantity * parsed, currency, locale);
}

export function DocumentLinesEditor({
  lines,
  quickAddOpen,
  quickAddValue,
  quickAddMakesProduct,
  quickAddCreating,
  scanOpen,
  scanLoading,
  scannerError,
  isCameraActive,
  isTorchOn,
  showValueFields = false,
  showTaxField = false,
  defaultTaxRate,
  currency,
  partnerId,
  stockLocationId,
  stockLocationName,
  onChangeSource,
  needsStockRow = false,
  mergeStockRows = false,
  lineErrors,
  onAddEmptyLine,
  onConsolidate,
  onQuickAddChange,
  onQuickAddSubmit,
  onQuickAddCancel,
  onScanToggle,
  onToggleTorch,
  onManualCode,
  onRemoveLine,
  onUpdateLine,
  renderLineExtra,
  onPriceHintResult,
  onCreateProduct,
}: DocumentLinesEditorProps) {
  const { t, i18n } = useTranslation(["warehouse", "scan"]);
  const hasTorch = useTorchAvailable();
  const dateLang = i18n.language?.substring(0, 2) ?? "en";
  const { results, elsewhere, isLoading, search, clearSearch } =
    useProductSearch({
      locationId: stockLocationId,
      stockOnly: needsStockRow,
      merge: mergeStockRows,
    });

  const lineItems = useMemo<LineItem[]>(
    () => lines.map((line) => ({ ...line, key: line._key })),
    [lines],
  );

  const indexByKey = useMemo(() => {
    const map = new Map<string, number>();
    lines.forEach((line, index) => map.set(line._key, index));
    return map;
  }, [lines]);

  const labels: LineItemsEditorLabels = {
    lines: t("fields.lines"),
    addLine: t("lines.addLine"),
    scanOpen: t("scan.open"),
    scanClose: t("scan.close"),
    scanHint: t("scan.hint"),
    scanOpening: t("scan.opening"),
    scanProcessing: t("scan.processing"),
    scanManualLabel: t("scan:manualInputLabel"),
    scanManualPlaceholder: t("scan:manualInputPlaceholder"),
    scanManualSubmit: t("scan:manualInputSubmit"),
    torchOn: t("scan.torchOn"),
    torchOff: t("scan.torchOff"),
    emptyHint: t("picker.addItemsHint"),
    item: t("lines.item"),
    quantity: t("lines.quantity"),
    unit: t("lines.unit"),
    unitPrice: t("lines.unitPrice"),
    lineValue: t("lines.lineValue"),
    taxRate: t("lines.taxRate"),
    taxRatePlaceholder: defaultTaxRate,
    removeLine: t("lines.removeLine"),
    clearProduct: t("common:actions.clear"),
    noResults: t("picker.noResults"),
    inStock: t("picker.inStock"),
    addedLabel: t("picker.added"),
    expiryLabel: t("lines.expiryDate"),
    storageLabel: t("register.groupBy_location"),
    adHocBadge: t("lines.adHocBadge"),
    adHocBadgeTooltip: t("lines.adHocBadgeTooltip"),
    subtotal: t("value.totalNet"),
    taxAmount: t("value.totalTax"),
    total: t("value.totalGross"),
    showOptionalFields: t("lines.showOptionalFields"),
    hideOptionalFields: t("lines.hideOptionalFields"),
    consolidate: t("lines.consolidate"),
    batchNumber: t("lines.batchNumber"),
    serialNumber: t("lines.serialNumber"),
    expiryDate: t("lines.expiryDate"),
    expiryFieldHiddenHint: t("lines.expiryFieldHiddenHint"),
    showExpiryField: t("lines.showExpiryField"),
    hideExpiryField: t("lines.hideExpiryField"),
    notes: t("lines.notes"),
  };

  const renderUomSelect: RenderUomSelect = useCallback(
    (value, onChange) => (
      <UomSelect
        value={value}
        onChange={(_uomId, uom) => onChange(uom.id)}
        compact
      />
    ),
    [],
  );

  const formatLineValue = useCallback(
    (line: LineItem) =>
      line.unit_price
        ? computeLineValue(
            line.quantity,
            line.unit_price,
            currency,
            i18n.language,
          )
        : "",
    [currency, i18n.language],
  );

  // live Net/VAT/Gross totals across all priced lines.
  const totals = useMemo(() => {
    // Each line rounded, then summed — the rule in `app/core/money.py`, so
    // this preview and the document it is about to create agree. Adding the
    // raw figures and rounding the total gave a different answer whenever a
    // line's own tax landed on a half.
    const priced = lines.filter((line) => {
      const price = parseFloat(line.unit_price ?? "");
      return isFinite(price) && price >= 0;
    });
    if (priced.length === 0) return undefined;
    const summed = totalAmounts(
      priced.map((line) => ({
        quantity: line.quantity,
        unit_price: line.unit_price,
        // A blank rate is not "no tax" — it is "whatever the profile says",
        // which is what the server will apply. Counting it as zero is how
        // a receipt approved at 51.40 was created at 61.68.
        tax_rate: line.tax_rate || defaultTaxRate,
      })),
    );
    return {
      subtotal: summed.net.toFixed(2),
      tax: summed.tax.toFixed(2),
      total: summed.gross.toFixed(2),
    };
  }, [lines, defaultTaxRate]);

  const handleUpdateLine = (key: string, updates: Partial<LineItem>) => {
    const index = indexByKey.get(key);
    if (index === undefined) return;
    onUpdateLine(index, toReceiptLineUpdates(updates));
  };

  const handleRemoveLine = (key: string) => {
    const index = indexByKey.get(key);
    if (index === undefined) return;
    onRemoveLine(index);
  };

  const handleSelectProduct = async (key: string, product: LineItemProduct) => {
    const index = indexByKey.get(key);
    if (index === undefined) return;
    const existing = lines[index];
    const alreadyPriced =
      existing.unit_price != null && existing.unit_price !== "";
    onUpdateLine(index, {
      item_id: product.item_id ?? undefined,
      product_template_id: product.product_template_id ?? undefined,
      name: product.name,
      sku: product.sku || undefined,
      barcode: product.barcode || undefined,
      brand: product.brand || undefined,
      image_url: product.image_url || undefined,
      uom_id: product.uom_id || undefined,
    });

    // auto-suggest unit price from the partner pricelist or the
    // most recent purchase — never overwrite a price the user already set.
    if (!product.product_template_id || !showValueFields) {
      // A hand-named product has no catalogue entry to hint from, and a form
      // that shows no price must not store one the reader never saw (a
      // transfer): the answer is known before asking, and the form counts it
      // asked.
      onPriceHintResult?.(key, false);
      return;
    }
    if (alreadyPriced) return;
    try {
      const hint = await documentsApi.priceHint({
        template_id: product.product_template_id,
        partner_id: partnerId ?? null,
      });
      // Two answers, kept apart. A product nobody has bought yet has no
      // price to suggest, and the rate that came with it — the partner's,
      // the most specific one there is — used to be discarded along with it.
      const suggestion: Partial<ReceiptDraftLine> = {};
      if (hint.unit_price != null) {
        suggestion.unit_price = String(hint.unit_price);
      }
      if (hint.tax_rate != null) {
        suggestion.tax_rate = String(hint.tax_rate);
      }
      if (Object.keys(suggestion).length === 0) {
        onPriceHintResult?.(key, false);
        return;
      }
      onPriceHintResult?.(key, hint.unit_price != null);
      onUpdateLine(index, suggestion);
    } catch {
      // The ask failed, but it was made: the form may not keep promising
      // a suggestion this line already went looking for.
      onPriceHintResult?.(key, false);
    }
  };

  return (
    <LineItemsEditor
      lines={lineItems}
      mode="document"
      features={{
        scan: true,
        quickAdd: true,
        consolidate: Boolean(onConsolidate),
        optionalFields: true,
        valueFields: showValueFields,
        taxField: showTaxField,
        totals: showValueFields,
      }}
      labels={labels}
      search={{
        results,
        isLoading,
        scope:
          stockLocationId && stockLocationName && onChangeSource
            ? {
                hint: t("picker.inLocation", { location: stockLocationName }),
                elsewhere,
                elsewhereLabel: (location) =>
                  t("picker.inOtherLocation", { location }),
                changeLabel: t("picker.changeSource"),
                onChange: onChangeSource,
              }
            : undefined,
        createNew: onCreateProduct && {
          label: (name) => t("common:productQuickCreate.addAsNew", { name }),
          onCreate: onCreateProduct,
        },
        onQuery: search,
        onClear: clearSearch,
      }}
      renderUomSelect={renderUomSelect}
      scan={{
        open: scanOpen,
        loading: scanLoading,
        error: scannerError,
        cameraActive: isCameraActive,
        torchOn: isTorchOn,
        torchAvailable: hasTorch,
        onToggle: onScanToggle,
        onToggleTorch,
        onManualCode,
      }}
      quickAddPanel={
        quickAddOpen ? (
          <DocumentQuickAddPanel
            value={quickAddValue}
            onChange={onQuickAddChange}
            onSubmit={onQuickAddSubmit}
            onCancel={onQuickAddCancel}
            makesProduct={quickAddMakesProduct}
            creating={quickAddCreating}
          />
        ) : undefined
      }
      dateLang={dateLang}
      formatLineValue={formatLineValue}
      totals={totals}
      totalsCurrency={currency ?? undefined}
      testIds={{
        shell: "document-lines-table-shell",
        desktopHeader: "document-lines-desktop-header",
        rowLayout: (index) => `document-line-card-layout-${index}`,
        optionalPanel: (index) => `document-line-optional-panel-${index}`,
      }}
      lineErrors={lineErrors}
      onAddLine={onAddEmptyLine}
      onRemoveLine={handleRemoveLine}
      onUpdateLine={handleUpdateLine}
      onSelectProduct={handleSelectProduct}
      onConsolidate={onConsolidate}
      renderLineExtra={
        renderLineExtra &&
        ((item) => {
          const index = indexByKey.get(item.key);
          return index === undefined ? null : renderLineExtra(lines[index]);
        })
      }
    />
  );
}
