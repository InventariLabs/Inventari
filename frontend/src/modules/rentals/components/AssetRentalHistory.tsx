import { useTranslation } from "react-i18next";

import type { SlotDataMap } from "@/module-sdk";

import { RentalHistorySection } from "./RentalHistorySection";

/**
 * An asset's rentals — contributed to the equipment asset's timeline tab.
 *
 * The asset page knows the item; the bookings are the rentals module's
 * records, so they arrive here through `asset_detail_extra` rather than an
 * import (frontend/AGENTS.md §7). Each row names who borrowed the asset.
 */
export function AssetRentalHistory({
  data,
}: {
  data: SlotDataMap["asset_detail_extra"];
}) {
  const { t } = useTranslation("rentals");

  return (
    <RentalHistorySection
      sectionLabel={`${t("history.title")} — ${data.itemName}`}
      heading={t("history.assetTitle")}
      emptyTitle={t("history.emptyAsset")}
      params={{ item_id: data.itemId }}
      viewAllTo={`/rentals/bookings?item_id=${data.itemId}`}
      showBorrower
    />
  );
}
