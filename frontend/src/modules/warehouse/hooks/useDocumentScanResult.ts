import { useCallback } from "react";
import type { TFunction } from "i18next";
import { scanSubjectKind } from "@/lib/scan/scanSubject";
import type { ExecutionLine } from "./useDocumentExecution";
import type { LabelScanView } from "@/types";

/**
 * Whether a line is the product the registry recognized.
 *
 * A line's own barcode is a snapshot from when it was added; the product has
 * since gained codes and labels, so the line is matched by what it points at
 * (stock record, catalogue entry) and by any code the product carries now.
 */
function lineHoldsScannedProduct(
  line: ExecutionLine,
  result: LabelScanView,
): boolean {
  const itemIds = new Set(
    [
      result.item?.id,
      ...(result.stock_summary?.items ?? []).map((i) => i.id),
    ].filter(Boolean),
  );
  if (line.item_id && itemIds.has(line.item_id)) return true;
  const templateId =
    result.item?.template_id ?? result.stock_summary?.template?.id;
  if (line.product_template_id && line.product_template_id === templateId) {
    return true;
  }
  const lineCode = line.barcode?.trim().toLowerCase();
  const productCodes = [
    result.item?.barcode,
    result.item?.template?.barcode,
  ].map((code) => code?.trim().toLowerCase());
  return !!lineCode && productCodes.includes(lineCode);
}

/**
 * Apply what the registry made of a scanned code — a product label, a
 * barcode the line never recorded — to the line carrying that product.
 * Says so when the product is not on this document; returns false for a code
 * that is not a product at all, which the shared resolver then names.
 */
export function useDocumentScanResult(
  lines: ExecutionLine[],
  applyScanToLine: (
    line: ExecutionLine | undefined,
    notFound: string,
  ) => boolean,
  t: TFunction,
) {
  return useCallback(
    (result: LabelScanView): boolean => {
      if (scanSubjectKind(result) !== "product") return false;
      const name =
        result.item?.name ?? result.stock_summary?.template?.name ?? "";
      applyScanToLine(
        lines.find((line) => lineHoldsScannedProduct(line, result)),
        t("warehouse:detail.scanNotOnDocument", { name }),
      );
      return true;
    },
    [lines, applyScanToLine, t],
  );
}
