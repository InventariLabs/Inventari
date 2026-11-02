import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Check, FileSpreadsheet, AlertCircle } from "lucide-react";
import type { ImportOutcome } from "./types";

interface ImportProgressStepProps {
  isProcessing: boolean;
  importResult: ImportOutcome | null;
  /** "Please wait while we process your …" — the entity names itself. */
  waitText: string;
  /** "Added N …" — the entity counts itself. */
  addedText: (count: number) => string;
  /** The sentence under the title, when the entity counts more than
   *  additions — an import that also overwrote rows must not open with
   *  "Added 1 product." alone. Falls back to `addedText`. */
  summaryText?: string;
  /** What the import founded beside the records, when the entity has any. */
  children?: ReactNode;
}

export function ImportProgressStep({
  isProcessing,
  importResult,
  waitText,
  addedText,
  summaryText,
  children,
}: ImportProgressStepProps) {
  const { t } = useTranslation(["common"]);
  if (isProcessing) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-6">
        <div className="relative">
          <Loader2 size={64} className="text-primary-600 animate-spin" />
          <div className="absolute inset-0 flex items-center justify-center">
            <FileSpreadsheet size={24} className="text-primary-400" />
          </div>
        </div>
        <div className="text-center">
          <h3 className="text-xl font-semibold text-on">
            {t("common:import.importing")}
          </h3>
          <p className="text-on-secondary text-sm mt-1">{waitText}</p>
        </div>
      </div>
    );
  }

  if (!importResult) return null;

  // The server counts: total rows read, rows imported, rows refused. `failed`
  // is the server's number — the errors list is capped at ten, so counting it
  // under-reported mass failures.
  const errorCount = importResult.failed;

  return (
    <div className="space-y-8 py-6 text-center">
      {/* Success icon */}
      <div className="w-20 h-20 bg-accent-50 text-accent-600 rounded-xl flex items-center justify-center mx-auto shadow-lg shadow-accent-100">
        <Check size={40} strokeWidth={3} />
      </div>

      {/* Title & description */}
      <div>
        <h3 className="text-2xl font-semibold text-on">
          {t("common:import.complete")}
        </h3>
        <p className="text-on-secondary font-medium">
          {summaryText ?? addedText(importResult.imported)}
        </p>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-3 gap-4 max-w-sm mx-auto">
        <div className="bg-surface p-4 rounded-2xl border border-border">
          <p className="text-[10px] font-medium text-on-muted uppercase">
            {t("common:import.statsTotal")}
          </p>
          <p className="text-xl font-semibold text-on">{importResult.total}</p>
        </div>
        <div className="bg-accent-50 p-4 rounded-2xl border border-accent-100">
          <p className="text-[10px] font-medium text-on-success uppercase">
            {t("common:import.statsImported")}
          </p>
          <p className="text-xl font-semibold text-on-success">
            {importResult.imported}
          </p>
        </div>
        <div className="bg-red-50 p-4 rounded-2xl border border-red-100">
          <p className="text-[10px] font-medium text-on-danger uppercase">
            {t("common:import.statsFailed")}
          </p>
          <p className="text-xl font-semibold text-on-danger">{errorCount}</p>
        </div>
      </div>

      {children}

      {/* Errors list */}
      {errorCount > 0 && (
        <div className="bg-red-50/50 p-6 rounded-xl border border-red-100 text-left max-w-md mx-auto">
          <p className="text-[10px] font-medium text-on-danger uppercase tracking-widest mb-3 flex items-center gap-2">
            <AlertCircle size={12} />
            {t("common:import.firstErrors")}
          </p>
          <ul className="space-y-2">
            {importResult.errors.map((err) => (
              <li
                key={err.row}
                className="text-xs text-on-danger flex items-start gap-2"
              >
                <span className="font-medium shrink-0">#{err.row}:</span>
                <span>{err.error}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
