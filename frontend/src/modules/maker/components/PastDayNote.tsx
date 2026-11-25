import { useTranslation } from "react-i18next";
import { todayIso } from "@/utils/formatters";

/**
 * The line under a run's day field once it names a day already past: the
 * stock and value statements count the run's movements on the day they are
 * recorded, not on the named day.
 */
export function PastDayNote({ day }: { day: string }) {
  const { t } = useTranslation("maker");
  if (!day || day >= todayIso()) return null;
  return (
    <p className="text-xs text-on-muted" data-testid="maker-past-day-note">
      {t("progress.pastDayNote")}
    </p>
  );
}
