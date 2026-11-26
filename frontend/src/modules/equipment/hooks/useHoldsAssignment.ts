/**
 * Whether the signed-in user is the person holding this assignment (not a
 * place, not someone else), so the screen can word the return as theirs: a
 * holder hands a thing back, a manager accepts it. The holder is the address
 * on the row or, as the server answers in `held_by_viewer`, a partner
 * carrying the viewer's address — the rule "My assets" lists by.
 */
import { useIsSignedInAs } from "@/module-sdk";

export function useHoldsAssignment(
  assignment: {
    assigned_to_email?: string | null;
    holder_kind?: string | null;
    held_by_viewer?: boolean | null;
  } | null,
): boolean {
  const same = useIsSignedInAs(assignment?.assigned_to_email);
  const held = same || assignment?.held_by_viewer === true;
  return held && assignment?.holder_kind !== "location";
}
