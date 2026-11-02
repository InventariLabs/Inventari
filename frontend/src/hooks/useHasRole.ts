/**
 * useHasRole -- role-membership gate for UI that should only render for
 * specific roles (e.g. destructive actions restricted to admin/manager,
 * 1b). Superusers bypass all role gates.
 */
import { useCallback } from "react";
import { useAuthStore } from "@/store/authStore";

export function useHasRole(roles: string[]): boolean {
  const user = useAuthStore((s) => s.user);

  if (!user) return false;
  if (user.is_superuser === true) return true;

  // The backend types the role nullable (a user row mid-provisioning);
  // no role matches no gate, which is what the old `role: string` hid.
  return user.role != null && roles.includes(user.role);
}

/**
 * The same gate as a predicate, for filtering lists of gated items.
 *
 * A list cannot call {@link useHasRole} per entry, and an ungated entry must
 * stay visible — so an empty or absent role list means "everyone".
 */
export function useRoleCheck(): (roles?: string[]) => boolean {
  const user = useAuthStore((s) => s.user);

  return useCallback(
    (roles?: string[]) => {
      if (!roles || roles.length === 0) return true;
      if (!user) return false;
      if (user.is_superuser === true) return true;
      return user.role != null && roles.includes(user.role);
    },
    [user],
  );
}
