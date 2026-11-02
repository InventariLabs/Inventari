import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/Card";
import { useFormatOrgDay } from "@/hooks/useOrganizationTimezone";
import { queryKeys } from "@/hooks/queries/keys";
import { categoriesApi } from "@/lib/api/categories";
import { useLocationsById } from "@/module-sdk";
import { campaignScopeLabel } from "@/modules/equipment/components/campaignLabels";

interface CampaignParametersProps {
  scopeType: string;
  scopeFilterId: string | null;
  deadline: string;
  reminderDaysBefore: number;
  emailSubject: string | null;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs font-medium text-on-muted">{label}</dt>
      <dd className="text-sm text-on">{value}</dd>
    </div>
  );
}

/**
 * What this campaign will actually do, before it does it.
 *
 * A campaign sends email outside the organization, and its detail screen
 * showed none of what the creation dialog had asked for — not the scope, not
 * the reminder window, not the subject line. There was nothing to check
 * against before launching.
 */
export function CampaignParameters({
  scopeType,
  scopeFilterId,
  deadline,
  reminderDaysBefore,
  emailSubject,
}: CampaignParametersProps) {
  const { t } = useTranslation("equipment");
  // The deadline was pinned to the organization's clock on write; it is read
  // through that same clock, not the browser's.
  const formatOrgDay = useFormatOrgDay();

  // Names only decorate the scope label. A list that failed leaves the label
  // as the scope type alone — true, just less specific — so there is no empty
  // default to mistake for "no such storage".
  const { byId: places } = useLocationsById(
    scopeType === "STORAGE" ? [scopeFilterId] : [],
  );
  const { data: categories } = useQuery({
    queryKey: queryKeys.categories.equipmentScope,
    queryFn: () => categoriesApi.getAll(),
    enabled: scopeType === "CATEGORY",
  });

  const scope = useMemo(() => {
    const label = campaignScopeLabel(t, scopeType);
    if (scopeType === "ALL" || !scopeFilterId) return label;
    const named =
      scopeType === "STORAGE"
        ? places.get(scopeFilterId)?.name
        : categories?.find((c) => String(c.id) === scopeFilterId)?.name;
    return named ? `${label}: ${named}` : label;
  }, [t, scopeType, scopeFilterId, places, categories]);

  return (
    <Card className="p-4">
      <h2 className="text-sm font-semibold text-on mb-3">
        {t("attestation.parametersTitle")}
      </h2>
      <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Row label={t("attestation.scope.label")} value={scope} />
        <Row label={t("attestation.deadline")} value={formatOrgDay(deadline)} />
        <Row
          label={t("attestation.reminderDays")}
          value={String(reminderDaysBefore)}
        />
        <Row
          label={t("attestation.emailSubject")}
          value={emailSubject || t("attestation.emailSubjectDefault")}
        />
      </dl>
    </Card>
  );
}
