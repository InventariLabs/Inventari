import { useEffect, useMemo, useState } from "react";
import { useEmployeeAutocomplete } from "@/modules/equipment/hooks/useEmployeeAutocomplete";
import { useOrganizationMembers } from "@/modules/settings/hooks/useOrganization";

interface UseAddressMatchesDirectoryParams {
  /** The hand-typed address, trimmed. */
  email: string;
  /** Off where no person is being named (location mode, a picked person). */
  enabled: boolean;
  /** The Partners register only exists when its module is on. */
  partnersEnabled: boolean;
}

/**
 * Whether a hand-typed address belongs to nobody either register knows —
 * the organization's accounts and the Partners employee book, the same two
 * the person picker searches. True is a signal, not a veto: equipment also
 * goes to people no directory knows (an intern, a contractor), so the
 * caller names the consequence and lets the save through.
 */
export function useAddressMatchesDirectory({
  email,
  enabled,
  partnersEnabled,
}: UseAddressMatchesDirectoryParams): boolean {
  // The check waits for the typing to settle: a keystroke-by-keystroke
  // lookup fired a request per character, and mid-address a correct
  // account reads as a typo until its last letter lands.
  const [settledEmail, setSettledEmail] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setSettledEmail(email), 400);
    return () => clearTimeout(timer);
  }, [email]);

  const checking = enabled && settledEmail.includes("@");
  const { data: memberData, isError: membersFailed } = useOrganizationMembers(
    0,
    20,
    settledEmail || undefined,
    { enabled: checking },
  );
  const { data: partnerData, isError: partnersFailed } =
    useEmployeeAutocomplete({
      search: settledEmail,
      enabled: partnersEnabled && checking,
    });

  return useMemo(() => {
    // A register that failed to answer cannot testify that the address is in
    // nobody's book: the warning stays quiet rather than call a correct
    // address a typo.
    if (!checking || membersFailed || partnersFailed || !memberData) {
      return false;
    }
    if (partnersEnabled && !partnerData) return false;
    const lower = settledEmail.toLowerCase();
    const memberHas = (memberData.items ?? []).some(
      (m) => m.email.toLowerCase() === lower,
    );
    const partnerHas = (partnerData?.items ?? []).some(
      (p) => p.email?.toLowerCase() === lower,
    );
    return !memberHas && !partnerHas;
  }, [
    checking,
    membersFailed,
    partnersFailed,
    memberData,
    partnerData,
    partnersEnabled,
    settledEmail,
  ]);
}
