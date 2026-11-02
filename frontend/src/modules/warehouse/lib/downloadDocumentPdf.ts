import i18next from "i18next";
import { toast } from "sonner";
import { downloadBlob } from "@/utils/helpers";
import { extractApiError } from "@/lib/errors";
import { documentsApi } from "@/modules/warehouse/api/documents";

/**
 * Build the document's PDF and hand it to the browser, saying so where the
 * reader is looking. It lives outside the detail page's action hook because
 * the posted-result screen downloads the same PDF, and importing the hook
 * for this one function dragged the whole document detail machinery into
 * that screen's bundle.
 */
export async function downloadDocumentPdf(
  doc: { id: string; number: string } | undefined,
  t: (key: string) => string,
  setIsPdfDownloading: (pending: boolean) => void,
): Promise<void> {
  if (!doc) return;
  setIsPdfDownloading(true);
  try {
    const lang = i18next.language || "en";
    const blob = await documentsApi.downloadPdf(doc.id, lang);
    const safeNumber = doc.number.replace(/\//g, "-").replace(/\s/g, "_");
    downloadBlob(blob, `document_${safeNumber}.pdf`);
    toast.success(t("warehouse:toast.pdfDownloaded"));
  } catch (error) {
    toast.error(extractApiError(error, t("warehouse:errors.pdfFailed")));
  } finally {
    setIsPdfDownloading(false);
  }
}
