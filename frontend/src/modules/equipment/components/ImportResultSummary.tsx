import { useTranslation } from "react-i18next";
import { AlertCircle, Check, Info } from "lucide-react";
import { Card } from "@/components/ui/Card";
import type { ImportExecuteResult } from "@/modules/equipment/api/equipment";

/**
 * The headline of a finished import, and the rows it refused.
 *
 * It read "Import complete" under a green check whatever happened, so a sheet
 * whose every row was refused announced success above "Imported: 0, Failed: 3".
 * A run that wrote nothing now says so — as a failure when rows were refused,
 * plainly when every row was skipped as a duplicate.
 */
export function ImportResultSummary({
  result,
}: {
  result: ImportExecuteResult;
}) {
  const { t } = useTranslation("equipment");
  const skipped = result.skipped ?? 0;
  const updated = result.updated ?? 0;
  const wroteNothing = result.imported === 0 && updated === 0;
  const refused = wroteNothing && result.failed > 0;

  return (
    <>
      <Card className="p-4">
        <div className="flex items-center gap-3">
          {refused ? (
            <AlertCircle size={20} className="text-red-500" aria-hidden />
          ) : wroteNothing ? (
            <Info size={20} className="text-on-muted" aria-hidden />
          ) : (
            <Check size={20} className="text-success-500" aria-hidden />
          )}
          <div>
            <div className="text-sm font-medium text-on">
              {wroteNothing
                ? t("import.nothingImported")
                : t("import.complete")}
            </div>
            <div className="text-xs text-on-muted">
              {t("import.result", {
                imported: result.imported,
                failed: result.failed,
              })}
            </div>
            {skipped > 0 || updated > 0 ? (
              <div className="text-xs text-on-muted">
                {t("import.resultExtras", { skipped, updated })}
              </div>
            ) : null}
          </div>
        </div>
      </Card>

      {result.errors.length > 0 && (
        <Card className="p-4 bg-red-50 border-red-200">
          <div className="flex items-start gap-2 mb-2">
            <AlertCircle size={14} className="text-red-500 mt-0.5" />
            <span className="text-sm font-medium text-red-700">
              {t("import.errors")}
            </span>
          </div>
          <div className="space-y-1 max-h-40 overflow-y-auto">
            {result.errors.map((err, i) => (
              <div key={i} className="text-xs text-red-600">
                {t("import.error_row", { row: err.row, error: err.error })}
              </div>
            ))}
          </div>
        </Card>
      )}
    </>
  );
}
