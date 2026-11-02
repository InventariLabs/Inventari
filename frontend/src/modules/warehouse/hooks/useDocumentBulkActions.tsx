import { documentTitle } from "@/modules/warehouse/lib/documentTitle";
import { useState, type ComponentProps } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import i18next from "i18next";
import { extractApiError } from "@/lib/errors";
import { downloadCsv } from "@/lib/csv";
import { downloadBlob } from "@/utils/helpers";
import { getTodayFilename } from "@/utils/formatters";
import { documentsApi } from "@/modules/warehouse/api/documents";
import type { BulkActionBar } from "@/modules/warehouse/components/BulkActionBar";
import { exportDocumentsCsv } from "@/modules/warehouse/utils/csvExport";
import { isPickable } from "@/modules/warehouse/utils/pickable";
import { useBulkSelect } from "@/modules/warehouse/hooks/useBulkSelect";
import type { WarehouseDocumentRow } from "@/modules/warehouse/types";

type BulkMutations = Pick<
  Parameters<typeof useBulkSelect>[0],
  "confirmMutation" | "deleteMutation"
>;

/** The register's selection and everything the action bar does with it,
 *  each action reporting to the reader once for the whole selection. */
export function useDocumentBulkActions(
  documents: WarehouseDocumentRow[],
  { confirmMutation, deleteMutation }: BulkMutations,
) {
  const { t } = useTranslation("warehouse");
  const bulk = useBulkSelect({
    documents,
    deleteMutation,
    confirmMutation,
    // One summary for the whole selection: how many went through, and every
    // document that did not, by number and with the reason it gave.
    onConfirmed: (confirmed, refused) => {
      if (confirmed > 0)
        toast.success(t("bulk.confirmSuccess", { count: confirmed }));
      if (refused.length > 0)
        toast.error(t("bulk.confirmFailed", { count: refused.length }), {
          description: (
            <ul className="mt-1 list-disc pl-4">
              {refused.map(({ doc, error }) => (
                <li key={doc.id}>
                  {documentTitle(t, doc)}:{" "}
                  {extractApiError(error, t("errors.confirmFailed"))}
                </li>
              ))}
            </ul>
          ),
          duration: Infinity,
          closeButton: true,
        });
    },
    onSuccess: (count) => {
      if (count > 0) toast.success(t("bulk.deleteSuccess", { count }));
    },
    onError: (count, error) => {
      if (count > 0)
        toast.error(extractApiError(error, t("bulk.deleteFailed", { count })));
    },
  });

  const handleExportCsv = () => {
    const csv = exportDocumentsCsv(bulk.selectedDocs, t);
    // The file is dated the day the reader took it out, in their own zone.
    downloadCsv(csv, `documents_export_${getTodayFilename()}.csv`);
    toast.success(t("bulk.exportSuccess", { count: bulk.selectedDocs.length }));
  };

  const [isPrinting, setIsPrinting] = useState(false);
  // The printable part of the selection as one file, in the order of the list.
  const handlePrint = async () => {
    setIsPrinting(true);
    try {
      const blob = await documentsApi.downloadPdfBatch(
        bulk.selectedPrintable.map((d) => d.id),
        i18next.language || "en",
      );
      downloadBlob(blob, `documents_${getTodayFilename()}.pdf`);
      toast.success(
        t("bulk.printSuccess", { count: bulk.selectedPrintable.length }),
      );
    } catch (error: unknown) {
      toast.error(extractApiError(error, t("errors.pdfFailed")));
    } finally {
      setIsPrinting(false);
    }
  };

  const barProps = {
    selectedCount: bulk.selectedIds.size,
    draftCount: bulk.selectedDrafts.length,
    pickableIds: bulk.selectedDocs.filter(isPickable).map((d) => d.id),
    printableCount: bulk.selectedPrintable.length,
    isDeleting: bulk.isBulkDeleting,
    isConfirming: bulk.isBulkConfirming,
    isPrinting,
    onConfirmDrafts: () => bulk.setBulkConfirmOpen(true),
    onPrint: () => void handlePrint(),
    onDeleteDrafts: () => bulk.setBulkDeleteOpen(true),
    onExportCsv: handleExportCsv,
    onClear: bulk.clearSelection,
  } satisfies Partial<ComponentProps<typeof BulkActionBar>>;

  return { ...bulk, barProps };
}
