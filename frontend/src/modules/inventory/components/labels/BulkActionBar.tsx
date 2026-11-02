import { Loader2, Trash2, Eye } from "lucide-react";
import Button from "@/components/ui/Button";
import { SelectionToolbar } from "@/components/ui/SelectionToolbar";
import { SendToPrinterButton } from "@/modules/shared/components/SendToPrinterButton";

interface BulkActionBarProps {
  selectedIds: string[];
  bulkDeleteMutation: {
    isPending: boolean;
    mutate: (ids: string[], opts?: object) => void;
  };
  onClearSelection: () => void;
  onDeleteSelected: () => void;
  onPreviewSelected: () => void;
  t: (key: string, options?: Record<string, unknown>) => string;
}

/**
 * What to do with the labels that are ticked.
 *
 * It used to be a row in the page flow with both buttons on `flex-1`, so a
 * desktop showed two actions each half the screen wide, wedged between the
 * page title and the filter row. The selection is a passing state, so its
 * actions live in the floating toolbar every list in this app uses.
 */
export function BulkActionBar({
  selectedIds,
  bulkDeleteMutation,
  onClearSelection,
  onDeleteSelected,
  onPreviewSelected,
  t,
}: BulkActionBarProps) {
  return (
    <SelectionToolbar
      count={selectedIds.length}
      onClear={onClearSelection}
      width="wide"
    >
      <Button
        variant="ghostDanger"
        size="content"
        className="min-h-11 py-2 md:min-h-0"
        onClick={onDeleteSelected}
        disabled={bulkDeleteMutation.isPending}
        leftIcon={
          bulkDeleteMutation.isPending ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Trash2 size={16} />
          )
        }
      >
        {t("actions.deleteSelected", { ns: "labels" })}
      </Button>
      <Button
        variant="ghost"
        size="content"
        className="min-h-11 py-2 md:min-h-0"
        onClick={onPreviewSelected}
        leftIcon={<Eye size={16} />}
      >
        {t("actions.preview", { ns: "labels" })}
      </Button>
      <SendToPrinterButton
        target={{ labelIds: selectedIds }}
        variant="ghost"
        size="content"
        className="min-h-11 py-2 md:min-h-0"
        onSent={onClearSelection}
      />
    </SelectionToolbar>
  );
}
