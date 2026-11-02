import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Card } from "@/components/ui/Card";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { Checkbox } from "@/components/ui/Checkbox";
import { useHasPermission } from "@/hooks/useHasPermission";
import {
  useOrganization,
  useUpdateOrganization,
} from "@/modules/settings/hooks/useOrganization";

/**
 * Org-level switch for mixing vertical-module data into the general lists.
 *
 * The isolation it governs used to be a constant in the Inventory page, which
 * made a policy question look like a rendering detail. It is a policy: one
 * organization runs equipment and groceries as separate worlds, another wants
 * a single list of everything it owns. Off is the default, and it is also the
 * only way to reach data a module left behind — the claim on a `context_tag`
 * outlives the module that made it, so turning this on is how an
 * administrator gets at assets after switching the module off.
 *
 * The switch saves on click, one card below a form that saves on a button.
 * Two save models on one screen are legitimate — a switch with its own Save
 * would be worse — as long as each says which it is, hence the line under the
 * description and the toast on the way back.
 */
export default function ModuleDataVisibilitySettings() {
  const { t } = useTranslation("common");
  const {
    data: org,
    isError: orgFailed,
    error: orgError,
    refetch: refetchOrg,
  } = useOrganization();
  const updateOrg = useUpdateOrganization();
  // `PUT /organizations` is admin-only, so a member could flip this switch and
  // watch the save bounce. The policy is worth reading either way — it explains
  // what the lists show — so the switch stays visible and says who owns it.
  const isAdmin = useHasPermission("admin:access");

  const current = org?.settings?.show_module_data === true;

  const handleChange = (checked: boolean) => {
    updateOrg.mutate(
      {
        settings: {
          ...(org?.settings ?? {}),
          show_module_data: checked,
        },
      },
      { onSuccess: () => toast.success(t("messages.saved")) },
    );
  };

  // Without the organization the switch would read "off" whatever is saved,
  // and flipping it would write over the real settings.
  if (orgFailed) {
    return (
      <Card id="module-data" className="p-4">
        <InlineQueryError error={orgError} onRetry={() => void refetchOrg()} />
      </Card>
    );
  }

  return (
    // The id is the target of the "/settings#module-data" deep link the
    // hidden-data empty states point at — the switch must be what the reader
    // lands on, not the top of this page. The row is the label: a 20x20
    // square is a target a thumb misses, and the words toggling the switch
    // grows the hit area without growing the square.
    <Card id="module-data" className="p-0">
      <label className="flex items-center justify-between gap-4 p-4 cursor-pointer">
        <div className="min-w-0">
          <p className="text-sm font-medium text-on">
            {t("settings.organization.moduleData.title")}
          </p>
          <p className="text-xs text-on-muted mt-0.5">
            {t("settings.organization.moduleData.description")}
          </p>
          <p className="text-xs text-on-muted mt-1">
            {t("settings.organization.moduleData.instantSave")}
          </p>
          {!isAdmin && (
            <p className="text-xs text-on-muted mt-1 italic">
              {t("settings.access.adminOnlyHint")}
            </p>
          )}
        </div>
        <Checkbox
          data-testid="module-data-toggle"
          className="h-6 w-6 shrink-0 md:h-5 md:w-5"
          checked={current}
          disabled={updateOrg.isPending || !isAdmin}
          aria-label={t("settings.organization.moduleData.label")}
          onChange={(e) => handleChange(e.target.checked)}
        />
      </label>
    </Card>
  );
}
