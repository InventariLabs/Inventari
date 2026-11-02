import { useTranslation } from "react-i18next";
import type { Item } from "@/types";
import type { StockTakeItem } from "@/modules/stock_takes/types/stock-takes";
import { Badge } from "@/components/ui/Badge";
import { categoryLabel } from "@/lib/i18nHelpers";
import { recordMarks, type Twin } from "@/modules/stock_takes/recordMarks";

interface Props {
  itemId: string;
  item: Item | undefined;
  stockTakeItem: StockTakeItem | undefined;
  savedCount: number | null;
  discrepancy: "missing" | "surplus" | null;
  twin?: Twin | null;
  isUnsaved: boolean;
  awaitingRecount: boolean;
}

/**
 * Title row of a counting card: product name (with fallback to the
 * snapshot name), location code, the batch and expiry that tell the record
 * from its twins, "counted 0" badge, the unsaved marker and the discrepancy
 * badge.
 *
 * The badges read the saved count, never the input box. A row whose box
 * holds a number nobody saved looked exactly like a saved one — same
 * "Counted: 20", same computed difference — and the number was gone on the
 * way back from the door. The brand-coloured marker is the same hue as the
 * save button that is waiting for it.
 */
export default function StockTakeItemCardHeader({
  itemId,
  item,
  stockTakeItem,
  savedCount,
  discrepancy,
  twin,
  isUnsaved,
  awaitingRecount,
}: Props) {
  const { t } = useTranslation(["stock_takes"]);
  return (
    <div>
      <div className="flex items-center gap-2 flex-wrap">
        <h3 className="font-semibold text-on">
          {item?.name ?? stockTakeItem?.item_name ?? `Item ${itemId}`}
        </h3>
        {stockTakeItem?.shelf_location && (
          <span className="text-xs text-on-secondary font-mono bg-surface-raised px-1.5 py-0.5 rounded">
            {stockTakeItem.shelf_location}
          </span>
        )}
        {recordMarks(t, item, stockTakeItem, twin).map((mark) => (
          <span key={mark} className="text-xs text-on-secondary">
            {mark}
          </span>
        ))}
        {savedCount === 0 && (
          <Badge variant="warning">{t("countedZero")}</Badge>
        )}
        {isUnsaved && <Badge>{t("item.unsaved")}</Badge>}
        {awaitingRecount && (
          <Badge variant="info">{t("item.awaitingRecount")}</Badge>
        )}
        {discrepancy && (
          <Badge variant={discrepancy === "missing" ? "danger" : "info"}>
            {discrepancy === "missing"
              ? t("discrepancyMissing")
              : t("discrepancySurplus")}
          </Badge>
        )}
      </div>
      {item && (
        <p className="text-sm text-on-secondary">
          {item.barcode && `${t("item.barcode")}: ${item.barcode}`}
          {item.category &&
            ` • ${categoryLabel(t, item.category.code, item.category.name)}`}
        </p>
      )}
    </div>
  );
}
