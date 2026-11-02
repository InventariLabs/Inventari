import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { FIELD_IDS } from "@/modules/warehouse/components/DocumentFormFields";
import type { ImportResult } from "@/modules/warehouse/components/ImportPreviewSections";
import { useFetchDocument } from "@/modules/warehouse/hooks/useDocuments";
import type { WarehouseDocument } from "@/modules/warehouse/types";

interface UseDocumentLineImportOptions {
  /** The saved draft being edited; none while the document is being written. */
  documentId?: string;
  docType: string;
  sourceLocationId: string;
  requiresSource: boolean;
  replaceLinesFrom: (source: WarehouseDocument) => void;
  appendImportedLines: (lines: ImportResult["lines"]) => void;
}

/** The line import beside the document form: when it may open, and where its lines go. */
export function useDocumentLineImport({
  documentId,
  docType,
  sourceLocationId,
  requiresSource,
  replaceLinesFrom,
  appendImportedLines,
}: UseDocumentLineImportOptions) {
  const { t } = useTranslation("warehouse");
  const [importOpen, setImportOpen] = useState(false);
  const fetchDocument = useFetchDocument();

  /** Import is offered while the document is still being written, too: an
   * order arriving as a spreadsheet is a dispatch nobody has saved yet. A
   * dispatch's lines name records on its source shelf, so that comes first.
   */
  const openImport = useCallback(() => {
    if (!documentId && requiresSource && !sourceLocationId) {
      toast.error(t("import.chooseSourceFirst"));
      document.getElementById(FIELD_IDS.source)?.focus();
      return;
    }
    setImportOpen(true);
  }, [documentId, requiresSource, sourceLocationId, t]);

  /** A saved draft was written to: the form takes the server's lines.
   *
   * Saving sends the whole list, so a form still holding the line it opened
   * with would delete everything the import had just written. What is on
   * screen after an import is what the document has. A document not saved
   * yet was written nothing: the lines read come back for the form to add.
   */
  const onImported = useCallback(
    async (result: ImportResult) => {
      if (!documentId) {
        appendImportedLines(result.lines);
        return;
      }
      replaceLinesFrom(await fetchDocument(documentId));
    },
    [documentId, appendImportedLines, fetchDocument, replaceLinesFrom],
  );

  const importTarget = documentId
    ? { documentId }
    : {
        documentType: docType,
        sourceLocationId: sourceLocationId || undefined,
      };

  return {
    importOpen,
    openImport,
    /** What the import sheet is opened with: where its lines go, and back. */
    modalProps: {
      ...importTarget,
      onClose: () => setImportOpen(false),
      onImported,
    },
  };
}
