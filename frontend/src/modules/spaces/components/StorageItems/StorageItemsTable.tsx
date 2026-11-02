import {
  Package,
  Tag,
  Calendar,
  AlertTriangle,
  TrendingDown,
  Edit2,
  Trash2,
  RefreshCw,
  CheckCircle,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import type { Item } from "@/types";
import { TranslateFn } from "@/types/i18n";
import { isExpired, isExpiringSoon, formatDate } from "./helpers";
import { formatQuantityValue } from "@/utils/formatters";
import { unitLabel } from "@/lib/i18nHelpers";
import { effectiveExpiry } from "@/module-sdk";

interface Props {
  t: TranslateFn;
  filteredItems: Item[];
  /** ``StorageType.behavior_mode`` of the location — what it does, not what
      it is called. A type code would tie this table to one vertical's
      vocabulary; the mode is a property every type carries. */
  behaviorMode?: string;
  onItemClick: (item: Item) => void;
  onConsumeItem: (itemId: string) => void;
  onEditItem: (itemId: string) => void;
  onDeleteItem: (item: Item) => void;
  /** Whether to offer the row actions — all three ask for `items:write`. */
  canWriteItems?: boolean;
  isConsumePending: boolean;
  consumePendingId: string | undefined;
  isDeletePending: boolean;
  getCategoryName: (
    cat: { name: string; code?: string | null } | undefined | null,
    categoryId: string | null | undefined,
  ) => string;
}

export function StorageItemsTable({
  t,
  filteredItems,
  behaviorMode,
  onItemClick,
  onConsumeItem,
  onEditItem,
  onDeleteItem,
  canWriteItems = true,
  isConsumePending,
  consumePendingId,
  isDeletePending,
  getCategoryName,
}: Props) {
  const isFreezing = behaviorMode === "FREEZING";

  return (
    <div className="hidden md:block bg-surface-card rounded-xl shadow-sm border overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-surface border-b">
            {/* The products list fixes its header row on the row, not on
                seven cells — the same one class, read once (§1.2). */}
            <tr className="text-xs font-medium uppercase tracking-wider text-on-muted">
              <th className="px-4 py-3 text-left">
                {t("locations:detail.table.product")}
              </th>
              <th className="px-4 py-3 text-left">
                {t("locations:detail.table.category")}
              </th>
              <th className="px-4 py-3 text-left">
                {t("locations:detail.table.quantity")}
              </th>
              <th className="px-4 py-3 text-left">
                {isFreezing
                  ? t("locations:detail.table.freezeDate")
                  : t("locations:detail.table.storageDate")}
              </th>
              <th className="px-4 py-3 text-left">
                {t("locations:detail.table.expiryDate")}
              </th>
              <th className="px-4 py-3 text-left">
                {t("locations:detail.table.location")}
              </th>
              <th className="px-4 py-3 text-right">
                {t("locations:detail.table.actions")}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {filteredItems.map((item: Item) => (
              <tr key={item.id} className="hover:bg-surface">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-3">
                    {item.image_url ? (
                      <img
                        src={item.image_url}
                        alt={item.name}
                        loading="lazy"
                        className="w-10 h-10 rounded-lg object-cover"
                      />
                    ) : (
                      <div className="w-10 h-10 bg-surface-raised rounded-lg flex items-center justify-center">
                        <Package size={20} className="text-on-muted" />
                      </div>
                    )}
                    <div
                      className="cursor-pointer group"
                      onClick={() => onItemClick(item)}
                    >
                      <p className="text-sm font-semibold text-on group-hover:text-primary-600 transition-colors">
                        {item.name}
                      </p>
                      {item.description && (
                        <p className="text-[10px] text-on-muted italic line-clamp-1">
                          {item.description}
                        </p>
                      )}
                      {item.brand && (
                        <p className="text-sm text-on-secondary">
                          {item.brand}
                        </p>
                      )}
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className="inline-flex items-center gap-1 px-2 py-1 bg-surface-raised rounded text-sm">
                    <Tag size={14} />
                    {getCategoryName(item.category, item.category_id)}
                  </span>
                </td>
                <td className="px-4 py-3">
                  {/* The unit slot says "—" for a product that records no
                      unit, the way the products list does. Standing "pcs"
                      in for a missing unit reads 500 g of something as 500
                      pieces — and 2661 of 3243 products record none. */}
                  <div className="flex items-center gap-1">
                    <span className="text-sm tabular-nums text-on">
                      {formatQuantityValue(item.quantity, item.uom?.rounding)}
                    </span>
                    <span
                      className="text-xs font-medium text-on-muted"
                      title={
                        item.uom?.symbol
                          ? undefined
                          : t("items:stock.noUnitRecorded")
                      }
                    >
                      {unitLabel(t, item.uom?.symbol) || "—"}
                    </span>
                  </div>
                </td>
                <td className="px-4 py-3">
                  {(() => {
                    // The header above says what this column is; the cell has
                    // to agree with it. Outside a freezer the column is
                    // "Added", and the date it means is the one the detail
                    // page shows under that name.
                    const date = isFreezing
                      ? item.freeze_date
                      : item.added_date;
                    return date ? (
                      <div className="flex items-center gap-1 text-xs text-on-secondary">
                        <Calendar size={14} />
                        <span>{formatDate(date)}</span>
                      </div>
                    ) : (
                      <span className="text-xs text-on-muted">-</span>
                    );
                  })()}
                </td>
                <td className="px-4 py-3">
                  {effectiveExpiry(item) ? (
                    <div
                      className={`flex items-center gap-1 text-xs ${
                        isExpired(effectiveExpiry(item))
                          ? "text-red-600"
                          : isExpiringSoon(effectiveExpiry(item))
                            ? "text-orange-600"
                            : "text-on-secondary"
                      }`}
                    >
                      <Calendar size={14} />
                      <span
                        className={
                          isExpired(effectiveExpiry(item)) ? "line-through" : ""
                        }
                      >
                        {formatDate(effectiveExpiry(item))}
                      </span>
                      {isExpired(effectiveExpiry(item)) && (
                        <AlertTriangle size={14} />
                      )}
                      {isExpiringSoon(effectiveExpiry(item)) &&
                        !isExpired(effectiveExpiry(item)) && (
                          <TrendingDown size={14} />
                        )}
                    </div>
                  ) : (
                    <span className="text-xs text-on-muted">-</span>
                  )}
                </td>
                <td className="px-4 py-3 text-xs text-on-secondary">
                  {item.shelf_location || "-"}
                </td>
                <td className="px-4 py-3 text-right">
                  {canWriteItems && (
                    <div className="flex justify-end gap-2">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => onConsumeItem(item.id)}
                        disabled={
                          isConsumePending && consumePendingId === item.id
                        }
                        className="text-on-muted hover:text-accent-600 hover:bg-accent-50 active:bg-accent-50"
                        title={t("items:actions.consume", {
                          defaultValue: "Remove",
                        })}
                        aria-label={t("items:actions.consume", {
                          defaultValue: "Remove",
                        })}
                      >
                        {isConsumePending && consumePendingId === item.id ? (
                          <RefreshCw size={16} className="animate-spin" />
                        ) : (
                          <CheckCircle size={16} />
                        )}
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => onEditItem(item.id)}
                        className="text-primary-600 hover:bg-primary-50 active:bg-primary-50"
                        title={t("items:actions.edit")}
                        aria-label={t("items:actions.edit")}
                      >
                        <Edit2 size={16} />
                      </Button>
                      <Button
                        variant="ghostDanger"
                        size="icon"
                        onClick={() => onDeleteItem(item)}
                        disabled={isDeletePending}
                        title={t("items:actions.delete")}
                        aria-label={t("items:actions.delete")}
                      >
                        <Trash2 size={16} />
                      </Button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
