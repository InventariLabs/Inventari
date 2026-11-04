/**
 * Whether the signed-in user is the person holding this assignment (not a
 * place, not someone else), so the screen can word the return as theirs: a
 * holder hands a thing back, a manager accepts it.
 */
import { useIsSignedInAs } from "@/module-sdk";

export function useHoldsAssignment(
  assignment: {
    assigned_to_email?: string | null;
    holder_kind?: string | null;
  } | null,
): boolean {
  const same = useIsSignedInAs(assignment?.assigned_to_email);
  return same && assignment?.holder_kind !== "location";
}
