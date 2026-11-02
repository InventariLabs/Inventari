import { MEMBER_ROLES } from "./memberRoles";
import type { MemberRoleName } from "./memberRoles";

/**
 * One-line summary of what a role lets its holder do, shown next to the role
 * name on the member list — the reader cares about the powers, not the label.
 *
 * The built-in mapping mirrors the fallback permission sets in the backend's
 * `identity_service.py`: admin gets every permission, viewer reads only, and
 * user/manager read and write.
 */
export type MemberRoleAccess = "full" | "readWrite" | "readOnly";

const BUILTIN_ROLE_ACCESS: Record<MemberRoleName, MemberRoleAccess> = {
  admin: "full",
  manager: "readWrite",
  user: "readWrite",
  viewer: "readOnly",
};

/** Access summary for a built-in role; an unknown value reads as the least one. */
export function builtinRoleAccess(role: string): MemberRoleAccess {
  return (MEMBER_ROLES as readonly string[]).includes(role)
    ? BUILTIN_ROLE_ACCESS[role as MemberRoleName]
    : "readOnly";
}

/** Access summary for a custom role, derived from its permission set:
 *  `admin:access` reads as full access, anything beyond `*:read` as read and
 *  write, and a read-only (or empty) set as read only. */
export function customRoleAccess(permissions: string[]): MemberRoleAccess {
  if (permissions.includes("admin:access")) return "full";
  if (permissions.some((p) => !p.endsWith(":read"))) return "readWrite";
  return "readOnly";
}
