import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  LineItemsEditor,
  type LineItem,
  type LineItemProduct,
  type LineItemsEditorLabels,
  type RenderUomSelect,
} from "@/modules/shared/components/LineItemsEditor";
import { UomSelect } from "@/modules/shared/components/UomSelect";
import { useProductSearch } from "@/modules/warehouse/moduleApi";
import { formatMoney } from "@/utils/formatters";
import { computeLineValueWithTax } from "./poLineCalc";

export interface POLineInput {
  id: string;
  product_template_id: string | null;
  name: string;
  sku: string | null;
  barcode: string | null;
  brand: string | null;
  image_url: string | null;
  quantity_ordered: number;
  unit_price: string;
  tax_rate: string;
  uom_id: string | null;
}

interface POLinesSectionProps {
  lines: POLineInput[];
  scanOpen: boolean;
  scanLoading: boolean;
  isCameraActive: boolean;
  scannerError: string | null;
  isTorchOn: boolean;
  onToggleScan: () => void;
  onAddLine: () => void;
  onToggleTorch: () => void;
  onManualCode: (code: string) => void;
  onUpdateData: (id: string, data: Partial<POLineInput>) => void;
  onRemove: (id: string) => void;
  t: (key: string) => string;
  /** Inline "name required" errors keyed by line id. */
  nameErrors?: Record<string, string>;
  currency?: string | null;
  subtotalAmount?: string;
  totalTaxAmount?: string;
  totalAmount?: string;
  subtotalLabel?: string;
  taxAmountLabel?: string;
  totalLabel?: string;
}

function toPOLineUpdates(updates: Partial<LineItem>): Partial<POLineInput> {
  const {
    key: _ignoredKey,
    quantity,
    item_id: _ignoredItemId,
    ...rest
  } = updates;
  const result: Partial<POLineInput> = { ...rest };
  if (quantity !== undefined) {
    result.quantity_ordered = quantity;
  }
  return result;
}

export function POLinesSection({
  lines,
  scanOpen,
  scanLoading,
  isCameraActive,
  scannerError,
  isTorchOn,
  onToggleScan,
  onAddLine,
  onToggleTorch,
  onManualCode,
  onUpdateData,
  onRemove,
  t,
  nameErrors,
  currency,
  subtotalAmount,
  totalTaxAmount,
  totalAmount,
  subtotalLabel,
  taxAmountLabel,
  totalLabel,
}: POLinesSectionProps) {
  const { results, isLoading, search, clearSearch } = useProductSearch();
  const { i18n } = useTranslation(["purchase_orders", "common", "scan"]);
  const dateLang = i18n.language?.substring(0, 2) ?? "en";

  const lineItems = useMemo<LineItem[]>(
    () =>
      lines.map((line) => ({
        key: line.id,
        product_template_id: line.product_template_id,
        name: line.name,
        sku: line.sku,
        barcode: line.barcode,
        brand: line.brand,
        image_url: line.image_url,
        quantity: line.quantity_ordered,
        unit_price: line.unit_price,
        tax_rate: line.tax_rate,
        uom_id: line.uom_id,
      })),
    [lines],
  );

  // the API rejects a line of zero (`quantity_ordered > 0`). Say it on
  // the field rather than after a round trip — an order is often edited to
  // "0 for now", and the reader has no way to know that will not save.
  const lineErrors = useMemo(() => {
    const errors: Record<string, { quantity?: string; name?: string }> =
      Object.fromEntries(
        lines
          .filter((line) => !(Number(line.quantity_ordered) > 0))
          .map((line) => [line.id, { quantity: t("form.quantityPositive") }]),
      );
    for (const [id, message] of Object.entries(nameErrors ?? {})) {
      errors[id] = { ...errors[id], name: message };
    }
    return errors;
  }, [lines, t, nameErrors]);

  const labels: LineItemsEditorLabels = {
    lines: t("form.linesSectionEyebrow"),
    addLine: t("form.addLine"),
    scanOpen: t("form.scanOpen"),
    scanClose: t("form.scanClose"),
    scanHint: t("form.scanning"),
    torchOn: t("form.torchOn"),
    torchOff: t("form.torchOff"),
    emptyHint: t("form.addItemsHint"),
    item: t("form.lineProduct"),
    quantity: t("form.lineQuantity"),
    unit: t("form.lineUnit"),
    unitPrice: currency
      ? `${t("form.lineUnitPrice")} (${currency})`
      : t("form.lineUnitPrice"),
    lineValue: t("form.lineSubtotal"),
    taxRate: t("form.lineTaxRate"),
    removeLine: t("form.removeLine"),
    clearProduct: t("common:actions.clear"),
    noResults: t("form.noResults"),
    adHocBadge: t("form.adHocBadge"),
    adHocBadgeTooltip: t("form.adHocBadgeTooltip"),
    scanManualLabel: t("scan:manualInputLabel"),
    scanManualPlaceholder: t("scan:manualInputPlaceholder"),
    scanManualSubmit: t("scan:manualInputSubmit"),
    subtotal: subtotalLabel,
    taxAmount: taxAmountLabel,
    total: totalLabel,
  };

  const renderUomSelect: RenderUomSelect = useCallback(
    (value, onChange) => (
      <UomSelect value={value} onChange={(uomId) => onChange(uomId)} compact />
    ),
    [],
  );

  const formatLineValue = useCallback(
    (line: LineItem) => {
      const raw = computeLineValueWithTax(
        line.quantity,
        line.unit_price ?? "",
        line.tax_rate ?? "",
      );
      if (!raw) return "";
      return formatMoney(raw, currency, dateLang);
    },
    [currency, dateLang],
  );

  const handleUpdateLine = (key: string, updates: Partial<LineItem>) => {
    onUpdateData(key, toPOLineUpdates(updates));
  };

  const handleSelectProduct = (key: string, product: LineItemProduct) => {
    onUpdateData(key, {
      product_template_id: product.product_template_id,
      name: product.name,
      sku: product.sku,
      barcode: product.barcode,
      brand: product.brand,
      image_url: product.image_url,
      uom_id: product.uom_id,
    });
  };

  const totalsReady =
    subtotalAmount !== undefined &&
    totalTaxAmount !== undefined &&
    totalAmount !== undefined;

  return (
    <LineItemsEditor
      lines={lineItems}
      mode="purchase-order"
      features={{
        scan: true,
        valueFields: true,
        taxField: true,
        totals: true,
      }}
      labels={labels}
      lineErrors={lineErrors}
      search={{
        results,
        isLoading,
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
        onToggle: onToggleScan,
        onToggleTorch,
        onManualCode,
      }}
      totals={
        totalsReady
          ? {
              subtotal: subtotalAmount,
              tax: totalTaxAmount,
              total: totalAmount,
            }
          : undefined
      }
      totalsCurrency={currency}
      dateLang={dateLang}
      formatLineValue={formatLineValue}
      onAddLine={onAddLine}
      onRemoveLine={onRemove}
      onUpdateLine={handleUpdateLine}
      onSelectProduct={handleSelectProduct}
    />
  );
}
