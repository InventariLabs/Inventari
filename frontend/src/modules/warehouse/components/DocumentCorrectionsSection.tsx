import { Link } from "react-router-dom";
import { RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { DocumentStatusBadge } from "@/modules/warehouse/components/DocumentStatusBadge";
import type { DocumentSummary } from "@/modules/warehouse/types";

interface DocumentCorrectionsSectionProps {
  corrections: DocumentSummary[];
  documentType: string;
  onNewCorrection: () => void;
  correctionsTitle: string;
  correctionsNewText: string;
  correctionsNoneText: string;
  /** Renders a reason code the way the rest of the module does — the form
   *  demanded this answer, the row names it. */
  formatReason: (code: string) => string;
  /** False keeps the list of corrections and drops the button that starts a
   *  new one. It used to open the whole form, take the delta and the reason,
   *  enable the submit — and refuse with a 403 at the end of the work. */
  canWrite?: boolean;
  formatDate: (dateStr: string | null) => string;
}

export function DocumentCorrectionsSection({
  corrections,
  documentType,
  onNewCorrection,
  correctionsTitle,
  correctionsNewText,
  correctionsNoneText,
  formatReason,
  canWrite = true,
  formatDate,
}: DocumentCorrectionsSectionProps) {
  // An adjustment's lines are already differences, and the API refuses to
  // correct one (`correction_sign`): a mistake in it is a new adjustment.
  if (documentType === "CORRECTION" || documentType === "ADJUSTMENT")
    return null;

  return (
    <Card className="p-4 sm:p-5 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="font-medium text-on">{correctionsTitle}</h2>
        {canWrite && (
          <Button
            variant="outline"
            size="sm"
            leftIcon={<RotateCcw size={14} />}
            onClick={onNewCorrection}
          >
            {correctionsNewText}
          </Button>
        )}
      </div>
      {corrections.length === 0 ? (
        <p className="text-sm text-on-secondary">{correctionsNoneText}</p>
      ) : (
        <div className="space-y-2">
          {corrections.map((c) => (
            <div
              key={c.id}
              className="flex flex-wrap sm:flex-nowrap items-start sm:items-center justify-between gap-x-3 gap-y-1 rounded-lg border border-border bg-surface-raised px-3 py-2"
            >
              {/* The number is the only way to tell these rows apart — it
                    keeps its full width and the reason wraps under it
                    (UI_GUIDELINES §2.9), never the other way round. */}
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 min-w-0">
                <Link
                  to={`/warehouse/documents/${c.id}`}
                  className="text-xs font-mono font-medium text-on-primary hover:underline shrink-0"
                >
                  {c.number}
                </Link>
                <span className="text-xs text-on-secondary shrink-0">
                  {formatDate(c.created_at)}
                </span>
                {c.reason_code && (
                  <span className="text-xs text-on-secondary">
                    {formatReason(c.reason_code)}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {/* One status vocabulary across the module: this printed the
                    raw enum (COMPLETED) next to badges reading "Completed"
 everywhere else. */}
                <DocumentStatusBadge status={c.status} />
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
