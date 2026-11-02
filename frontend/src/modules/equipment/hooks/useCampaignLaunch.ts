import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useConfirm } from "@/hooks/useConfirm";
import { useLaunchCampaign } from "@/modules/equipment/hooks/useEquipment";
import { equipmentApi } from "@/modules/equipment/api/equipment";
import type {
  ScopePreview,
  ScopeType,
} from "@/modules/equipment/api/equipment_campaigns";
import { useOrganization } from "@/modules/settings/hooks/useOrganization";
import { announceLaunch } from "@/modules/equipment/lib/campaignRuns";

/** The scope of the campaign a row asks to launch. */
export interface LaunchableCampaign {
  id: string;
  scope_type: ScopeType;
  scope_filter_id?: string | null;
}

/**
 * Launching a campaign, with its confirmation, from wherever the reader is.
 *
 * Launching sends an attestation email to every assignee in scope and cannot
 * be undone, so it always asks first — and the question now carries the
 * number it is asking about. The reader used to walk through the
 * irreversible gate to learn, from the refusal behind it, that there was
 * nobody in scope to attest anything: the count is fetched before the
 * dialog, and a scope covering no assets is answered with where to fill it
 * in rather than with a launch that cannot succeed.
 *
 * The list screen and the campaign's own detail screen share this hook: the
 * detail screen used to tell the reader to launch the campaign while
 * offering no way to do it.
 */
export function useCampaignLaunch() {
  const { t } = useTranslation(["equipment", "common"]);
  const { confirm, confirmDialogProps } = useConfirm();
  // `mutate` is stable across renders (React Query v5 memoises it on the
  // observer); the result object is not — see the call sites' effect deps.
  const { mutate: launchCampaign } = useLaunchCampaign();
  const navigate = useNavigate();
  const [launchingId, setLaunchingId] = useState<string | null>(null);
  // The question names what will really happen: the New attestation dialog
  // says when the organization sends no mail, and so does this one.
  const { data: organization } = useOrganization();
  const canSendEmail = organization?.can_send_email === true;

  const launch = useCallback(
    async (campaign: LaunchableCampaign) => {
      const preview: ScopePreview | null = await equipmentApi
        .scopePreview(
          campaign.scope_type,
          campaign.scope_filter_id ?? undefined,
        )
        // A preview nobody could fetch must not block a launch the server may
        // well accept: the refusal belongs to the server, and it speaks it.
        .catch(() => null);

      if (preview && preview.assets === 0) {
        const go = await confirm({
          title: t("attestation.confirm.nothingToAttestTitle"),
          message: t("attestation.confirm.nothingToAttestMessage"),
          confirmLabel: t("attestation.confirm.nothingToAttestAction"),
        });
        if (go) navigate("/equipment/assignments");
        return;
      }

      const message = [
        !canSendEmail
          ? t("attestation.noEmailWarning")
          : preview
            ? t("attestation.confirm.launchMessageCounted", {
                people: preview.people,
                assets: preview.assets,
              })
            : t("attestation.confirm.launchMessage"),
        preview && preview.without_email > 0
          ? t("attestation.confirm.withoutEmail", {
              count: preview.without_email,
            })
          : null,
      ]
        .filter(Boolean)
        .join(" ");
      const ok = await confirm({
        title: t("attestation.confirm.launchTitle"),
        message,
        confirmLabel: t("attestation.confirm.launchConfirm"),
      });
      if (!ok) return;
      setLaunchingId(campaign.id);
      launchCampaign(campaign.id, {
        onSuccess: (run) => announceLaunch(t, run),
        onSettled: () => setLaunchingId(null),
      });
    },
    [t, confirm, navigate, launchCampaign, canSendEmail],
  );

  return { launch, launchingId, confirmDialogProps };
}
