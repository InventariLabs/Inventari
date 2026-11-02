import { useEffect, useRef } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { DateInput } from "@/components/ui/DateInput";
import { QuantityInput } from "@/components/ui/QuantityInput";
import { UomSelect } from "@/modules/shared/components/UomSelect";
import { lookupProductByBarcode } from "@/modules/shared/lib/productLookup";
import { type QuickAddLineDraft } from "@/modules/warehouse/components/documentFormShared";
import { useTranslation } from "react-i18next";

interface DocumentQuickAddPanelProps {
  value: QuickAddLineDraft;
  onChange: (updates: Partial<QuickAddLineDraft>) => void;
  onSubmit: () => void;
  onCancel: () => void;
  /**
   * A receipt line has to name a catalogue product: the panel then makes
   * the product it describes, and asks for the unit the product needs.
   */
  makesProduct?: boolean;
  creating?: boolean;
}

export function DocumentQuickAddPanel({
  value,
  onChange,
  onSubmit,
  onCancel,
  makesProduct = false,
  creating = false,
}: DocumentQuickAddPanelProps) {
  const { t } = useTranslation(["warehouse", "common"]);
  const lookupTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const unitMissing = makesProduct && !value.uom_id;
  const submitLabel = !makesProduct
    ? t("picker.addItem")
    : creating
      ? t("common:productQuickCreate.creating")
      : t("common:productQuickCreate.addAsNew", { name: value.name.trim() });

  useEffect(() => {
    const barcode = value.barcode?.trim();
    if (!barcode) {
      return;
    }

    if (lookupTimeoutRef.current) {
      clearTimeout(lookupTimeoutRef.current);
    }

    lookupTimeoutRef.current = setTimeout(async () => {
      const result = await lookupProductByBarcode(barcode);
      if (result && !value.name.trim()) {
        onChange({
          name: result.name,
          brand: result.brand ?? "",
          sku: result.sku ?? "",
          uom_id: result.uom_id ?? null,
          product_template_id: result.product_template_id,
        });
      }
    }, 500);

    return () => {
      if (lookupTimeoutRef.current) {
        clearTimeout(lookupTimeoutRef.current);
      }
    };
  }, [value.barcode, value.name, onChange]);

  return (
    <div className="rounded-xl border border-primary-200 bg-primary-50/40 p-3 sm:p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-on">
            {t(makesProduct ? "picker.newProduct" : "picker.manualEntry")}
          </h3>
          <p className="text-xs text-on-secondary mt-0.5">
            {t(makesProduct ? "picker.newProductHint" : "picker.addItemsHint")}
          </p>
        </div>
        <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
          {t("common:form.cancel")}
        </Button>
      </div>

      <Input
        id="document-quick-add-name"
        type="text"
        label={t("picker.itemName")}
        aria-required="true"
        value={value.name}
        onChange={(event) => onChange({ name: event.target.value })}
        placeholder={t("picker.itemNamePlaceholder")}
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 items-end gap-3">
        <Input
          id="document-quick-add-brand"
          type="text"
          label={t("lines.brand")}
          value={value.brand}
          onChange={(event) => onChange({ brand: event.target.value })}
          placeholder="-"
        />
        <Input
          id="document-quick-add-barcode"
          type="text"
          label={t("lines.barcode")}
          value={value.barcode}
          onChange={(event) => onChange({ barcode: event.target.value })}
          placeholder="-"
          className="font-mono"
        />
      </div>

      <div className="grid grid-cols-2 items-end sm:grid-cols-4 gap-3">
        <QuantityInput
          id="document-quick-add-quantity"
          uomId={value.uom_id}
          label={t("lines.quantity")}
          aria-required="true"
          value={value.quantity ?? ""}
          onQuantityChange={(quantity) => onChange({ quantity })}
          className="text-center"
        />
        <UomSelect
          value={value.uom_id ?? null}
          onChange={(_uomId, uom) => onChange({ uom_id: uom.id })}
          compact
        />
        <div className="col-span-2 sm:col-span-1">
          <Input
            id="document-quick-add-batch"
            type="text"
            label={t("lines.batchNumber")}
            value={value.batch_number}
            onChange={(event) => onChange({ batch_number: event.target.value })}
            placeholder="-"
          />
        </div>
        <div className="col-span-2 sm:col-span-1">
          <DateInput
            id="document-quick-add-expiry"
            label={t("lines.expiryDate")}
            value={value.expiry_date}
            onChange={(expiry) => onChange({ expiry_date: expiry })}
            presets={["plus1Week", "plus1Month", "plus6Months"]}
          />
        </div>
      </div>

      {/* A disabled button swallows the click silently, so the reason it
          waits is said next to it. */}
      {unitMissing && (
        <p
          id="document-quick-add-uom-required"
          className="text-xs text-on-muted"
        >
          {t("common:productQuickCreate.uomRequired")}
        </p>
      )}

      <div className="flex justify-end">
        <Button
          type="button"
          onClick={onSubmit}
          disabled={!value.name.trim() || unitMissing || creating}
          aria-describedby={
            unitMissing ? "document-quick-add-uom-required" : undefined
          }
        >
          {submitLabel}
        </Button>
      </div>
    </div>
  );
}
