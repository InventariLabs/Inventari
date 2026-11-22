import type { LocationScope } from "@/module-sdk";

/**
 * What a production run may offer as the place its output goes.
 *
 * The run's goods are kept where they are put: what may hold stock, and not
 * a receiving area or the quarantine location, where goods wait or are held
 * back. The server refuses them as well; the picker never offers them.
 */
export const OUTPUT_LOCATION_SCOPE: LocationScope = {
  purpose: "stock",
  excludeHeldBack: true,
};
