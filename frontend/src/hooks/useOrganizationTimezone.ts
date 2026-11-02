import { useCallback } from "react";

import { useOrganization } from "@/modules/settings/hooks/useOrganization";
import { formatDateInZone, type DateVariant } from "@/utils/formatters";

/**
 * The timezone configured for the current organization, or `undefined`
 * while it is unknown.
 *
 * This is the one place that knows the organization's clock. The backend
 * pins some dates to it before storing (an attestation deadline is the end
 * of its own day in this zone), and those dates owe the reader this zone —
 * not the browser's. Rendering an org-clock day in the reader's zone is how
 * a form said "25" and the list a second later said "26".
 */
export function useOrganizationTimezone(): string | undefined {
  const { data: organization } = useOrganization();
  return organization?.timezone ?? undefined;
}

/**
 * Format an org-clock day: a value the backend pinned to the
 * organization's calendar (see `formatDateInZone` for the three date
 * families and which clock each owes the reader).
 *
 * While the organization is still loading the formatter falls back to the
 * browser's zone — the behaviour every reader saw before this hook existed,
 * one beat of it at worst, and no placeholder flash.
 *
 * *variant* is the shape the calling screen already prints its dates in —
 * a list of short dates keeps "09/30/2026" where a card of medium ones
 * keeps "Sep 30, 2026".
 */
export function useFormatOrgDay(
  variant: DateVariant = "date",
): (value: string | null | undefined) => string {
  const timezone = useOrganizationTimezone();
  // Memoised on the zone: a fresh function every render would re-run any
  // effect that lists it among its deps, and an effect that re-sets the
  // page header on every render loops.
  return useCallback(
    (value: string | null | undefined) =>
      formatDateInZone(value, timezone, { variant }),
    [timezone, variant],
  );
}
