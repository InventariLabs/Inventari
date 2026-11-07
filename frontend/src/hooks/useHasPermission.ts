/**
 * useHasPermission -- the gate hook modules use to hide or show UI behind a
 * permission key.
 *
 * It now reads the permission set that GET /auth/me returns. Before that
 * existed the hook had nothing to check and answered `false` for every
 * non-admin, which meant permission-gated UI was really admin-gated UI: a
 * manager with `approvals:approve` still saw the button hidden while the API
 * would have accepted the call.
 *
 * Admin and superuser keep their bypass, matching `UserContextDTO.has_permission`
 * on the backend. The server sends admins the full catalog anyway; the shortcut
 * stays so the two cannot drift apart if the payload is stale.
 *
 * `permissions` is undefined until /auth/me resolves — and for user objects
 * from endpoints that do not compute it. Undefined means "not loaded", so the
 * hook falls back to the admin check rather than reporting a denial it cannot
 * actually support.
 *
 * Decision (kept deliberately): the hook does NOT tell "does not hold the
 * permission" apart from "permissions have not arrived yet". For a non-admin
 * the answer is `false` in both cases, i.e. it fails closed. A write
 * affordance that appears for a moment and is then withdrawn is the worse
 * flicker, and everything that needs the answer outside a page's first
 * paint — a dialog, a menu, a row action — opens long after /auth/me has
 * resolved, so the window is not met in practice. A caller that must say
 * "you lack X" in words (rather than merely hide a control) is such a
 * dialog; one that would render at first paint should gate on
 * `user.permissions !== undefined` itself.
 */
import { useAuthStore } from "@/store/authStore";
import type { User } from "@/types";

export function useHasPermission(permission: string): boolean {
  const user = useAuthStore((s) => s.user);
  return holdsPermission(user, permission);
}

/**
 * The hook's answer for a user already in hand — for a component that asks
 * about a list of keys it only knows at render time, one hook per key being
 * impossible there.
 */
export function holdsPermission(
  user: Pick<User, "role" | "is_superuser" | "permissions"> | null,
  permission: string,
): boolean {
  if (!user) return false;

  if (user.role === "admin" || user.is_superuser === true) return true;

  return user.permissions?.includes(permission) ?? false;
}
