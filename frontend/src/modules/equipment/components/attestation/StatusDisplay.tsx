import { useTranslation } from "react-i18next";
import { CheckCircle, AlertTriangle, Clock, XCircle } from "lucide-react";

export function StatusDisplay({
  status,
  closedReason,
}: {
  status: string;
  /**
   * Why the link can no longer take an answer, straight from the public
   * GET. Told only while the response itself has no answer to show: a
   * confirmed answer is the reader's own and outranks a later closure.
   * ``'expired'`` arrives here without the status having moved — a read
   * does not write — and still reads as expired.
   */
  closedReason?: string | null;
}) {
  const { t } = useTranslation("equipment");

  // The response's own state first: it is the answer the reader gave.
  if (status === "CONFIRMED") {
    return (
      <div className="flex flex-col items-center gap-3 text-center py-4">
        <CheckCircle size={56} className="text-accent-500" />
        <h2 className="text-xl font-semibold text-on">
          {t("attestation.public.statusConfirmed")}
        </h2>
        <p className="text-on-secondary">
          {t("attestation.public.statusConfirmedDesc")}
        </p>
      </div>
    );
  }

  if (status === "DISPUTED") {
    return (
      <div className="flex flex-col items-center gap-3 text-center py-4">
        <AlertTriangle size={56} className="text-red-400" />
        <h2 className="text-xl font-semibold text-on">
          {t("attestation.public.statusDisputed")}
        </h2>
        <p className="text-on-secondary">
          {t("attestation.public.statusDisputedDesc")}
        </p>
      </div>
    );
  }

  if (status === "EXPIRED" || closedReason === "expired") {
    return (
      <div className="flex flex-col items-center gap-3 text-center py-4">
        <Clock size={56} className="text-on-muted" />
        <h2 className="text-xl font-semibold text-on">
          {t("attestation.public.statusExpired")}
        </h2>
        <p className="text-on-secondary">
          {t("attestation.public.statusExpiredDesc")}
        </p>
      </div>
    );
  }

  if (status === "PENDING" && closedReason === "campaign_closed") {
    return (
      <div className="flex flex-col items-center gap-3 text-center py-4">
        <XCircle size={56} className="text-on-muted" />
        <h2 className="text-xl font-semibold text-on">
          {t("attestation.public.statusCampaignClosed")}
        </h2>
        <p className="text-on-secondary">
          {t("attestation.public.statusCampaignClosedDesc")}
        </p>
      </div>
    );
  }

  if (status === "PENDING" && closedReason === "assignment_already_returned") {
    return (
      <div className="flex flex-col items-center gap-3 text-center py-4">
        <CheckCircle size={56} className="text-accent-500" />
        <h2 className="text-xl font-semibold text-on">
          {t("attestation.public.statusAssignmentReturned")}
        </h2>
        <p className="text-on-secondary">
          {t("attestation.public.statusAssignmentReturnedDesc")}
        </p>
      </div>
    );
  }

  return null;
}
