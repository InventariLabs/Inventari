import { StatusBadge } from "@/components/ui/StatusBadge";
import type { DocumentStatus } from "@/modules/warehouse/types";

const STATUS_VARIANT: Record<
  DocumentStatus,
  "secondary" | "info" | "success" | "danger" | "warning"
> = {
  DRAFT: "secondary",
  PENDING_APPROVAL: "warning",
  CONFIRMED: "info",
  COMPLETED: "success",
  CANCELLED: "danger",
};

interface DocumentStatusBadgeProps {
  status: string;
}

export function DocumentStatusBadge({ status }: DocumentStatusBadgeProps) {
  return (
    <StatusBadge
      status={status}
      ns="warehouse"
      variants={STATUS_VARIANT}
      // Document i18n keys are uppercase (`status.DRAFT`), not the lowercase convention.
      labelKey={`status.${status}`}
    />
  );
}
