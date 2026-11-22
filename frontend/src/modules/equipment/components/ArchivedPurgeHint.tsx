import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { resolveAllowPermanentDelete } from "@/module-sdk";
import { useOrganization } from "@/modules/settings/hooks/useOrganization";

/**
 * Where permanent deletion is switched on, said on the screen that would
 * offer it. The archived tab lists records that can only be restored while the
 * organization's switch is off, and nothing on it said the switch exists or
 * where it lives. Shown once the organization has loaded and only while the
 * switch is off.
 */
export function ArchivedPurgeHint() {
  const { t } = useTranslation("equipment");
  const { data: org } = useOrganization();
  if (!org || resolveAllowPermanentDelete(org)) return null;
  return (
    <p className="mb-3 text-xs text-on-muted" data-testid="archived-purge-hint">
      {t("list.purge_off_hint")}{" "}
      <Link
        to="/settings#permanent-delete"
        className="text-primary underline underline-offset-2"
      >
        {t("list.purge_off_link")}
      </Link>
    </p>
  );
}
