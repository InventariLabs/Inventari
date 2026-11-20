/**
 * "May this account permanently delete archived records here?"
 *
 * Two different questions, and a screen that offers the button asks both.
 * `allow_permanent_delete` is the organization's policy; `items:purge` is this
 * account's right, which the API checks on the other end. Offered without
 * either, the button ends in a refusal after the click.
 */
import { useHasPermission } from "@/hooks/useHasPermission";
import { useOrganization } from "@/modules/settings/hooks/useOrganization";

/** Business profiles that start with permanent deletion locked (mirrors the
 * backend resolver in items/_lifecycle.py). */
const PURGE_LOCKED_PROFILES = ["equipment_wms", "clean_core"];

/** Effective allow_permanent_delete: explicit setting wins, otherwise the
 *  product profile decides; legacy orgs without a profile stay allowed. */
export function resolveAllowPermanentDelete(
  org:
    | {
        settings?: Record<string, unknown> | null;
        active_profile_id?: string | null;
      }
    | null
    | undefined,
): boolean {
  const flag = org?.settings?.allow_permanent_delete;
  if (typeof flag === "boolean") {
    return flag;
  }
  return !PURGE_LOCKED_PROFILES.includes(org?.active_profile_id ?? "");
}

/** The organization's policy; false until the organization has loaded, so a
 *  locked organization never sees the button flash in. */
export function useAllowPermanentDelete(): boolean {
  const { data: org } = useOrganization();
  return org ? resolveAllowPermanentDelete(org) : false;
}

/** Policy allows it and the account holds `items:purge`. */
export function useCanPurge(): boolean {
  const allowed = useAllowPermanentDelete();
  const mayPurge = useHasPermission("items:purge");
  return allowed && mayPurge;
}
