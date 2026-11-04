import type { TFunction } from "i18next";
import type { ChoiceOption } from "@/components/ui/ChoiceGroup";
import type { EquipmentStatus } from "@/modules/equipment/components/AssetStatusBadge";

/** The state an asset comes back in — one choice for a single or a bulk return. */
export type CheckinCondition = "GOOD" | "DAMAGED" | "NEEDS_REPAIR";

const CHECKIN_CONDITIONS: CheckinCondition[] = [
  "GOOD",
  "DAMAGED",
  "NEEDS_REPAIR",
];

const LABEL_KEYS: Record<CheckinCondition, string> = {
  GOOD: "equipment:assignments.condition_good",
  DAMAGED: "equipment:assignments.condition_damaged",
  NEEDS_REPAIR: "equipment:assignments.condition_needs_repair",
};

const EFFECT_KEYS: Record<CheckinCondition, string> = {
  GOOD: "equipment:assignments.condition_effect_available",
  DAMAGED: "equipment:assignments.condition_effect_damaged",
  NEEDS_REPAIR: "equipment:assignments.condition_effect_needs_repair",
};

const STYLES: Record<CheckinCondition, string> = {
  GOOD: "border-success-500 bg-success-50 dark:bg-success-900/20 text-success-700 dark:text-success-300",
  DAMAGED:
    "border-red-400 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300",
  NEEDS_REPAIR:
    "border-amber-400 bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300",
};

/**
 * Where the asset goes when it comes back in this condition — the backend's
 * `SERVICE_CONDITIONS` rule: a damaged or needs-repair return opens a repair
 * entry and moves the asset to Maintenance.
 */
export function statusAfterCheckin(
  condition: CheckinCondition,
): EquipmentStatus {
  return condition === "GOOD" ? "AVAILABLE" : "MAINTENANCE";
}

/**
 * The condition choices, each saying what it does to the asset.
 *
 * The second radio took the asset out of circulation and filed a repair
 * entry, and the dialog said so nowhere: the person learnt it afterwards,
 * from the asset's page.
 */
export function checkinConditionOptions(t: TFunction): ChoiceOption[] {
  return CHECKIN_CONDITIONS.map((c) => ({
    id: c,
    label: t(LABEL_KEYS[c]),
    description: t(EFFECT_KEYS[c]),
    selectedClassName: STYLES[c],
  }));
}

/** What a bulk return is asked to do: one condition, one note, one place. */
export interface BulkReturnChoice {
  condition: CheckinCondition;
  notes?: string;
  /** Unset sends each asset back to its own location. */
  returnLocationId?: string;
}

/** The request a bulk return sends for the assets that are out. */
export function bulkReturnPayload(itemIds: string[], choice: BulkReturnChoice) {
  return {
    item_ids: itemIds,
    checkin_condition: choice.condition,
    checkin_notes: choice.notes,
    return_location_id: choice.returnLocationId,
  };
}

/** The bulk return's confirmation, naming the status when it is not Available. */
export function bulkReturnedText(
  t: TFunction,
  count: number,
  condition: CheckinCondition,
): string {
  const status = statusAfterCheckin(condition);
  return status === "AVAILABLE"
    ? t("equipment:list.bulk_returned", { count })
    : t("equipment:list.bulk_returned_status", {
        count,
        status: t(`equipment:status.${status.toLowerCase()}`),
      });
}
