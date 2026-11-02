import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ChoiceGroup } from "@/components/ui/ChoiceGroup";
import { DateInput } from "@/components/ui/DateInput";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { ProductSearchInput } from "@/modules/maker/components/ProductSearchInput";
import { SelectedProductCard } from "@/modules/maker/components/SelectedProductCard";
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

  return (
    <div className="space-y-5 min-w-0">
      <ChoiceGroup
        label={t("create.mode.label")}
        options={[
          { id: "made", label: t("create.mode.made") },
          { id: "planned", label: t("create.mode.planned") },
        ]}
        value={form.mode}
        onChange={(id) => form.setMode(id as ProductionMode)}
      />

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
