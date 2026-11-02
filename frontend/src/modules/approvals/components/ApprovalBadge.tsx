import { useTranslation } from "react-i18next";
import { CheckCheck, Clock, XCircle, Ban } from "lucide-react";

import { Badge } from "@/components/ui/Badge";

const STATUS_CONFIG: Record<
  string,
  {
    variant: "warning" | "success" | "danger" | "default";
    icon: React.ReactNode;
  }
> = {
  PENDING: { variant: "warning", icon: <Clock size={12} /> },
  IN_PROGRESS: { variant: "warning", icon: <Clock size={12} /> },
  APPROVED: { variant: "success", icon: <CheckCheck size={12} /> },
  REJECTED: { variant: "danger", icon: <XCircle size={12} /> },
  CANCELLED: { variant: "default", icon: <Ban size={12} /> },
};

const STATUS_LABEL_KEYS: Record<string, string> = {
  PENDING: "request.waiting",
  IN_PROGRESS: "request.waiting",
  APPROVED: "request.approved",
  REJECTED: "request.rejected",
  CANCELLED: "request.cancelled",
};

interface ApprovalBadgeProps {
  status: string;
  /**
   * Where a multi-stage request stands. An open request then reads "Waiting
   * for approval — step 2 of 2", the same words the order's own list uses
   * for the same state.
   */
  stage?: { current: number; total: number };
  className?: string;
}

const OPEN_STATUSES = new Set(["PENDING", "IN_PROGRESS"]);

export function ApprovalBadge({
  status,
  stage,
  className,
}: ApprovalBadgeProps) {
  const { t } = useTranslation("approvals");
  const config = STATUS_CONFIG[status] ?? {
    variant: "default" as const,
    icon: null,
  };

  const showStep = OPEN_STATUSES.has(status) && stage && stage.total > 1;

  return (
    <Badge variant={config.variant} className={className}>
      <span className="flex items-center gap-1">
        {config.icon}
        {showStep
          ? t("request.waitingAtStep", {
              current: stage.current,
              total: stage.total,
            })
          : t(STATUS_LABEL_KEYS[status] ?? status, { defaultValue: status })}
      </span>
    </Badge>
  );
}
