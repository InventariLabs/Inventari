import {
  CheckCheck,
  Download,
  PackageCheck,
  Printer,
  Trash2,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/Button";

interface BulkActionBarProps {
  selectedCount: number;
  draftCount: number;
  /** Ticked confirmed dispatches, in the order the list shows them, which is
   *  the order the session picks. */
  pickableIds: string[];
  isDeleting: boolean;
  /** Selected documents a printout exists for (confirmed or completed). */
  printableCount: number;
  isConfirming: boolean;
  isPrinting: boolean;
  onConfirmDrafts: () => void;
  onPrint: () => void;
  onDeleteDrafts: () => void;
  onExportCsv: () => void;
  onClear: () => void;
  /** Open a picking session over these dispatches. The page owns the sheet:
   *  it must outlive this bar, which goes when a scan empties the list. */
  onPick: (documentIds: string[]) => void;
  /** False drops the delete action. Exporting what you may already read is
   *  not a write; deleting drafts is, and the refusal used to arrive after
   *  the "this cannot be undone" dialog had been accepted. */
  canWrite?: boolean;
  t: (key: string, options?: Record<string, unknown>) => string;
}

export function BulkActionBar({
  selectedCount,
  draftCount,
  pickableIds,
  isDeleting,
  printableCount,
  isConfirming,
  isPrinting,
  onConfirmDrafts,
  onPrint,
  onDeleteDrafts,
  onExportCsv,
  onClear,
  onPick,
  canWrite = true,
  t,
}: BulkActionBarProps) {
  if (selectedCount === 0) return null;
  return (
    <div className="sticky top-[calc(3.5rem+var(--app-notice-height,0px)+0.5rem)] md:top-[calc(3.5rem+2.75rem+var(--app-notice-height,0px)+0.5rem)] z-[var(--z-sticky)] flex flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-lg border border-primary-200 bg-primary-50/95 px-3 py-2 backdrop-blur dark:border-primary-800 dark:bg-primary-950/80">
      <div className="flex items-center gap-3 text-sm">
        <span className="font-medium text-primary-900 dark:text-primary-100">
          {t("warehouse:bulk.selectedCount", { count: selectedCount })}
        </span>
        {draftCount > 0 && (
          <span className="text-xs text-on-secondary">
            {t("warehouse:bulk.draftsCount", { count: draftCount })}
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          leftIcon={<Download size={15} />}
          onClick={onExportCsv}
        >
          {t("warehouse:bulk.exportCsv")}
        </Button>
        {/* The reason sits on the wrapper: a disabled button takes no hover. */}
        <span
          title={
            printableCount === 0
              ? t("warehouse:bulk.printNoneReason")
              : undefined
          }
        >
          <Button
            variant="ghost"
            size="sm"
            leftIcon={<Printer size={15} />}
            onClick={onPrint}
            disabled={printableCount === 0 || isPrinting}
            isLoading={isPrinting}
          >
            {printableCount === 0
              ? t("warehouse:bulk.printNone")
              : t("warehouse:bulk.print", { count: printableCount })}
          </Button>
        </span>
        {canWrite && (
          <Button
            variant="ghost"
            size="sm"
            leftIcon={<CheckCheck size={15} />}
            onClick={onConfirmDrafts}
            disabled={draftCount === 0 || isConfirming}
            isLoading={isConfirming}
          >
            {t("warehouse:bulk.confirmDrafts", { count: draftCount })}
          </Button>
        )}
        {canWrite && pickableIds.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            leftIcon={<PackageCheck size={15} />}
            onClick={() => onPick(pickableIds)}
          >
            {t("warehouse:bulk.pickSelected", { count: pickableIds.length })}
          </Button>
        )}
        {canWrite && (
          <Button
            variant="ghost"
            size="sm"
            leftIcon={<Trash2 size={15} />}
            onClick={onDeleteDrafts}
            disabled={draftCount === 0 || isDeleting}
            isLoading={isDeleting}
            className="text-red-600 hover:text-red-700 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/20"
          >
            {t("warehouse:bulk.deleteDrafts", { count: draftCount })}
          </Button>
        )}
        <Button
          variant="ghost"
          size="sm"
          onClick={onClear}
          aria-label={t("warehouse:bulk.clear")}
        >
          <X size={16} />
        </Button>
      </div>
    </div>
  );
}
