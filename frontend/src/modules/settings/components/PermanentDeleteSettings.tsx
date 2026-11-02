import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Card } from "@/components/ui/Card";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { Checkbox } from "@/components/ui/Checkbox";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useHasPermission } from "@/hooks/useHasPermission";
import {
  useOrganization,
  useUpdateOrganization,
} from "@/modules/settings/hooks/useOrganization";

/**
 * Org-level switch for permanent deletion.
 *
 * Described by its effect, not by the field name: turning it on hands users
 * an irreversible action, which is why audited business profiles default to
 * off. The toggle writes the explicit `allow_permanent_delete` setting; when
 * unset, the backend derives the value from the product profile.
 *
 * Arming an irreversible action took one click and said nothing back, which
 * is a lot of consequence for a checkbox. Turning it on now asks first;
 * turning it off is the safe direction and saves straight away.
 */
export default function PermanentDeleteSettings() {
  const { t } = useTranslation("common");
  const {
    data: org,
    isError: orgFailed,
    error: orgError,
    refetch: refetchOrg,
  } = useOrganization();
  const updateOrg = useUpdateOrganization();
  // Same as the module-data switch: readable by every member, writable by an
  // administrator, and the screen says so instead of failing on save.
  const isAdmin = useHasPermission("admin:access");
  const [confirmingEnable, setConfirmingEnable] = useState(false);

  const flag = org?.settings?.allow_permanent_delete;
  const current =
    typeof flag === "boolean"
      ? flag
      : !["equipment_wms", "clean_core"].includes(org?.active_profile_id ?? "");

  const save = (checked: boolean) => {
    updateOrg.mutate(
      {
        settings: {
          ...(org?.settings ?? {}),
          allow_permanent_delete: checked,
        },
      },
      { onSuccess: () => toast.success(t("messages.saved")) },
    );
  };

  const handleChange = (checked: boolean) => {
    if (checked) {
      setConfirmingEnable(true);
      return;
    }
    save(false);
  };

  // Without the organization the switch would show the profile default as
  // the saved choice, and flipping it would write over the real settings.
  if (orgFailed) {
    return (
      <Card className="p-4">
        <InlineQueryError error={orgError} onRetry={() => void refetchOrg()} />
      </Card>
    );
  }

  return (
    // Same class as the module-data card: the row is the label, so the words
    // toggle the switch and the hit area grows without the square doing it.
    <>
      <Card className="p-0">
        <label className="flex items-center justify-between gap-4 p-4 cursor-pointer">
          <div className="min-w-0">
            <p className="text-sm font-medium text-on">
              {t("settings.organization.permanentDelete.title")}
            </p>
            <p className="text-xs text-on-muted mt-0.5">
              {t("settings.organization.permanentDelete.description")}
            </p>
            <p className="text-xs text-on-muted mt-1">
              {t("settings.organization.permanentDelete.instantSave")}
            </p>
            {!isAdmin && (
              <p className="text-xs text-on-muted mt-1 italic">
                {t("settings.access.adminOnlyHint")}
              </p>
            )}
          </div>
          <Checkbox
            data-testid="permanent-delete-toggle"
            className="h-6 w-6 shrink-0 md:h-5 md:w-5"
            checked={current}
            disabled={updateOrg.isPending || !isAdmin}
            aria-label={t("settings.organization.permanentDelete.label")}
            onChange={(e) => handleChange(e.target.checked)}
          />
        </label>
      </Card>

      <ConfirmDialog
        open={confirmingEnable}
        variant="danger"
        title={t("settings.organization.permanentDelete.confirmTitle")}
        message={t("settings.organization.permanentDelete.confirmMessage")}
        confirmLabel={t("settings.organization.permanentDelete.confirmAction")}
        onConfirm={() => {
          setConfirmingEnable(false);
          save(true);
        }}
        onCancel={() => setConfirmingEnable(false)}
      />
    </>
  );
}
