import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ChoiceGroup } from "@/components/ui/ChoiceGroup";
import { DateInput } from "@/components/ui/DateInput";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { useFormGuard } from "@/module-sdk";
import { ProductSearchInput } from "@/modules/maker/components/ProductSearchInput";
import { SelectedProductCard } from "@/modules/maker/components/SelectedProductCard";
import { IngredientBatchPicker } from "@/modules/maker/components/IngredientBatchPicker";
import { useIsHomeProfile } from "@/modules/maker/hooks/useIsHomeProfile";
import { todayIso } from "@/utils/formatters";
import type { ProductionForm } from "@/modules/maker/hooks/useProductionSheet";
import type { ProductionMode } from "@/modules/maker/types/maker";

interface ProductionRunFieldsProps {
  form: ProductionForm;
  /** The location picker, which the sheet builds from the locations module. */
  locationField: ReactNode;
  onShowPreview: () => void;
  onShowPricing: () => void;
}

/** The left half of the production sheet: what, how much, where, when. */
export function ProductionRunFields({
  form,
  locationField,
  onShowPreview,
  onShowPricing,
}: ProductionRunFieldsProps) {
  const { t } = useTranslation("maker");
  const home = useIsHomeProfile();
  // What the reader typed goes with a navigation the palette or a tab
  // starts over the sheet; the guard asks first. Saving leaves by its own
  // navigation, which the guard does not stand in.
  useFormGuard(
    form.qty !== "" ||
      form.notes.trim() !== "" ||
      form.outputLotName.trim() !== "",
    t("create.guardName"),
  );

  return (
    <div className="space-y-5 min-w-0">
      {form.canRecordMade && (
        <ChoiceGroup
          label={t("create.mode.label")}
          options={[
            { id: "made", label: t("create.mode.made") },
            { id: "planned", label: t("create.mode.planned") },
          ]}
          value={form.mode}
          onChange={(id) => form.setMode(id as ProductionMode)}
        />
      )}

      {form.selected ? (
        <SelectedProductCard
          product={form.selected}
          onChange={() => form.setSelected(null)}
        />
      ) : (
        <ProductSearchInput
          onSelect={form.setSelected}
          label={t("create.productLabel")}
          testId="maker-create-search"
          formulaBadge
        />
      )}

      <Input
        type="number"
        step="any"
        min="0"
        label={
          form.mode === "made" ? t("create.qtyLabelMade") : t("create.qtyLabel")
        }
        suffix={form.unit ?? undefined}
        description={form.batchHint}
        value={form.qty}
        onChange={(e) => form.setQty(e.target.value)}
        data-testid="maker-create-qty-input"
      />

      {locationField}

      {/* A named batch is what lets a recall of an ingredient follow this
          run on to the customers of what it made. A run nobody names one
          for names its own, so a home is never asked. */}
      {!home && (
        <Input
          label={t("create.outputLotLabel")}
          description={t("create.outputLotHint")}
          value={form.outputLotName}
          onChange={(e) => form.setOutputLotName(e.target.value)}
          maxLength={100}
          data-testid="maker-create-output-lot-input"
        />
      )}

      {form.mode === "made" && (
        <div className="space-y-1">
          <DateInput
            id="maker-create-best-before"
            label={t("batches.bestBeforeLabel")}
            value={form.bestBefore}
            onChange={form.setBestBefore}
            min={todayIso()}
            presets={["plus6Months", "plus1Year"]}
          />
          <p className="text-xs text-on-muted">
            {form.shelfLifeDays
              ? t("batches.bestBeforeFromShelfLife", {
                  count: form.shelfLifeDays,
                })
              : t(
                  home
                    ? "batches.bestBeforeNoShelfLifeHome"
                    : "batches.bestBeforeNoShelfLife",
                )}
          </p>
        </div>
      )}

      {form.mode === "planned" && (
        <DateInput
          label={t("create.dateLabel")}
          value={form.productionDate}
          onChange={form.setProductionDate}
        />
      )}

      {/* Cost details and the price calculator inspect what is on the
          form; they are tools, not ways to finish. Keeping them here
          leaves the footer with one thing to press. */}
      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={onShowPreview}
          disabled={!form.canPreview}
          data-testid="maker-create-preview-button"
        >
          {t("create.preview")}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={onShowPricing}
          // An empty quantity prices one unit (the calculator's default).
          disabled={!form.selected}
          leftIcon={<Sparkles size={16} />}
          data-testid="maker-create-pricing-button"
        >
          {t("pricing.openButton")}
        </Button>
      </div>

      {form.mode === "made" && <IngredientBatchPicker choice={form.batches} />}

      <Textarea
        wrapperClassName="space-y-2"
        label={t("create.notesLabel")}
        value={form.notes}
        onChange={(e) => form.setNotes(e.target.value)}
        rows={3}
        className="w-full px-3 py-2 rounded-lg border border-border bg-surface-card text-sm text-on focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500"
        placeholder={t("create.notesPlaceholder")}
      />

      {!form.canPreview && (
        <Card className="p-3 text-xs text-on-secondary bg-surface-raised border-border">
          {form.requirements.map((requirement) => (
            <p key={requirement}>{requirement}</p>
          ))}
        </Card>
      )}
    </div>
  );
}
