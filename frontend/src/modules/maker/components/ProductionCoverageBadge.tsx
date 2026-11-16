import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/Badge";
import type { PlanCoverage } from "@/modules/maker/types/maker";

/**
 * How far the shelf covers a planned run once the runs planned before it
 * (by day, then by creation) have taken their share. Not the verdict
 * completion gives — that one is `ProductionShortageSignal`, read on the
 * shelf as it stands — but the plan's: two runs that each fit on the shelf
 * alone are not both covered.
 */
export function ProductionCoverageBadge({
  coverage,
}: {
  coverage: PlanCoverage | null | undefined;
}) {
  const { t } = useTranslation("maker");
  if (!coverage) return null;
  switch (coverage) {
    case "covered":
      return (
        <Badge variant="success" data-testid="maker-order-coverage">
          {t("coverage.covered")}
        </Badge>
      );
    case "partial":
      return (
        <Badge variant="warning" data-testid="maker-order-coverage">
          {t("coverage.partial")}
        </Badge>
      );
    case "short":
      return (
        <Badge variant="danger" data-testid="maker-order-coverage">
          {t("coverage.short")}
        </Badge>
      );
    default:
      return null;
  }
}
