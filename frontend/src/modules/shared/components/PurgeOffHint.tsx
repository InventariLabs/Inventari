import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { resolveAllowPermanentDelete, useHasPermission } from "@/module-sdk";
import { useOrganization } from "@/modules/settings/hooks/useOrganization";

/**
 * Where permanent deletion is switched on, said on the archive that would
 * offer it. An archive lists records that can only be restored while the
 * organization's switch is off; both the product and the equipment archive
 * carry this line. Shown once the organization has loaded and only while the
 * switch is off.
 *
 * The switch saves only for an administrator, so only one gets the link;
 * anyone else reads who can turn it on, as `HiddenRecordsNotice` does.
 */
export function PurgeOffHint() {
  const { t } = useTranslation("common");
  const { data: org } = useOrganization();
  const isAdmin = useHasPermission("admin:access");
  if (!org || resolveAllowPermanentDelete(org)) return null;
  return (
    <p className="mb-3 text-xs text-on-muted" data-testid="archived-purge-hint">
      {t("access.purgeOff")}{" "}
      {isAdmin ? (
        <Link
          to="/settings#permanent-delete"
          className="text-primary underline underline-offset-2"
        >
          {t("access.purgeOffLink")}
        </Link>
      ) : (
        t("access.hiddenRecordsAdminOnly")
      )}
    </p>
  );
}
