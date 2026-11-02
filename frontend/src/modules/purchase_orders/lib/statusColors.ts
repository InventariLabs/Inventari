// Shared purchase-order / linked-receipt status → Badge variant mapping.
// Single source of truth so status colors stay consistent across the module.
export const STATUS_COLORS: Record<
  string,
  "default" | "success" | "warning" | "danger"
> = {
  DRAFT: "default",
  PENDING_APPROVAL: "warning",
  CONFIRMED: "success",
  COMPLETED: "success",
  CANCELLED: "danger",
};
