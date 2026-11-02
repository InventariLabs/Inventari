import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Hammer, Save } from "lucide-react";
import { Sheet } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/Button";
import { QueryFailure } from "@/components/ui/QueryResult";
import { StorageRequired } from "@/modules/shared/components/StorageRequired";
import { useLocationOffer } from "@/module-sdk";
import { LocationCombobox } from "@/module-sdk";
import {
  useProductionForm,
  useProductionSave,
  type PreselectedProduct,
} from "@/modules/maker/hooks/useProductionSheet";
import { ProductionPreviewSheet } from "./ProductionPreviewSheet";
import { PricingCalculator } from "./PricingCalculator";
import { ShortageModal } from "./ShortageModal";
import { ProductionNeedsPanel } from "./ProductionNeedsPanel";
import { ProductionRunFields } from "./ProductionRunFields";

interface ProductionCreateSheetProps {
  open: boolean;
  onClose: () => void;
  onSuccess?: (orderId: string) => void;
  /**
   * Pre-selects the output product when the sheet opens (e.g. the
   * [Wyprodukuj] action on a formula card). recipe_id is sent with the
   * order as long as the user keeps the preselected product.
   */
  preselectedProduct?: PreselectedProduct;
}

/**
 * "I made it" and "I plan to make it" on one sheet.
 *
 * Recording 20 kg made used to be five steps — a draft, its page, a
 * completion — with the quantity defaulting to one of nothing in particular,
 * and the shortage first heard of at "Create draft". The quantity is now in
 * the product's own unit; what the run takes, what is short and what it
 * costs stand beside the form while it is filled; and "Already made" saves
 * the finished run in one step.
 */
