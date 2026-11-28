import { useTranslation } from "react-i18next";

import type { SlotDataMap } from "@/module-sdk";

import { RentalHistorySection } from "./RentalHistorySection";

/**
 * A partner's rentals — contributed to the partner detail sheet.
 *
 * A slot, not an import: the partner sheet belongs to Partners and the
 * bookings belong to Rentals, and modules do not reach into each other
 * (frontend/AGENTS.md §7). The sheet renders `partner_detail_extra` and this
 * is the rentals module's contribution to it.
 */
export function PartnerRentalHistory({
  data,
}: {
  data: SlotDataMap["partner_detail_extra"];
}) {
  const { t } = useTranslation("rentals");

  return (
    <RentalHistorySection
      sectionLabel={`${t("history.title")} — ${data.partnerName}`}
      heading={t("history.partnerTitle")}
      emptyTitle={t("history.emptyPartner")}
      params={{ partner_id: data.partnerId }}
      viewAllTo={`/rentals/bookings?partner_id=${data.partnerId}`}
      headingLevel="h3"
    />
  );
}
