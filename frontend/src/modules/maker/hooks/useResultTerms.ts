import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { useMakerSettings } from "@/modules/maker/hooks/useRecipes";

export interface ResultTerms {
  label: string;
  definition: string;
}

/**
 * The name of production's result and the one line that says what it is.
 *
 * The number is always the reference price minus the cost to make; the
 * organization's reference direction decides what that price is — a sale
 * price (margin) or a shop price (savings). The same number used to be
 * "Savings" on a card, "Result" on an order and "Monthly result" on the
 * summary, and only the settings screen said they were one thing.
 */
export function resultTerms(
  t: TFunction<"maker">,
  direction: string | null | undefined,
): ResultTerms {
  // Margin is a new organization's direction, so it is also the word
  // shown before the server has said which one this organization uses.
  return direction === "SAVINGS"
    ? {
        label: t("result.savings.label"),
        definition: t("result.savings.definition"),
      }
    : {
        label: t("result.margin.label"),
        definition: t("result.margin.definition"),
      };
}

/** `resultTerms` for screens whose rows do not carry the direction. */
export function useResultTerms(): ResultTerms {
  const { t } = useTranslation("maker");
  const { data: settings } = useMakerSettings();
  return resultTerms(t, settings?.reference_direction);
}
