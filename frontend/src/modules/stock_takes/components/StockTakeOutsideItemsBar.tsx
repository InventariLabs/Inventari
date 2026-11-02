import { useTranslation } from "react-i18next";
import { Plus, AlertTriangle } from "lucide-react";
import type { Item } from "@/types";
import { Button } from "@/components/ui/Button";

interface Props {
  items: Item[];
  onAdd: (item: Item) => void;
}

/**
 * products physically present in the counted location but missing
 * from the stock take snapshot. The snapshot is correct by design — this
 * bar makes it loud instead of silently completing without the new goods.
 */
export default function StockTakeOutsideItemsBar({ items, onAdd }: Props) {
  const { t } = useTranslation(["stock_takes"]);
  if (items.length === 0) return null;

  return (
    <div className="bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/20 rounded-lg p-3 space-y-2">
      <p className="text-sm font-medium text-amber-700 dark:text-amber-400 flex items-center gap-2">
        <AlertTriangle size={16} className="shrink-0" />
        {t("outsideItems.title", { count: items.length })}
      </p>
      <ul className="space-y-1">
        {items.map((item) => (
          <li key={item.id} className="flex items-center justify-between gap-2">
            <span className="text-sm text-on-secondary truncate">
              {item.name}
            </span>
            <Button
              type="button"
              size="contentSm"
              variant="outline"
              className="h-8 shrink-0"
              onClick={() => onAdd(item)}
            >
              <Plus size={14} />
              {t("outsideItems.add")}
            </Button>
          </li>
        ))}
      </ul>
    </div>
  );
}
