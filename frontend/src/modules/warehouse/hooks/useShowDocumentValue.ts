import { useDocumentProfile } from "@/modules/warehouse/hooks/useDocumentProfile";
import { showsDocumentValue } from "@/modules/warehouse/types";

/**
 * Whether price, VAT, totals or a value warning belong on this document's
 * screens: the profile's value tracking read through `showsDocumentValue`,
 * so no screen decides the rule on its own.
 *
 * Its own file because tests stand a different profile in for
 * `useDocumentProfile`; reading the rule from this module lets them state
 * the profile once and leave the rule itself real.
 */
export function useShowDocumentValue(type: string): boolean {
  const { data: profile } = useDocumentProfile();
  return showsDocumentValue(type, profile?.value_tracking_enabled ?? false);
}
