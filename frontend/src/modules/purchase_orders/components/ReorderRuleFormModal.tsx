import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/Input";
import { unitLabel } from "@/lib/i18nHelpers";
import { SearchableCombobox } from "@/components/ui/SearchableCombobox";
import { LocationCombobox } from "@/module-sdk";
import { FormSheetFooter } from "@/components/ui/FormSheetFooter";
import { ProductCombobox } from "@/components/ui/ProductCombobox";
import { Sheet, SheetBody, SheetHeader } from "@/components/ui/Sheet";
import type { CatalogueSearchResult } from "@/modules/warehouse/moduleApi";

export interface RuleFormState {
  id: string | null;
  product: CatalogueSearchResult | null;
  locationId: string;
  minQuantity: string;
  maxQuantity: string;
  safetyStock: string;
  preferredPartnerId: string;
  notes: string;
}

/** One field of the thresholds row: label, input, description and error take
 *  four rows of the grid they share with their neighbours. */
const THRESHOLD_FIELD = "grid grid-rows-subgrid row-span-4 gap-y-1.5 space-y-0";

export const emptyForm: RuleFormState = {
  id: null,
  product: null,
  locationId: "",
  minQuantity: "",
  maxQuantity: "",
  safetyStock: "0",
  preferredPartnerId: "",
  notes: "",
};

interface ReorderRuleFormModalProps {
  open: boolean;
  form: RuleFormState;
  onChange: (form: RuleFormState) => void;
  /**
   * Product search used by the picker. The page owns the concrete API so the
   * modal stays vocabulary-free.
   */
  searchProducts: (q: string) => Promise<CatalogueSearchResult[]>;
  onProductSelected: (product: CatalogueSearchResult) => void;
  partnerOptions: { id: string; name: string }[];
  /** The preferred supplier is looked up on the server as the reader types. */
  onPartnerSearch: (query: string) => void;
  partnersLoading: boolean;
  onSave: () => void;
  onClose: () => void;
  isSaving: boolean;
}

export function ReorderRuleFormModal({
  open,
  form,
  onChange,
  searchProducts,
  onProductSelected,
  partnerOptions,
  onPartnerSearch,
  partnersLoading,
  onSave,
  onClose,
  isSaving,
}: ReorderRuleFormModalProps) {
  const { t } = useTranslation("purchase_orders");

  // Both thresholds have to be above 0, and MIN is the one that matters:
  // it is what makes the rule fire, while MAX is only the level to reach.
  // The star used to sit on MAX alone, so a rule saved with the required
  // fields got MIN 0 and the engine skipped it — a row on the list that
  // looked like every other one and could never produce an alert.
  const [submitted, setSubmitted] = useState(false);
  useEffect(() => {
    if (open) setSubmitted(false);
  }, [open]);

  const positiveError = (raw: string, message: string) => {
    const value = Number(raw);
    return raw.trim() === "" || !Number.isFinite(value) || value <= 0
      ? message
      : undefined;
  };

  const minQuantityError = positiveError(
    form.minQuantity,
    t("reorderRules.minPositive"),
  );
  const maxQuantityError = positiveError(
    form.maxQuantity,
    t("reorderRules.maxPositive"),
  );

  const handleSubmit = () => {
    setSubmitted(true);
    if (minQuantityError || maxQuantityError) return;
    onSave();
  };

  const title = form.id
    ? t("reorderRules.editTitle")
    : t("reorderRules.createTitle");

  // The unit belongs to the selected product; threshold values are plain
  // numbers without it, so carry the localized label next to the fields.
  const unit = unitLabel(t, form.product?.uom_symbol) || undefined;

  return (
    // Same shared dialog as every other modal in these modules — role,
    // aria-modal, focus trap and Escape come with it.
    <Sheet open={open} onClose={onClose} aria-label={title} maxWidth="lg">
      <SheetHeader title={title} onClose={onClose} />
      <SheetBody className="space-y-4 p-5">
        {/* The same picker the price form uses — this file carried a
            byte-for-byte copy of its dropdown. */}
        {!form.id && (
          <ProductCombobox
            label={t("reorderRules.product")}
            value={form.product}
            onSelect={onProductSelected}
            onClear={() => onChange({ ...form, product: null })}
            search={searchProducts}
            placeholder={t("productPicker.search")}
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

        <LocationCombobox
          label={t("reorderRules.location")}
          value={form.locationId}
          onChange={(v) => onChange({ ...form, locationId: v })}
          placeholder={t("reorderRules.selectLocation")}
          title={t("reorderRules.location")}
        />

        {/* Each field spans the label, input, description and error rows of one
            shared grid, so a label that wraps to a second line ("Safety
            stock") lowers the inputs of all three together instead of only
            its own, and descriptions of different length cannot shift them. */}
        <div className="grid grid-cols-3 items-stretch gap-x-3 gap-y-1.5">
          <Input
            wrapperClassName={THRESHOLD_FIELD}
            label={t("reorderRules.min")}
            aria-required="true"
            description={t("reorderRules.minDescription")}
            suffix={unit}
            type="number"
            min="0"
            value={form.minQuantity}
            error={submitted ? minQuantityError : undefined}
            onChange={(e) => onChange({ ...form, minQuantity: e.target.value })}
          />
          <Input
            wrapperClassName={THRESHOLD_FIELD}
            label={t("reorderRules.max")}
            aria-required="true"
            description={t("reorderRules.maxDescription")}
            suffix={unit}
            type="number"
            min="0"
            value={form.maxQuantity}
            error={submitted ? maxQuantityError : undefined}
            onChange={(e) => onChange({ ...form, maxQuantity: e.target.value })}
          />
          <Input
            wrapperClassName={THRESHOLD_FIELD}
            label={t("reorderRules.safety")}
            description={t("reorderRules.safetyDescription")}
            suffix={unit}
            type="number"
            min="0"
            value={form.safetyStock}
            onChange={(e) => onChange({ ...form, safetyStock: e.target.value })}
          />
        </div>

        <SearchableCombobox
          label={t("reorderRules.preferredPartner")}
          value={form.preferredPartnerId}
          onChange={(v) => onChange({ ...form, preferredPartnerId: v })}
          placeholder={t("reorderRules.none")}
          searchPlaceholder={t("form.searchPartner")}
          options={partnerOptions}
          onSearchChange={onPartnerSearch}
          loading={partnersLoading}
          clearable
          clearLabel={t("reorderRules.none")}
        />

        <Input
          label={t("reorderRules.notes")}
          value={form.notes}
          onChange={(e) => onChange({ ...form, notes: e.target.value })}
        />
      </SheetBody>

      {/* One footer row, owned by the component (§4.3) — it used to scroll
          away with the form as two `size="sm"` buttons. */}
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
