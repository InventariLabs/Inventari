import { useTranslation } from "react-i18next";
import { formatMoney } from "@/utils/formatters";
import type { Partner } from "@/types";

/**
 * What a partner's turnover column and detail sheet print, from the list item.
 *
 * Three cases the API tells apart: a single-currency total (named by
 * `turnover_currency`), documents that carry no value (a total of zero with
 * no currency — nothing to show, and `formatMoney` would print a zero with a
 * "?" meaning "currency unknown"), and a mix of currencies (no total at all).
 */
export function usePartnerTurnover() {
  const { t, i18n } = useTranslation("partners");
  const lang = i18n.language?.substring(0, 2) ?? "en";
  return (partner: Partner) => {
    if (partner.total_amount != null) {
      if (!partner.turnover_currency && Number(partner.total_amount) === 0) {
        return "—";
      }
      return formatMoney(
        partner.total_amount,
        partner.turnover_currency ?? undefined,
        lang,
      );
    }
    return partner.document_count != null && partner.document_count > 0
      ? t("stats.multipleCurrencies")
      : "—";
  };
}
