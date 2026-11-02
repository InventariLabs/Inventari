import { useCallback } from "react";
import { TypedSlot } from "@/components/Slot";
import type { SaveMetaData } from "@/lib/moduleRegistry";
import { useSetDocumentMetaData } from "@/modules/warehouse/hooks/useDocuments";
import type { WarehouseDocument } from "@/modules/warehouse/types";

/** Writes one module's values on the saved document, or on one of its lines. */
function useSaveMetaData(docId: string, lineId?: string): SaveMetaData {
  const { mutateAsync } = useSetDocumentMetaData();
  return useCallback(
    async (module, values) => {
      await mutateAsync({ docId, lineId, module, values });
    },
    [mutateAsync, docId, lineId],
  );
}

/**
 * What other modules say about one line of a document, under the line in the
 * table and in the phone's card alike. Draws nothing when no module has
 * anything to add.
 */
export function DocumentLineExtra({
  document,
  line,
}: {
  document: WarehouseDocument;
  line: WarehouseDocument["lines"][number];
}) {
  const saveMetaData = useSaveMetaData(document.id, line.id);
  return (
    <TypedSlot
      name="document_detail_line_extra"
      data={{
        documentId: document.id,
        documentStatus: document.status,
        line: {
          id: line.id,
          lineNumber: line.line_number,
          itemId: line.item_id ?? null,
          productTemplateId: line.product_template_id ?? null,
          name: line.name ?? null,
          batchNumber: line.batch_number ?? null,
          metaData: line.meta_data ?? {},
        },
        saveMetaData,
      }}
    />
  );
}

/** What other modules say about the whole document, below its lines and totals. */
export function DocumentDetailExtra({
  document,
}: {
  document: WarehouseDocument;
}) {
  const saveMetaData = useSaveMetaData(document.id);
  return (
    <TypedSlot
      name="document_detail_extra"
      data={{
        documentId: document.id,
        documentStatus: document.status,
        metaData: document.meta_data ?? {},
        saveMetaData,
      }}
    />
  );
}
