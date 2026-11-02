import { StatusBadge } from "@/components/ui/StatusBadge";

export type EquipmentStatus =
  "AVAILABLE" | "DEPLOYED" | "MAINTENANCE" | "RETIRED";

/**
 * Canonical status list — single source of truth (was duplicated across 3
 * files). Not exported: since the pickers moved to SELECTABLE_STATUSES below,
 * nothing outside this file needs the full list, and an export nobody imports
 * is what the dead-code gate is for.
 */
const EQUIPMENT_STATUSES: EquipmentStatus[] = [
  "AVAILABLE",
  "DEPLOYED",
  "MAINTENANCE",
  "RETIRED",
];

/**
 * Statuses that are consequences, not choices: an asset becomes DEPLOYED when
 * it is handed to someone (checkout) and RETIRED through an action that asks
 * first. No picker may offer them — a "deployed" row with nobody holding it
 * is exactly the lie these guards exist to prevent.
 */
export const CONSEQUENCE_STATUSES: EquipmentStatus[] = ["DEPLOYED", "RETIRED"];

/** The statuses a picker may set. */
export const SELECTABLE_STATUSES: EquipmentStatus[] = EQUIPMENT_STATUSES.filter(
  (status) => !CONSEQUENCE_STATUSES.includes(status),
);

export const STATUS_VARIANT: Record<
  EquipmentStatus,
  "success" | "info" | "warning" | "secondary"
> = {
  AVAILABLE: "success",
  DEPLOYED: "info",
  MAINTENANCE: "warning",
  RETIRED: "secondary",
};

interface AssetStatusBadgeProps {
  /** Null when no status exists at all — read as an absence, like any
   *  value outside the four. */
  status: EquipmentStatus | string | null;
  className?: string;
}

/**
 * The asset's state, or the fact that it has none.
 *
 * A value outside the four reads as an absence, never as a name. StatusBadge
 * falls back to printing the raw string when no translation answers, which is
 * how a spreadsheet cell reading BANANA came to stand in the STATUS column
 * beside AVAILABLE and IN SERVICE, and on the asset card as its state. The
 * backend contract says the same thing about "UNKNOWN": it is not a state,
 * and it must never reach a screen as if it were a name.
 */
export function AssetStatusBadge({ status, className }: AssetStatusBadgeProps) {
  const known = EQUIPMENT_STATUSES.includes(status as EquipmentStatus);
  return (
    <StatusBadge
      status={status}
      ns="equipment"
      variants={STATUS_VARIANT}
      labelKey={known ? undefined : "status.unknown"}
      className={className}
    />
  );
}
