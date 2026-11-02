/**
 * Who may open which settings screen — one decision for the whole group.
 *
 * The old arrangement protected screens by hiding their sidebar links, and
 * each page that bothered enforced it its own way: `<Navigate>` in one,
 * `navigate()` inside an effect in two others, nothing at all in
 * `/settings` (index), `/settings/modules/:name` and `/settings/audit-log`.
 * A child route therefore walked straight past the protection of its parent,
 * and a manager who typed the address got a screen full of switches the API
 * refuses to save.
 *
 * A screen opens for whoever holds the permission its own API asks for to
 * change what the screen shows — the same key, so the screen and the server
 * cannot disagree about a custom role. For most of the group that key is
 * `admin:access`, which is what `get_current_admin_user` asks; the screens
 * whose API asks for a narrower key are listed below. A screen opened by
 * `admin:access` while its API asked for `org:settings:write` was a grant that
 * could only be used through the API.
 *
 * Default is "administrator only": a settings screen added tomorrow is
 * protected until someone deliberately lists it below.
 */

/** Sub-paths of /settings any signed-in member may open. */
const MEMBER_SETTINGS_SEGMENTS = new Set<string>([
  // The licence and the source link are owed to every user (AGPL-3.0 §13).
  "about",
  // Each person's own name, language and password.
  "profile",
]);

/** Sub-paths of /settings opened by a key of their own, not `admin:access`. */
const KEYED_SETTINGS_SEGMENTS = new Map<string, string>([
  // The five writes of /ai-connections ask for it; reading is any member's,
  // because every AI feature reads the connection it runs on.
  ["ai", "org:settings:write"],
  // Every route of /roles asks for it, reads included.
  ["roles", "system:config:write"],
]);

/** What a module-contributed section says about itself, as far as access goes. */
interface KeyedSection {
  path: string;
  permission?: string;
}

/**
 * The permission a path under /settings needs, or `null` when every signed-in
 * member may open it.
 *
 * Matching is by first segment, so `/settings/modules/equipment` inherits the
 * answer given to `/settings/modules` — that is the hole this closes. A module
 * section that names its own `permission` is matched on its whole path, which
 * may have two segments (`modules/approvals`).
 */
export function settingsRoutePermission(
  pathname: string,
  sections: readonly KeyedSection[] = [],
): string | null {
  const rest = pathname
    .replace(/^\/settings\/?/, "")
    .replace(/\/+$/, "")
    .trim();

  // The index — the organisation's own profile — belongs to every member.
  if (rest === "") return null;

  const section = sections.find(
    (s) => s.permission && (rest === s.path || rest.startsWith(`${s.path}/`)),
  );
  if (section?.permission) return section.permission;

  const segment = rest.split("/")[0];
  if (MEMBER_SETTINGS_SEGMENTS.has(segment)) return null;
  return KEYED_SETTINGS_SEGMENTS.get(segment) ?? "admin:access";
}
