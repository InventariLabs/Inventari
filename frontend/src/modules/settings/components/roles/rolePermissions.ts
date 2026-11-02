import type { TFunction } from "i18next";
import type {
  PermissionCatalog,
  PermissionDefinition,
  Role,
} from "@/modules/settings/hooks/useRoles";

/**
 * What to call a role on screen.
 *
 * A built-in level's `name` is its slug — "user", "viewer" — because that is
 * what `User.role` stores. The members list has always shown these under
 * their proper names, and two screens naming the same level two ways is how
 * a reader concludes they are two levels. A custom role is named by whoever
 * wrote it and needs no translating.
 */
export function roleDisplayName(role: Role, t: TFunction<"common">): string {
  return role.is_system
    ? t(`settings.organization.memberRoles.${role.name}`, {
        defaultValue: role.name,
      })
    : role.name;
}

/** A run of permissions under one heading: the system group, then one per module. */
export interface PermissionGroup {
  id: string;
  /** Technical module name; absent for the system group. */
  module?: string;
  permissions: PermissionDefinition[];
}

/** How much of a group a role holds — the state its header checkbox shows. */
export type GroupState = "none" | "some" | "all";

/**
 * Split the catalog into the sections the editor renders.
 *
 * Empty sections are dropped: a module that declares no permission has nothing
 * to offer, and an empty accordion is a promise of content that is not there.
 */
export function permissionGroups(
  catalog: PermissionCatalog | undefined,
): PermissionGroup[] {
  if (!catalog) return [];
  return [
    { id: "system", permissions: catalog.system },
    ...catalog.modules.map((m) => ({
      id: m.module,
      module: m.module,
      permissions: m.permissions,
    })),
  ].filter((g) => g.permissions.length > 0);
}

export function groupState(
  group: PermissionGroup,
  granted: ReadonlySet<string>,
): GroupState {
  const held = group.permissions.filter((p) => granted.has(p.key)).length;
  if (held === 0) return "none";
  return held === group.permissions.length ? "all" : "some";
}

/**
 * What a role can do, in the areas it touches.
 *
 * The list row answers "what does this role do?" without opening anything,
 * which a row of thirty-three checkboxes never did — reading it meant scrolling
 * sideways and counting ticks.
 */
export interface RoleSummary {
  /** Total permissions held, including keys no enabled module declares. */
  count: number;
  /** Group ids the role touches, in catalog order. */
  areas: string[];
}

export function summarizeRole(
  role: Role,
  groups: PermissionGroup[],
): RoleSummary {
  const permissions = role.permissions ?? [];
  const granted = new Set(permissions);
  return {
    count: permissions.length,
    areas: groups
      .filter((g) => g.permissions.some((p) => granted.has(p.key)))
      .map((g) => g.id),
  };
}

/**
 * Permissions a role holds that no group offers.
 *
 * They come from a module that was disabled, or one whose manifest dropped the
 * key. The editor never shows them, so it must not drop them either: the saved
 * set is sent verbatim, and rebuilding it from the visible checkboxes alone
 * would silently revoke access the administrator never touched.
 */
export function invisiblePermissions(
  granted: ReadonlySet<string>,
  groups: PermissionGroup[],
): string[] {
  const known = new Set(groups.flatMap((g) => g.permissions.map((p) => p.key)));
  return [...granted].filter((key) => !known.has(key)).sort();
}

/** Filter a group's permissions by a search term over label and key. */
export function matchPermissions(
  permissions: PermissionDefinition[],
  term: string,
  labelOf: (permission: PermissionDefinition) => string,
): PermissionDefinition[] {
  const needle = term.trim().toLowerCase();
  if (!needle) return permissions;
  return permissions.filter(
    (p) =>
      labelOf(p).toLowerCase().includes(needle) ||
      p.key.toLowerCase().includes(needle),
  );
}
