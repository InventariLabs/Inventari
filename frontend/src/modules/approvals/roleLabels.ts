import type { TFunction } from "i18next";

const KNOWN_ROLES: readonly string[] = [
  "owner",
  "admin",
  "manager",
  "user",
  "viewer",
];

/**
 * Translate a workflow stage role identifier into its human label.
 *
 * The stage ``role`` field is an arbitrary label (never validated against the
 * RBAC roles), so custom roles fall back to the raw identifier instead of
 * rendering as a missing key.
 */
export function roleLabel(t: TFunction, role: string | null): string {
  // A user row's role is nullable on the wire; an absent role is rendered
  // the way an unknown identifier is — as nothing claimed about it.
  if (role != null && KNOWN_ROLES.includes(role)) {
    return t(`workflows.roles.${role}`, { defaultValue: role });
  }
  return role ?? "";
}
