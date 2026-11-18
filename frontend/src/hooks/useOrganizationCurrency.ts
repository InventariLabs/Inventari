import { useOrganization } from "@/modules/settings/hooks/useOrganization";

/**
 * The currency configured for the current organization, or `undefined` while
 * it is unknown.
 *
 * It does not fall back to "USD": a Polish organization would otherwise see
 * "$0.00" on one card and "PLN 225.00" on the next. `formatMoney` refuses to
 * invent a currency (it renders "0.00 ?"), and this hook refuses too — a wrong
 * currency is worse than a missing one.
 */
export function useOrganizationCurrency(): string | undefined {
  const { data: organization } = useOrganization();
  return organization?.currency ?? undefined;
}
