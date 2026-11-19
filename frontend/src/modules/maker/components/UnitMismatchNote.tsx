import { AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";

/**
 * The marker on a BOM line whose unit cannot be read as the ingredient's
 * stock unit.
 *
 * A run refuses such a line until it names a unit that converts, so the
 * composition tab says which row needs one — beside the quantity and unit it
 * cannot read — instead of letting the run's refusal be the first word.
 */
export function UnitMismatchNote() {
  const { t } = useTranslation("maker");
  return (
    <div className="basis-full flex justify-end">
      <span
        className="flex items-start gap-1.5 text-xs text-on-warning"
        data-testid="maker-composition-unit-mismatch"
      >
        <AlertTriangle size={12} className="mt-0.5 shrink-0" />
        {t("composition.unitMismatch")}
      </span>
    </div>
  );
}
