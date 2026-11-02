import {
  Package,
  Tag,
  Calendar,
  AlertTriangle,
  ThermometerSnowflake,
  CheckCircle,
  RefreshCw,
} from "lucide-react";
import type { Item } from "@/types";
import { TranslateFn } from "@/types/i18n";
import { Button } from "@/components/ui/Button";
import { isExpired, isExpiringSoon, formatDate } from "./helpers";
import { formatQuantityValue } from "@/utils/formatters";
import { unitLabel } from "@/lib/i18nHelpers";
import { effectiveExpiry } from "@/module-sdk";

interface Props {
  t: TranslateFn;
  filteredItems: Item[];
  onItemClick: (item: Item) => void;
  onConsumeItem: (itemId: string) => void;
  /** Whether to offer consuming — it asks for `items:write`. */
  canWriteItems?: boolean;
  isConsumePending: boolean;
  consumePendingId: string | undefined;
  getCategoryName: (
    cat: { name: string; code?: string | null } | undefined | null,
    categoryId: string | null | undefined,
  ) => string;
}

export function StorageItemsCards({
  t,
  filteredItems,
  onItemClick,
  onConsumeItem,
  canWriteItems = true,
  isConsumePending,
  consumePendingId,
  getCategoryName,
}: Props) {
  return (
    <div className="grid grid-cols-1 gap-4 md:hidden">
      {filteredItems.map((item: Item) => (
        <div
          key={item.id}
          className="bg-surface-card rounded-2xl border border-border p-4 shadow-sm active:scale-[0.98] transition-all"
          onClick={() => onItemClick(item)}
        >
          <div className="flex gap-4">
            <div className="shrink-0">
              {item.image_url ? (
                <img
                  src={item.image_url}
                  alt={item.name}
                  loading="lazy"
                  className="w-16 h-16 rounded-xl object-cover border border-border"
                />
              ) : (
                <div className="w-16 h-16 bg-surface rounded-xl flex items-center justify-center text-on-muted">
                  <Package size={32} />
                </div>
              )}
            </div>

            <div className="flex-1 min-w-0">
              <div className="flex justify-between items-start gap-2">
                <h3 className="font-semibold text-on truncate leading-tight">
                  {item.name}
                </h3>
                <div className="flex shrink-0 gap-1 items-center">
                  {canWriteItems && (
                    <Button
                      variant="ghost"
                      size="iconSm"
                      onClick={(e) => {
                        e.stopPropagation();
                        onConsumeItem(item.id);
                      }}
                      disabled={
                        isConsumePending && consumePendingId === item.id
                      }
                      aria-label={t("items:actions.consume", {
                        defaultValue: "Remove",
                      })}
                      className="bg-accent-50 text-accent-600 border border-accent-100 active:scale-90"
                    >
                      {isConsumePending && consumePendingId === item.id ? (
                        <RefreshCw size={14} className="animate-spin" />
                      ) : (
                        <CheckCircle size={14} />
                      )}
                    </Button>
                  )}
                  {/* "—" rather than "pcs" for a product that records no
                      unit: the invented unit turned 500 g into 500 pieces,
                      and the products list already says it this way. */}
                  <div className="bg-primary-50 px-2 py-1 rounded-lg text-[10px] font-medium text-primary-700 whitespace-nowrap border border-primary-100">
                    {formatQuantityValue(item.quantity, item.uom?.rounding)}{" "}
                    <span className="font-medium">
                      {unitLabel(t, item.uom?.symbol) || "—"}
                    </span>
                  </div>
                </div>
              </div>

              {item.brand && (
                <p className="text-xs text-on-secondary uppercase font-medium tracking-wide">
                  {item.brand}
                </p>
              )}

              <div className="mt-2 flex flex-wrap gap-2">
                <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-surface-raised rounded-full text-[10px] font-medium text-on-secondary uppercase">
                  <Tag size={10} />
                  {getCategoryName(item.category, item.category_id)}
                </span>
                <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-primary-50 rounded-full text-[10px] font-medium text-primary-700">
                  {formatQuantityValue(item.quantity, item.uom?.rounding)}{" "}
                  {unitLabel(t, item.uom?.symbol) || "—"}
                </span>
              </div>
            </div>
          </div>

          {(effectiveExpiry(item) || item.freeze_date) && (
            <div className="mt-3 flex items-center justify-between text-[10px] font-medium uppercase tracking-widest">
              {item.freeze_date ? (
                <div className="flex items-center gap-1.5 text-primary-600">
                  <ThermometerSnowflake size={12} />
                  <span>{formatDate(item.freeze_date)}</span>
                </div>
              ) : (
                <div></div>
              )}

              {effectiveExpiry(item) && (
                <div
                  className={`flex items-center gap-1.5 ${
                    isExpired(effectiveExpiry(item))
                      ? "text-red-600"
                      : isExpiringSoon(effectiveExpiry(item))
                        ? "text-orange-600"
                        : "text-on-muted"
                  }`}
                >
                  <Calendar size={12} />
                  <span
                    className={
                      isExpired(effectiveExpiry(item)) ? "line-through" : ""
                    }
                  >
                    {formatDate(effectiveExpiry(item))}
                  </span>
                  {isExpired(effectiveExpiry(item)) && (
                    <AlertTriangle size={12} />
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
