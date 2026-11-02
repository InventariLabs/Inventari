import { useTranslation } from "react-i18next";
import { MailWarning } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { QueryFailure } from "@/components/ui/QueryResult";
import { formatDateMedium } from "@/utils/formatters";
import { useFailedEmails } from "@/modules/settings/hooks/useOrganization";
import type { FailedEmail } from "@/lib/api/organizations";

/**
 * Mail this organization sent that never arrived.
 *
 * The queue retries for about seven and a half minutes and then marks the
 * row failed. Nothing read that row: an invitation nobody received and a
 * password-reset link that locked its user out both ended as one line in a
 * container log, while the invitation list went on showing a code that
 * looked like it was merely waiting to be opened.
 *
 * It sits under the SMTP form because that is where the cause usually is —
 * the reason on each row names it, and the form above is what fixes it.
 */
export default function FailedEmailsCard() {
  const { t } = useTranslation("common");
  const { data: failures = [], isError, error, refetch } = useFailedEmails();

  return (
    <Card className="p-6 space-y-4">
      <div className="flex items-center gap-4">
        <div className="w-10 h-10 bg-red-500/10 dark:bg-red-500/20 text-on-danger rounded-xl flex items-center justify-center shrink-0">
          <MailWarning size={20} strokeWidth={2.5} />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-on leading-tight">
            {t("settings.failedEmails.title")}
          </h2>
          <p className="text-[10px] font-medium text-on-muted uppercase tracking-widest mt-0.5">
            {t("settings.failedEmails.subtitle")}
          </p>
        </div>
      </div>

      {isError ? (
        <QueryFailure error={error} onRetry={() => refetch()} />
      ) : failures.length === 0 ? (
        <EmptyState
          variant="compact"
          icon={MailWarning}
          title={t("settings.failedEmails.none")}
          description={t("settings.failedEmails.noneHint")}
        />
      ) : (
        <ul data-testid="failed-emails" className="flex flex-col gap-2">
          {failures.map((failure) => (
            <FailedEmailRow key={failure.id} failure={failure} />
          ))}
        </ul>
      )}
    </Card>
  );
}

/**
 * One lost message: who it was for, what it was, and what the relay said.
 *
 * The reason comes last and in full. "It failed" leaves an administrator
 * guessing between a wrong password, a closed port and a host that never
 * answered — and those are three different afternoons.
 */
function FailedEmailRow({ failure }: { failure: FailedEmail }) {
  const { t } = useTranslation("common");
  return (
    <li
      data-testid="failed-email-row"
      className="rounded-lg border border-border p-3 space-y-1"
    >
      <div className="flex items-start justify-between gap-2 flex-wrap">
        <span className="text-sm font-semibold text-on truncate">
          {failure.to_email}
        </span>
        <span className="text-xs text-on-muted tabular-nums">
          {t("settings.failedEmails.attempts", {
            n: failure.attempts,
            max: failure.max_attempts,
          })}
          {" · "}
          {formatDateMedium(failure.created_at)}
        </span>
      </div>
      <p className="text-xs text-on-secondary truncate">{failure.subject}</p>
      {failure.last_error && (
        <p className="text-xs text-on-danger break-words">
          {t("settings.failedEmails.reason", { reason: failure.last_error })}
        </p>
      )}
    </li>
  );
}
