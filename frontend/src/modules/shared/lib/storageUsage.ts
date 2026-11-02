import type { TFunction } from "i18next";

// LocationUsage values (backend app.models.location.LocationUsage).
//
// Nobody picks one of these. A location a person creates is always
// "internal"; the other three are the virtual counterparts the system seeds
// per organization, and the only reason the front end knows their names is to
// mark such a row on a list as "not your shelf" (StorageLocationCard,
// StorageZoneCard). The picker that used to offer them is gone: choosing one
// took the shelf's contents out of stock, reports, purchase suggestions and
// scan lookup, and the shelf itself out of the tree it was reached from.
const STORAGE_USAGE_DEFAULT = "internal";

const VIRTUAL_USAGE_KEYS = ["customer", "inventory", "production"] as const;

type VirtualUsage = (typeof VIRTUAL_USAGE_KEYS)[number];

/** Whether this row is one of the system's virtual locations. */
export function isVirtualUsage(usage: string | null | undefined): boolean {
  return !!usage && usage !== STORAGE_USAGE_DEFAULT;
}

/**
 * Label for the badge on a virtual location.
 *
 * Falls back to the raw value: rows written before the Odoo-style roles were
 * dropped from the enum still carry them, and a stale row should read oddly,
 * not print a translation key at the person.
 */
export function virtualUsageLabel(t: TFunction, usage: string): string {
  return (VIRTUAL_USAGE_KEYS as readonly string[]).includes(usage)
    ? t(`locations:usage.${usage as VirtualUsage}`)
    : usage;
}
