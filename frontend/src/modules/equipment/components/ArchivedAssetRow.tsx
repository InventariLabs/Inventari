import { memo } from "react";
import { useTranslation } from "react-i18next";
import { RotateCcw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Checkbox } from "@/components/ui/Checkbox";
import { formatDate } from "@/utils/helpers";
import type { ArchivedItem } from "@/types";
import { getCategoryLabel } from "@/modules/equipment/components/assetUtils";
import { archivedReasonLabel } from "@/modules/shared/lib/archiveReasons";

interface ArchivedAssetRowProps {
  item: ArchivedItem;
  /** False drops the checkbox and both actions — a reader restores nothing. */
  selectable?: boolean;
  isSelected: boolean;
  isRestorePending: boolean;
  isPurgePending: boolean;
  onToggleSelect: (id: string) => void;
  onRestore: (id: string) => void;
  onPurge: (id: string) => void;
}

export const ArchivedAssetRow = memo(function ArchivedAssetRow({
  item,
  selectable = true,
  isSelected,
  isRestorePending,
  isPurgePending,
  onToggleSelect,
  onRestore,
  onPurge,
}: ArchivedAssetRowProps) {
  // The badge speaks the items catalogue's vocabulary: the reason values are
  // the same dictionary the inventory archive reads, and the raw value ("EXPIRED")
  // is the database's word, not the reader's.
  const { t } = useTranslation(["equipment", "items"]);

  return (
    <div
      className={`flex items-center gap-4 py-3 px-1 ${isSelected ? "bg-red-50/50 dark:bg-red-900/10" : ""}`}
    >
      {selectable && (
        <Checkbox
          checked={isSelected}
          onChange={() => onToggleSelect(item.id)}
          aria-label={t("list.select_archived_item", { name: item.name })}
          className="text-red-600 focus:ring-red-500"
        />
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-sm text-on truncate">
            {item.name}
          </span>
          {item.deletion_reason && (
            <Badge variant="outline">
              {archivedReasonLabel(t, item.deletion_reason)}
            </Badge>
          )}
        </div>
        <div className="text-xs text-on-muted mt-0.5 flex items-center gap-3">
          {item.category && <span>{getCategoryLabel(t, item.category)}</span>}
          {item.deleted_at && <span>{formatDate(item.deleted_at)}</span>}
        </div>
      </div>
      {selectable && (
        <div className="flex items-center gap-2 shrink-0">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onRestore(item.id)}
            disabled={isRestorePending}
            leftIcon={<RotateCcw size={14} />}
          >
            <span className="hidden sm:inline">{t("actions.restore")}</span>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onPurge(item.id)}
            disabled={isPurgePending}
            className="text-red-600 hover:text-red-700 hover:bg-red-50"
            leftIcon={<Trash2 size={14} />}
          >
            <span className="hidden sm:inline">{t("actions.purge")}</span>
          </Button>
        </div>
      )}
    </div>
  );
});
