import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/Badge";
import type { ProductionStatus } from "@/modules/maker/types/maker";

const COLOR_BY_STATUS: Record<ProductionStatus, string | undefined> = {
  DRAFT: "bg-amber-100 text-amber-700 border-amber-200",
  COMPLETED: "bg-accent-100 text-accent-700 border-accent-200",
  CANCELLED: "bg-surface-raised text-on-secondary border-border",
  REVERSED: "bg-surface-raised text-on-secondary border-border",
};

export function ProductionStatusBadge({
  status,
}: {
  /** The wire types the status as a plain string; an unknown value shows unstyled. */
  status: string;
}) {
  const { t } = useTranslation("maker");
  // The labels live under productionList.status — pointing at a bare
  // `status.*` namespace made every badge fall through to its defaultValue
  // and print the raw enum ("COMPLETED") next to translated filter tabs.
  return (
    <Badge className={COLOR_BY_STATUS[status as ProductionStatus]}>
      {t(`productionList.status.${status.toLowerCase()}` as const, {
        defaultValue: status,
      })}
    </Badge>
  );
}
