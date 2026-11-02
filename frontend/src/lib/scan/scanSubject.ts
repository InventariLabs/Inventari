import { extractApiErrorCode } from "@/lib/errors";
import type { LabelScanView } from "@/types";

/**
 * What the scan registry decided a code is.
 *
 * The registry resolves every kind of code the app prints — label codes,
 * product barcodes, storage-location codes, document numbers, and any of
 * those wrapped in a `?code=` URL — in a single chain. Screens used to keep
 * their own copy of that decision, which is why each of them knew exactly one
 * kind and answered "not found" to the other four.
 */
export type ScanSubjectKind =
  "product" | "blankLabel" | "archived" | "storage" | "document";

export interface ScanSubject {
  kind: ScanSubjectKind;
  /** What to call the thing when telling the reader what they scanned. */
  name: string;
  /** The route that handles this kind, with the scanned code preserved. */
  target: string;
}

//: The shape a label's short_code has, as the scanner recognises one: a
//: prefix, a hyphen, a body. The hyphen is what keeps a label apart from a
//: plain barcode, which is digits and nothing else — the rule itself lives
//: in `backend/app/core/label_codes.py`, and this is its recognition side.
const LABEL_CODE_SHAPE = /^[A-Z0-9]{1,12}-[A-Z0-9]{1,12}$/;

/** Whether a scanned code is a printed label rather than a product's code. */
export function isLabelCode(code: string): boolean {
  return LABEL_CODE_SHAPE.test(code);
}

/** Where a scanned document opens, and in which mode. */
export function documentScanTarget(result: LabelScanView): string | null {
  if (result.action !== "open_document" || !result.document) return null;
  const { id, type } = result.document;
  if (result.document_mode === "continue")
    return `/warehouse/documents/${id}#edit`;
  if (result.document_mode === "execute") {
    if (type === "IN" || type === "INTERNAL_IN")
      return `/warehouse/documents/${id}#receive`;
    if (type === "OUT" || type === "INT" || type === "INTERNAL_OUT")
      return `/warehouse/documents/${id}#pick`;
    return `/warehouse/documents/${id}#execute`;
  }
  return `/warehouse/documents/${id}`;
}

export function scanSubjectKind(result: LabelScanView): ScanSubjectKind {
  switch (result.action) {
    case "open_document":
      return "document";
    case "set_storage_context":
      return "storage";
    case "show_archived_info":
      return "archived";
    case "show_quick_add":
      return result.stock_summary?.template ? "product" : "blankLabel";
    default:
      return "product";
  }
}

/**
 * The thing that was scanned, named and addressed.
 *
 * `target` is where the code is handled, not merely where its record lives:
 * the product scanner takes `?code=` and replays the whole flow, so a reader
 * who followed the offer does not have to scan a second time.
 */
export function scanSubject(
  result: LabelScanView,
  scannedCode: string,
): ScanSubject {
  const kind = scanSubjectKind(result);
  const code = encodeURIComponent(scannedCode);
  switch (kind) {
    case "document":
      return {
        kind,
        name: result.document?.number ?? result.label_code,
        target: documentScanTarget(result) ?? `/warehouse`,
      };
    case "storage":
      return {
        kind,
        name: result.location?.name ?? result.label_code,
        target: result.location
          ? `/inventory/locations/${result.location.id}`
          : `/scan?code=${code}`,
      };
    case "archived":
      return {
        kind,
        name: result.item?.name ?? result.label_code,
        target: `/scan?code=${code}`,
      };
    case "blankLabel":
      return { kind, name: result.label_code, target: `/scan?code=${code}` };
    default:
      return {
        kind,
        name:
          result.stock_summary?.template?.name ??
          result.item?.name ??
          // The product's name travels as a value now: the line under the
          // status is a catalogue key, not the server's English sentence.
          result.message_params?.product ??
          result.label_code,
        target: `/scan?code=${code}`,
      };
  }
}

/**
 * Where a code that nothing recognized can still be looked for: the product
 * list, with the code in its search box. The server answers that search with
 * the same fields a scan reads, so a match the scan missed is still one tap
 * away.
 */
export function searchForCodeTarget(code: string): string {
  return `/inventory/items?search=${encodeURIComponent(code)}`;
}

/**
 * The toast action for a scan error: the search, when nothing recognized the
 * code (asking again cannot change that), and nothing for any other failure.
 */
export function searchActionFor(
  error: unknown,
  code: string,
  label: string,
  navigate: (to: string) => void,
): { label: string; onClick: () => void } | undefined {
  if (extractApiErrorCode(error) !== "SCAN_UNRECOGNIZED") return undefined;
  return { label, onClick: () => navigate(searchForCodeTarget(code)) };
}
