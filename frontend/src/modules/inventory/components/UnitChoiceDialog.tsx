import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { unitLabel } from "@/lib/i18nHelpers";
import type { PendingUnitChoice } from "@/modules/inventory/hooks/useItemForm";

interface Props {
  /** The chosen unit the matched template does not keep, waiting on the reader. */
  choice: PendingUnitChoice;
  /** The reader's answer: `true` keeps the chosen unit, `false` reverts. */
  onResolve: (confirmed: boolean) => void;
}

/**
 * "This product is kept in kilograms — enter it in grams anyway?"
 *
 * The question exists because the server refuses the answer nobody asked for:
 * the matched product template's unit is the reference, and a quantity typed
 * in another one is converted into it on saving — a picker left on grams from
 * the previous product would turn two kilograms into two grams, so the choice
 * has to be confirmed, and it is recorded.
 * Asking here, where both units can be named together, is what keeps that
 * rule from reaching the reader as an unexplained refusal after the save.
 */
export function UnitChoiceDialog({ choice, onResolve }: Props) {
  const { t } = useTranslation(["items", "common"]);
  const templateUnit = unitLabel(t, choice.template.uomSymbol);
  const chosenUnit = unitLabel(t, choice.chosenSymbol);

  return (
    <ConfirmDialog
      open
      title={t("items:unitChoice.title", {
        product: choice.template.productName,
      })}
      message={t("items:unitChoice.message", {
        product: choice.template.productName,
        template_unit: templateUnit,
        chosen_unit: chosenUnit,
      })}
      confirmLabel={t("items:unitChoice.keepChosen", { unit: chosenUnit })}
      cancelLabel={t("items:unitChoice.keepTemplate", { unit: templateUnit })}
      variant="warning"
      onConfirm={() => onResolve(true)}
      onCancel={() => onResolve(false)}
    />
  );
}
