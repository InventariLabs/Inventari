import { Plus, QrCode } from "lucide-react";
import { useTranslation } from "react-i18next";
import { EmptyState, EmptyStateAction } from "@/components/ui/EmptyState";

interface LabelPoolEmptyStateProps {
  /** Whether the pool is genuinely empty, or only empty under the active filter. */
  filtered: boolean;
  onGenerate: () => void;
  /** Whether to offer generating one — it asks for `items:write`. */
  canWrite?: boolean;
  onShowAll: () => void;
}

/**
 * What the label list shows when it has no rows.
 *
 * Two states in one place, because they lead opposite ways: an empty pool wants
 * codes generated, a filtered-out pool wants the filter cleared. Lives here
 * rather than inline so the page's own branching stays about the list.
 */
export function LabelPoolEmptyState({
  filtered,
  onGenerate,
  canWrite = true,
  onShowAll,
}: LabelPoolEmptyStateProps) {
  const { t } = useTranslation(["labels", "common"]);

  return (
    <EmptyState
      icon={QrCode}
      title={filtered ? t("status.noLabelsFiltered") : t("status.noLabels")}
      description={
        filtered
          ? t("status.noLabelsFilteredSubtitle")
          : t("status.noLabelsSubtitle")
      }
      primaryAction={
        filtered ? (
          <EmptyStateAction
            // Outline, not the filled default: the header's generate owns
            // the view's primary slot, and a second filled button beside it
            // read as two competing first moves.
            variant="outline"
            label={t("status.showAllLabels")}
            onClick={onShowAll}
          />
        ) : canWrite ? (
          <EmptyStateAction
            variant="outline"
            label={t("status.generateFirst")}
            onClick={onGenerate}
            leftIcon={Plus}
          />
        ) : undefined
      }
    />
  );
}
