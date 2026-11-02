import { useTranslation } from "react-i18next";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { formatMoney } from "@/utils/formatters";

/**
 * Format an amount the way this organization writes money.
 *
 * `formatMoney` takes the currency and the locale as arguments, and a call
 * site that omits them still renders something: a bare number followed by
 * "?" (no currency), grouped and pointed the American way (no locale). Both
 * read as a formatting bug rather than as the missing argument they are, so
 * a whole module went out with "0.00 ?" on a screen that knew the currency,
 * and with "PLN 0.00" where the interface language says "0,00 zł".
 *
 * The hook exists so those two arguments cannot be forgotten: it reads the
 * organization's currency and the interface language, and the call site
 * passes only the amount. Pass `currency` when the amount carries its own —
 * a purchase order in a supplier's currency, an imported price — and it wins
 * over the organization default.
 */
export function useMoney(): (
  amount: number | string | null | undefined,
  currency?: string | null,
) => string {
  const orgCurrency = useOrganizationCurrency();
  const { i18n } = useTranslation();
  const locale = i18n.language || "en";

  return (amount, currency) =>
    formatMoney(amount, currency ?? orgCurrency, locale);
}
