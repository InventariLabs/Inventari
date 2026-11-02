import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/Card";
import { JournalCard } from "@/components/ui/JournalCard";
import { QueryFailure } from "@/components/ui/QueryResult";
import { formatRecentMoment } from "@/utils/formatters";
import { unitIdentifier } from "@/modules/equipment/components/assetUtils";
import { useActiveAssignments } from "@/modules/equipment/hooks/useEquipment";

/** How many check-outs the overview shows; the asset list holds the rest. */
const RECENT_ASSIGNMENTS_LIMIT = 5;

/**
 * The latest check-outs, newest first, on the equipment overview. Each row
 * names the unit as well as the model — four "PowerEdge R650" in a row tell
 * the reader nothing about which one went where.
 */
export function RecentAssignments() {
  const { t } = useTranslation("equipment");
  const { data, isLoading, isError, error, refetch } = useActiveAssignments();

  if (isError) {
    return (
      <Card className="p-4 sm:p-5">
        <QueryFailure error={error} onRetry={() => void refetch()} />
      </Card>
    );
  }

  const entries = (data?.items ?? [])
    .slice(0, RECENT_ASSIGNMENTS_LIMIT)
    .map((a) => {
      const identifier = unitIdentifier(a);
      return {
        id: a.id,
        tone: "info" as const,
        text: (
          <>
            <strong>{a.item_name}</strong>
            {identifier && (
              <span className="font-mono text-xs text-on-muted">
                {" "}
                {identifier}
              </span>
            )}{" "}
            {a.holder_kind === "location"
              ? t("dashboard.journal.placed_in", { holder: a.holder_name })
              : t("dashboard.journal.issued_to", {
                  holder: a.holder_name ?? a.partner_name ?? a.assigned_to_name,
                })}
          </>
        ),
        timeLabel: formatRecentMoment(a.checked_out_at),
        dateTime: a.checked_out_at,
        href: `/equipment/${a.item_id}`,
      };
    });

  return (
    <JournalCard
      title={t("dashboard.journal.title")}
      entries={entries}
      linkLabel={t("dashboard.journal.link")}
      linkHref="/equipment/assets?checked_out=1"
      loading={isLoading}
      empty={{ text: t("assignments.no_active") }}
    />
  );
}
