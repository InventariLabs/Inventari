/**
 * useIsSignedInAs -- whether the signed-in user is the one a record names by
 * e-mail address (an assignment's holder, say). A module compares identity
 * through this rather than reading Core's auth store; addresses compare
 * without regard to case, and an absent address is nobody.
 */
import { useAuthStore } from "@/store/authStore";

export function useIsSignedInAs(email: string | null | undefined): boolean {
  const own = useAuthStore((s) => s.user?.email);
  return !!own && !!email && own.toLowerCase() === email.toLowerCase();
}
