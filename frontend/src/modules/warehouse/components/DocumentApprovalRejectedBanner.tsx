import { AlertTriangle, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { cn } from "@/lib/utils";
import type { TargetApprovalRequest } from "@/lib/moduleRegistry";

interface DocumentApprovalRejectedBannerProps {
  /**
   * The request the banner speaks about. `null`/`undefined` — no request,
   * or one that does not speak for the document as it stands (see
   * `speakingApproval` on the detail page) — and a request in any other
   * state render nothing.
   */
  approval: TargetApprovalRequest | null | undefined;
  documentId: string;
  className?: string;
}

/**
 * Banner shown while a document's most recent approval request was
 * REJECTED and still speaks for it — the draft the rejection left behind.
 * The user can read the reason, see who rejected, and click the CTA to
 * re-submit after editing the document.
 */
export function DocumentApprovalRejectedBanner({
  approval,
  documentId,
  className,
}: DocumentApprovalRejectedBannerProps) {
  const { t } = useTranslation("warehouse");
  if (approval?.status !== "REJECTED") return null;
  const rejection = approval.decisions?.find((d) => d.status === "REJECTED");
  if (!rejection) return null;

  // Hoisted out of the interpolation object: check-i18n-keys only sees
  // top-level t() calls, and a nested one reads as an orphaned key.
  const approverName =
    rejection.approver_name ?? t("detail.rejectedBanner.someone");

  return (
    <div
      role="alert"
      data-testid="approval-rejected-banner"
      className={cn(
        "flex flex-col gap-2 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800",
        "sm:flex-row sm:items-center sm:justify-between",
        className,
      )}
    >
      <div className="flex items-start gap-2">
        <AlertTriangle size={18} className="mt-0.5 shrink-0 text-red-600" />
        <div>
          <p className="font-semibold">
            {t("detail.rejectedBanner.title", { name: approverName })}
          </p>
          {rejection.notes && (
            <p className="mt-0.5 italic text-red-700">
              &ldquo;{rejection.notes}&rdquo;
            </p>
          )}
        </div>
      </div>
      <Link
        to={`/warehouse/documents/${documentId}#edit`}
        className={cn(
          "inline-flex items-center justify-center gap-1.5 self-start sm:self-auto",
          "h-8 px-3 rounded-lg border border-border bg-surface-card hover:bg-surface-raised",
          "active:bg-surface-raised text-sm font-medium text-on-secondary",
        )}
      >
        <RefreshCw size={14} />
        {t("detail.rejectedBanner.cta")}
      </Link>
    </div>
  );
}
