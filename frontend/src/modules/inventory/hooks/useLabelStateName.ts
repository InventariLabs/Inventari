import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import type { LabelPool } from "@/types";

export type LabelState = "FREE" | "PRINTED" | "ASSIGNED" | "ARCHIVED";

/**
 * The one state a label is in — the same four the pool's filter tabs filter
 * by, so a row's pill and the tab that lists it can never use two words.
 */
export function labelState(label: LabelPool): LabelState {
  if (label.is_assigned) return label.is_item_deleted ? "ARCHIVED" : "ASSIGNED";
  return label.printed_at ? "PRINTED" : "FREE";
}

/** Names a label state — shared by the filter tabs and the status pills. */
export function useLabelStateName(): (state: LabelState) => string {
  const { t } = useTranslation(["labels"]);
  return useCallback(
    (state: LabelState) => {
      switch (state) {
        case "FREE":
          return t("labels:filters.statusFree");
        case "PRINTED":
          return t("labels:filters.statusPrinted");
        case "ASSIGNED":
          return t("labels:filters.statusAssigned");
        case "ARCHIVED":
          return t("labels:filters.statusArchived");
      }
    },
    [t],
  );
}

/** The pool's filter tabs: everything, then one tab per state. */
export function useLabelStatusTabs(): { value: string; label: string }[] {
  const { t } = useTranslation(["labels"]);
  const stateName = useLabelStateName();
  return [
    { value: "ALL", label: t("labels:filters.statusAll") },
    ...(["FREE", "PRINTED", "ASSIGNED", "ARCHIVED"] as const).map((state) => ({
      value: state,
      label: stateName(state),
    })),
  ];
}
