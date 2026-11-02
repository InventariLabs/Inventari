import { useTranslation } from "react-i18next";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { DateInput } from "@/components/ui/DateInput";
import { Textarea } from "@/components/ui/Textarea";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import type { EquipmentFormData } from "../pages/AddEquipmentPage";

interface PurchaseNotesSectionProps {
  form: EquipmentFormData;
  onSet: (field: keyof EquipmentFormData, value: string) => void;
}

export function PurchaseNotesSection({
  form,
  onSet,
}: PurchaseNotesSectionProps) {
  const { t } = useTranslation("equipment");
  const currency = useOrganizationCurrency();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {t("form.sections.purchase", "Purchase & Notes")}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 items-end gap-4">
          {/* The label is the component's, not hand-rolled: an inline label
              sits in a line box the wrapper's line-height sizes, which left
              this field about 8px below the date field beside it in the same
              grid row. The currency rides inside the control for the same
              reason — a sibling box next to the input made the pair as tall as
              label plus field, and the row went with it. */}
          <Input
            id="purchase-price"
            label={t("form.fields.purchasePrice", "Purchase Price")}
            type="number"
            min="0"
            step="0.01"
            value={form.purchase_price}
            onChange={(e) => onSet("purchase_price", e.target.value)}
            placeholder="0.00"
            aria-describedby="purchase-price-currency"
            rightIcon={
              /* make the currency explicit next to the amount. It is
                 the unit of the number, so it is described to a screen reader
                 rather than hidden from it. */
              <span
                id="purchase-price-currency"
                className="text-sm font-semibold text-on-secondary"
              >
                {currency}
              </span>
            }
          />
          <DateInput
            id="purchase-date"
            label={t("form.fields.purchaseDate", "Purchase Date")}
            value={form.purchase_date}
            onChange={(value) => onSet("purchase_date", value)}
          />
        </div>

        <DateInput
          id="warranty-until"
          label={t("form.fields.warrantyUntil", "Warranty Until")}
          value={form.warranty_until}
          onChange={(value) => onSet("warranty_until", value)}
          presets={["plus1Year", "plus6Months", "plus3Months"]}
        />

        <Textarea
          label={t("form.sections.notes", "Notes")}
          id="notes"
          value={form.notes}
          onChange={(e) => onSet("notes", e.target.value)}
          rows={3}
          placeholder={t(
            "form.placeholders.notes",
            "Additional notes, assignment info…",
          )}
          className="w-full rounded-lg border border-border bg-surface-card text-on px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500 resize-none placeholder:text-on-muted"
        />
      </CardContent>
    </Card>
  );
}
