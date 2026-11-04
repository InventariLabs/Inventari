import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { DateInput } from "@/components/ui/DateInput";
import { FormSheetFooter } from "@/components/ui/FormSheetFooter";
import { ProductCombobox } from "@/components/ui/ProductCombobox";
import { Sheet, SheetBody, SheetHeader } from "@/components/ui/Sheet";
import { CURRENCY_CODES, currencyLabel } from "@/lib/currencies";
import { todayIso } from "@/utils/formatters";
import type { CatalogueSearchResult } from "@/modules/warehouse/moduleApi";

export interface PricelistFormState {
  id: string | null;
  product: CatalogueSearchResult | null;
  unitPrice: string;
  currency: string;
  minQuantity: string;
  validFrom: string;
  validTo: string;
  notes: string;
}

/**
 * A blank price list entry. The currency is left to the caller, which fills in
 * the organization's own: hardcoding "USD" here put dollar prices onto the
 * order lines of organizations that trade in something else.
 *
 * `validFrom` is saved, not just shown, so it is the reader's own day —
 * `toISOString()` answers in UTC, which around midnight is yesterday or
 * tomorrow.
 */
export const emptyForm: PricelistFormState = {
  id: null,
  product: null,
  unitPrice: "",
  currency: "",
  minQuantity: "",
  validFrom: todayIso(),
  validTo: "",
  notes: "",
};

interface PricelistFormModalProps {
  open: boolean;
  form: PricelistFormState;
  onChange: (form: PricelistFormState) => void;
  /**
   * Product search used by the picker. The page owns the concrete API so the
   * modal stays vocabulary-free.
   */
  searchProducts: (q: string) => Promise<CatalogueSearchResult[]>;
  onProductSelected: (product: CatalogueSearchResult) => void;
  onSave: () => void;
  onClose: () => void;
  isSaving: boolean;
}

export function PricelistFormModal({
  open,
  form,
  onChange,
  searchProducts,
  onProductSelected,
  onSave,
  onClose,
  isSaving,
}: PricelistFormModalProps) {
  const { t, i18n } = useTranslation("purchase_orders");

  // The API rejects these before they ever reach a row, so the form says the
  // same thing before the request leaves the browser. Errors are
  // derived from the form, so fixing a field clears its own message.
  const [submitted, setSubmitted] = useState(false);
  useEffect(() => {
    if (open) setSubmitted(false);
  }, [open]);

  const productError =
    !form.id && !form.product ? t("pricelist.productRequired") : undefined;

  const unitPrice = Number(form.unitPrice);
  const unitPriceError =
    form.unitPrice.trim() === "" ||
    !Number.isFinite(unitPrice) ||
    unitPrice <= 0
      ? t("pricelist.unitPricePositive")
      : undefined;

  const minQuantity = Number(form.minQuantity);
  const minQuantityError =
    form.minQuantity.trim() !== "" &&
    (!Number.isFinite(minQuantity) || minQuantity <= 0)
      ? t("pricelist.minQuantityPositive")
      : undefined;

  const validToError =
    form.validFrom.trim() !== "" &&
    form.validTo.trim() !== "" &&
    form.validTo < form.validFrom
      ? t("pricelist.validToInvalid")
      : undefined;

  const hasErrors = !!(
    productError ||
    unitPriceError ||
    minQuantityError ||
    validToError
  );

  const handleSubmit = () => {
    setSubmitted(true);
    if (hasErrors) return;
    onSave();
  };

  const title = form.id ? t("pricelist.editTitle") : t("pricelist.createTitle");

  return (
    // Sheet carries what a hand-rolled div could not: role="dialog",
    // aria-modal, a focus trap and Escape-to-close.
    <Sheet open={open} onClose={onClose} aria-label={title} maxWidth="lg">
      <SheetHeader title={title} onClose={onClose} />
      <SheetBody className="space-y-4 p-5">
        {!form.id && (
          <ProductCombobox
            label={t("pricelist.product")}
            value={form.product}
            onSelect={onProductSelected}
            onClear={() => onChange({ ...form, product: null })}
            search={searchProducts}
            placeholder={t("productPicker.search")}
            required
            error={submitted ? productError : undefined}
            renderNoResults={(query) => (
              <div className="space-y-1 p-3">
                <p className="text-sm text-on-muted">
                  {t("common:combobox.noResults", { query })}
                </p>
                <p className="text-xs text-on-secondary">
                  {t("productPicker.emptyCatalogHint")}
                </p>
              </div>
            )}
          />
        )}

        {/* One column on a phone: two 44px fields side by side inside a sheet
            left each about 130px wide, and a date reads as "12 Sep…". */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 items-end">
          <Input
            label={t("pricelist.price")}
            aria-required="true"
            type="number"
            min="0.01"
            step="0.01"
            value={form.unitPrice}
            error={submitted ? unitPriceError : undefined}
            onChange={(e) => onChange({ ...form, unitPrice: e.target.value })}
          />
          <NativeSelect
            label={t("pricelist.currency")}
            value={form.currency}
            onChange={(e) => onChange({ ...form, currency: e.target.value })}
          >
            <option value="">{t("pricelist.currencyPlaceholder")}</option>
            {CURRENCY_CODES.map((code) => (
              <option key={code} value={code}>
                {code} — {currencyLabel(code, i18n.language)}
              </option>
            ))}
          </NativeSelect>
          <Input
            label={t("pricelist.minQuantity")}
            type="number"
            min="0"
            step="0.001"
            value={form.minQuantity}
            error={submitted ? minQuantityError : undefined}
            onChange={(e) => onChange({ ...form, minQuantity: e.target.value })}
          />
          <DateInput
            label={t("pricelist.validFrom")}
            value={form.validFrom}
            onChange={(value) => onChange({ ...form, validFrom: value })}
          />
          <div className="space-y-1.5">
            <DateInput
              label={t("pricelist.validTo")}
              value={form.validTo}
              min={form.validFrom || undefined}
              error={submitted ? validToError : undefined}
              onChange={(value) => onChange({ ...form, validTo: value })}
            />
            {submitted && validToError && (
              <p role="alert" className="text-xs text-red-600 font-medium ml-1">
                {validToError}
              </p>
            )}
          </div>
        </div>

        <Input
          label={t("pricelist.notes")}
          value={form.notes}
          onChange={(e) => onChange({ ...form, notes: e.target.value })}
        />
      </SheetBody>

      {/* The footer is the component's, not this file's: a hand-rolled row of
          two `size="sm"` buttons scrolled away with the form and split the
          dialog down the middle on a phone (§4.3). */}
      <FormSheetFooter
        isPending={isSaving}
        lineCount={0}
        cancelText={t("common:form.cancel")}
        submitText={t("common:actions.save")}
        onCancel={onClose}
        onSubmit={handleSubmit}
      />
    </Sheet>
  );
}
