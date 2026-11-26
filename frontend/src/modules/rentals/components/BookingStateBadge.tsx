import { useTranslation } from "react-i18next";

import { Badge } from "@/module-sdk";

import type { BookingStatus } from "../api/rentals";

const STATUS_KEYS: Record<BookingStatus, string> = {
  RESERVED: "status.reserved",
  PICKED_UP: "status.picked_up",
  RETURNED: "status.returned",
  CANCELLED: "status.cancelled",
};

/** A booking's state, late winning over the stored status (it is derived). */
export function BookingStateBadge({
  status,
  isLate,
  lateDays,
}: {
  status: BookingStatus;
  isLate?: boolean;
  lateDays?: number;
}) {
  const { t } = useTranslation("rentals");
  if (isLate) {
    return (
      <Badge variant="danger">
        {lateDays && lateDays > 0
          ? t("status.lateDays", { count: lateDays })
          : t("status.late")}
      </Badge>
    );
  }
  const variant =
    status === "RESERVED"
      ? "info"
      : status === "PICKED_UP"
        ? "success"
        : status === "RETURNED"
          ? "secondary"
          : "outline";
  return <Badge variant={variant}>{t(STATUS_KEYS[status])}</Badge>;
}
