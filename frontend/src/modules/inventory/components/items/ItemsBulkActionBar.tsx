import { useTranslation } from "react-i18next";
import { makeTDynamic } from "@/lib/i18nHelpers";
import { Edit, Loader2, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { SelectionToolbar } from "@/components/ui/SelectionToolbar";
import { useHasPermission } from "@/hooks/useHasPermission";
import { moduleRegistry } from "@/lib/moduleRegistry";

interface ItemsBulkActionBarProps {
  selectedIds: string[];
  /** Rows in the filtered result — the selection only reaches this page. */
  totalInResult?: number;
  onClearSelection: () => void;
  onBulkEdit: () => void;
  onBulkDelete: () => void;
  /** Every action here writes, so a reader gets no bar at all. */
  canWrite?: boolean;
  isPendingDelete: boolean;
  enabledModules: string[];
}

export default function ItemsBulkActionBar({
  selectedIds,
  totalInResult,
  onClearSelection,
  onBulkEdit,
  onBulkDelete,
  canWrite = true,
  isPendingDelete,
  enabledModules,
}: ItemsBulkActionBarProps) {
  const { t } = useTranslation(["items", "common"]);
  const tDyn = makeTDynamic(t);
  // Bulk delete asks the narrower key its endpoint checks; the bar itself
  // needs the module's write right.
  const canDelete = useHasPermission("items:delete");

  // Editing in bulk is what the bar does for a writer; a reader gets no bar
  // at all — and no selection mode leading to one either.
  if (!canWrite) return null;

  return (
    <SelectionToolbar
      count={selectedIds.length}
      totalBeyondPage={totalInResult}
      onClear={onClearSelection}
    >
      <Button
        size="content"
        variant="ghost"
        onClick={onBulkEdit}
        className="py-2 rounded-xl font-semibold text-primary-600 hover:bg-primary-50 active:bg-primary-50"
      >
        <Edit size={16} />
        {t("common:actions.edit")}
      </Button>
      {moduleRegistry
        .getBulkActions(enabledModules)
        .filter(
          (action) =>
            !action.condition ||
            action.condition(selectedIds.map((id) => ({ id }))),
        )
        .map((action) => (
          <Button
            size="content"
            key={action.id}
            variant="ghost"
            onClick={() => action.handler(selectedIds)}
            className={`py-2 rounded-xl font-semibold ${
              action.variant === "danger"
                ? "text-red-600 hover:bg-red-50 active:bg-red-50"
                : "text-primary-600 hover:bg-primary-50 active:bg-primary-50"
            }`}
          >
            <action.icon size={16} />
            {tDyn(action.labelKey)}
          </Button>
        ))}
      {canDelete && (
        <Button
          size="content"
          variant="ghostDanger"
          onClick={onBulkDelete}
          disabled={isPendingDelete}
          className="py-2 rounded-xl font-semibold"
        >
          {isPendingDelete ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Trash2 size={16} />
          )}
          {t("common:actions.delete")}
        </Button>
      )}
    </SelectionToolbar>
  );
}
