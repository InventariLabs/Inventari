import { memo } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Monitor } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Checkbox } from "@/components/ui/Checkbox";
import { DynamicIcon } from "@/components/ui/DynamicIcon";
import { AssetStatusBadge } from "./AssetStatusBadge";
import { getEquipmentMeta } from "./assetUtils";
import type { EquipmentAssetItem } from "@/modules/equipment/api/equipment_assets";
import { getCategoryLabel } from "@/modules/equipment/components/assetUtils";
import type { AssetImage } from "@/modules/equipment/hooks/useAssetImage";

interface AssetCardProps {
  item: EquipmentAssetItem;
  /** False drops the checkbox — the bulk actions it feeds are gone. */
  selectable?: boolean;
  isSelected: boolean;
  onToggleSelect: (id: string) => void;
  /** Resolved by the list, so one query serves every row. */
  image: AssetImage | null;
  /** Resolved by the list, in the reader's language (seeded locations). */
  locationName: string | null;
}

export const AssetCardRow = memo(function AssetCardRow({
  item,
  selectable = true,
  isSelected,
  onToggleSelect,
  image,
  locationName,
}: AssetCardProps) {
  const { t } = useTranslation("equipment");
  const meta = getEquipmentMeta(item);
  const person = item.holder_kind === "location" ? null : item.holder_name;

  return (
    <Card
      data-testid="asset-card"
      /* `relative` is the containing block for the title link's overlay:
         the card is clickable from anywhere without a `<div onClick>`. */
      className={`relative p-3 sm:p-4 cursor-pointer hover:bg-surface-raised transition-colors ${isSelected ? "ring-2 ring-primary-300 bg-primary-50/50 dark:bg-primary-900/10" : ""}`}
    >
      <div className="flex items-start gap-3 sm:gap-4">
        {selectable && (
          /* Above the stretched link, or the overlay would answer the tap
             and open the record instead of ticking the row. */
          /* The 16px box sits in a 44px label on a phone, so the tap lands
             on the row's tick and not beside it. */
          <label
            htmlFor={`asset-select-${item.id}`}
            className="relative z-10 -m-3 flex h-11 w-11 flex-shrink-0 cursor-pointer items-center justify-center sm:m-0 sm:h-auto sm:w-auto sm:pt-0.5"
          >
            <span className="sr-only">
              {t("list.select_item", { name: item.name })}
            </span>
            <Checkbox
              id={`asset-select-${item.id}`}
              checked={isSelected}
              onChange={() => onToggleSelect(item.id)}
              className="text-primary-600 focus:ring-primary-500"
            />
          </label>
        )}
        <div className="flex-shrink-0">
          {image ? (
            <img
              src={image.url}
              alt={item.name}
              loading="lazy"
              className="w-9 h-9 rounded-lg object-cover border border-border"
            />
          ) : (
            <div className="w-9 h-9 rounded-lg bg-primary-50 dark:bg-primary-900/30 flex items-center justify-center">
              {item.category?.icon ? (
                <DynamicIcon
                  name={item.category.icon}
                  size={18}
                  className="text-primary-500"
                />
              ) : (
                <Monitor size={18} className="text-primary-500" />
              )}
            </div>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            {/* The card's one destination. Below `md:` these cards are the
                whole list, and as a `<span>` inside a `Card onClick` the
                name had no role, no focus and no href — Tab jumped from the
                checkbox straight out of the card, so no asset could be
                opened with a keyboard on a phone. The link is stretched
                over the card by a pseudo-element (§2.3a): the surface
                still opens the record, and the keyboard reaches it. */}
            <Link
              to={`/equipment/${item.id}`}
              className="min-w-0 truncate rounded-sm font-medium text-sm text-on after:absolute after:inset-0 after:content-[''] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/40"
            >
              {item.name}
            </Link>
            <span className="flex-shrink-0 ml-auto sm:ml-0">
              <AssetStatusBadge
                status={meta.status}
                className="px-1.5 py-px text-[10px] sm:px-2 sm:py-0.5 sm:text-[10px]"
              />
            </span>
          </div>
          <div className="mt-0.5 text-xs text-on-muted truncate">
            {meta.serial_number && (
              <span className="font-mono">{meta.serial_number}</span>
            )}
            {!meta.serial_number && meta.asset_tag && (
              <span className="font-mono">#{meta.asset_tag}</span>
            )}
            <span className="hidden sm:inline">
              {meta.manufacturer && <> {meta.manufacturer}</>}
              {meta.model && <> {meta.model}</>}
              {item.category?.name && (
                <> {getCategoryLabel(t, item.category)}</>
              )}
            </span>
          </div>
          {/* location and current holder answer "where is it" and
              "who has it" straight from the card, in the desktop table's
              words. For an asset checked out to a place the list reports
              that place as its location, so the place is said once. */}
          {(locationName || person) && (
            <div className="mt-1 text-xs text-on-muted truncate">
              {locationName && <span>{locationName}</span>}
              {locationName && person && <span aria-hidden="true"> · </span>}
              {person && (
                <span>{t("list.assignedToName", { name: person })}</span>
              )}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
});
