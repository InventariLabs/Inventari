import type { TFunction } from "i18next";
import { apiErrorStatus, extractApiError } from "@/lib/errors";
import { searchActionFor } from "@/lib/scan/scanSubject";

/**
 * The sentence for a failed code lookup. Past the per-minute allowance the API
 * answers 429 with a generic "try again later"; a scanner says what to do
 * right now instead. `t` is any translator; the key names its namespace.
 */
export function scanLookupError(
  error: unknown,
  fallback: string,
  t: TFunction,
): string {
  if (apiErrorStatus(error) === 429) return t("scan:tooManyScans");
  return extractApiError(error, fallback);
}

/**
 * Why a scan failed, as the scan page keeps it on screen, with the search as
 * the way on when nothing recognized the code. `t` is any translator; the keys
 * name their namespace.
 */
export function scanFailure(
  error: unknown,
  code: string,
  t: TFunction,
  navigate: (to: string) => void,
): { code: string; message: string; onSearch?: () => void } {
  return {
    code,
    message: scanLookupError(error, t("scan:errorScanning"), t),
    onSearch: searchActionFor(error, code, t("scan:searchForCode"), navigate)
      ?.onClick,
  };
}