export function ProductionCreateSheet({
  open,
  onClose,
  onSuccess,
  preselectedProduct,
}: ProductionCreateSheetProps) {
  const { t } = useTranslation("maker");
  // What may hold stock, never a place a module owns — asked with the
  // flow's own purpose at the query, or an empty picker here would still
  // blame the module-data switch, which reveals nothing in a stock flow.
  const locations = useLocationOffer({ purpose: "stock" });
  const form = useProductionForm(open, locations, preselectedProduct);
  const { save, isSaving, shortageState, setShortageState } = useProductionSave(
    form,
    { onClose, onSuccess },
  );
  const [showPreview, setShowPreview] = useState(false);
  const [showPricing, setShowPricing] = useState(false);

  useEffect(() => {
    if (open) return;
    setShowPreview(false);
    setShowPricing(false);
    setShortageState(null);
  }, [open, setShortageState]);

  const heading =
    form.mode === "made"
      ? t("create.needs.headingMade")
      : t("create.needs.headingPlanned");
  // The button must not offer what the server refuses, and the notice beside
  // the form already says why: no BOM refuses both modes (nothing to plan
  // from); a BOM that lists no ingredients refuses a run saved as made — it
  // would create its output out of nothing. A planned draft of it is
  // accepted, and its completion is refused until ingredients are added.
  const recipeState = form.preview.data?.recipe_state;
  let blockedReason: string | null = null;
  if (recipeState === "no_recipe") blockedReason = t("create.submitNeedsBom");
  else if (recipeState === "empty" && form.mode === "made")
    blockedReason = t("create.submitNeedsIngredients");
  let submitLabel = t("create.submitPlanned");
  if (isSaving) submitLabel = t("create.creating");
  else if (form.mode === "made") submitLabel = t("create.submitMade");

  return (
    <>
      <Sheet
        open={open}
        onClose={onClose}
        maxWidth="4xl"
        aria-label={t("create.title")}
      >
        <div className="px-6 pt-6 pb-4 border-b border-border">
          <div className="flex items-center gap-2 text-lg font-semibold text-on">
            <Hammer size={20} />
            {t("create.title")}
          </div>
          <p className="text-sm text-on-muted mt-1">{t("create.subtitle")}</p>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto p-6 grid gap-6 md:grid-cols-2">
          <ProductionRunFields
            form={form}
            locationField={
              <LocationField
                locations={locations}
                value={form.storageId}
                onChange={form.setStorageId}
              />
            }
            onShowPreview={() => setShowPreview(true)}
            onShowPricing={() => setShowPricing(true)}
          />
          <section
            className="min-w-0 md:border-l md:border-border md:pl-6"
            aria-label={heading}
            data-testid="maker-create-needs"
          >
            <ProductionNeedsPanel
              mode={form.mode}
              payload={form.payload}
              preview={form.preview.data}
              isLoading={form.preview.isFetching}
              error={form.preview.error ?? null}
              outputProduct={form.selected}
            />
          </section>
        </div>

        <div
          className="px-6 py-4 border-t border-border flex items-center justify-between gap-3"
          data-testid="maker-create-footer"
        >
          <Button variant="ghost" onClick={onClose}>
            {t("create.cancel")}
          </Button>
          <div className="flex items-center gap-3">
            {blockedReason && (
              <p
                id="maker-create-submit-reason"
                className="text-sm text-on-secondary"
              >
                {blockedReason}
              </p>
            )}
            <Button
              onClick={() => save(false)}
              disabled={!form.canPreview || isSaving || !!blockedReason}
              aria-describedby={
                blockedReason ? "maker-create-submit-reason" : undefined
              }
              leftIcon={<Save size={16} />}
              data-testid="maker-create-submit-button"
            >
              {submitLabel}
            </Button>
          </div>
        </div>
      </Sheet>

      <ProductionPreviewSheet
        open={showPreview}
        onClose={() => setShowPreview(false)}
        breakdown={form.preview.data}
        isLoading={form.preview.isFetching && !form.preview.data}
        error={form.preview.error ?? null}
        outputProduct={form.selected}
      />

      <PricingCalculator
        open={showPricing}
        onClose={() => setShowPricing(false)}
        templateId={form.selected?.product_template_id}
        producedQty={
          Number.isNaN(form.parsedQty) || form.parsedQty <= 0
            ? "1"
            : String(form.parsedQty)
        }
        product={form.selected}
      />

      {shortageState && (
        <ShortageModal
          open={!!shortageState}
          variant={shortageState.variant}
          shortages={shortageState.shortages}
          canConfirm={shortageState.variant === "warning"}
          onConfirm={
            shortageState.variant === "warning"
              ? () => {
                  setShortageState(null);
                  save(true);
                }
              : undefined
          }
          onCancel={() => setShortageState(null)}
        />
      )}
    </>
  );
}

/**
 * Where the run's output goes.
 *
 * The picker never leaves the form: an organization whose locations are all
 * kept out of general lists still gets the control, and the way forward sits
 * under it — create a location in place, or bring the module's own back via
 * the settings switch the note names. Replacing the field with a banner left
 * the hint below asking for a control that was not on the screen.
 */
function LocationField({
  locations,
  value,
  onChange,
}: {
  locations: ReturnType<typeof useLocationOffer>;
  value: string;
  onChange: (id: string) => void;
}) {
  const { t } = useTranslation("maker");
  return (
    <>
      {locations.isError ? (
        <QueryFailure
          error={locations.error}
          onRetry={() => locations.refetch()}
        />
      ) : (
        <LocationCombobox
          id="maker-create-storage"
          label={t("create.storageLabel")}
          scope={{ purpose: "stock" }}
          value={value}
          onChange={onChange}
          title={t("create.storageLabel")}
          placeholder={t("create.storagePlaceholder")}
          searchPlaceholder={t("create.storageSearchPlaceholder")}
          emptyMessage={t("create.storageEmpty")}
        />
      )}
      {/* On a failed load the list is undefined, so the note cannot show
          over the QueryFailure — no separate guard needed. */}
      {locations.total === 0 && (
        <StorageRequired
          variant="field"
          purpose="stock"
          onCreated={(storage) => onChange(storage.id)}
        />
      )}
    </>
  );
}
