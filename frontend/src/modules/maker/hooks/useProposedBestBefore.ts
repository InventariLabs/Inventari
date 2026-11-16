import { useState } from "react";
import { defaultBestBefore } from "@/modules/maker/lib/bestBefore";

/**
 * A best-before that follows the day the goods are made until the person
 * types one: proposed from that day and the product's shelf life, kept as
 * typed once changed (``reset`` hands the proposal back).
 */
export function useProposedBestBefore(
  madeOn: string,
  shelfLifeDays: number | null | undefined,
) {
  const [typed, setTyped] = useState<string | null>(null);
  return {
    value: typed ?? defaultBestBefore(madeOn, shelfLifeDays),
    set: setTyped,
    reset: () => setTyped(null),
  };
}
