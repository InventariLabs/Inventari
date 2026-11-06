import { useCallback, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  employeeSearchQuery,
  useEmployeeAutocomplete,
} from "@/modules/equipment/hooks/useEmployeeAutocomplete";
import {
  organizationMembersQuery,
  useOrganizationMembers,
} from "@/modules/settings/hooks/useOrganization";

interface UseAddressMatchesDirectoryParams {
  /** The hand-typed address, trimmed. */
  email: string;
  /** Off where no person is being named (location mode, a picked person). */
  enabled: boolean;
  /** The Partners register only exists when its module is on. */
  partnersEnabled: boolean;
}

export interface AddressCheck {
  /** The settled address belongs to nobody either register knows. */
  unmatched: boolean;
  /**
   * Whether the save of the address in the field must stop to show the
   * warning first: true when it matches nobody and the warning was not yet
   * on screen for it. The registers are asked now, not after the settle
   * window, and the warning rises by the same call — so an address pasted
   * and submitted inside the window is named before it is stored.
   */
  holdForWarning: () => Promise<boolean>;
}

type Register = { items?: Array<{ email?: string | null }> } | undefined;

const knows = (register: Register, lower: string) =>
  (register?.items ?? []).some((entry) => entry.email?.toLowerCase() === lower);

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
}: UseAddressMatchesDirectoryParams): AddressCheck {
  const queryClient = useQueryClient();
  // The highlighting waits for the typing to settle: a keystroke-by-keystroke
  // lookup fired a request per character, and mid-address a correct
  // account reads as a typo until its last letter lands. The save does not
  // wait for it — see `holdForWarning`.
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

  const unmatched = useMemo(() => {
    // A register that failed to answer cannot testify that the address is in
    // nobody's book: the warning stays quiet rather than call a correct
    // address a typo.
    if (!checking || membersFailed || partnersFailed || !memberData) {
      return false;
    }
    if (partnersEnabled && !partnerData) return false;
    const lower = settledEmail.toLowerCase();
    return !knows(memberData, lower) && !knows(partnerData, lower);
  }, [
    checking,
    membersFailed,
    partnersFailed,
    memberData,
    partnerData,
    partnersEnabled,
    settledEmail,
  ]);

  const holdForWarning = useCallback(async () => {
    if (!enabled || !email.includes("@")) return false;
    // The warning already stands for this very address: the reader has
    // seen it and saves anyway, which the check allows.
    if (unmatched && settledEmail === email) return false;
    let nobodys: boolean;
    try {
      const [members, partners] = await Promise.all([
        queryClient.fetchQuery(organizationMembersQuery(0, 20, email)),
        partnersEnabled
          ? queryClient.fetchQuery(employeeSearchQuery(email))
          : undefined,
      ]);
      const lower = email.toLowerCase();
      nobodys = !knows(members, lower) && !knows(partners, lower);
    } catch {
      // Same rule as the highlighting: no answer, no accusation.
      return false;
    }
    // The answers are in the cache under the keys the highlighting reads,
    // so settling on this address shows the warning on the next render.
    setSettledEmail(email);
    return nobodys;
  }, [enabled, email, unmatched, settledEmail, queryClient, partnersEnabled]);

  return { unmatched, holdForWarning };
}
