import type { ReceivingSeed } from "./receive-seed";

/**
 * The two organisation-wide switches a value report needs: value tracking
 * (what a receipt cost is kept) and the stock value shown on the statistics.
 * A spec that turns them on runs in the one-worker `value-tracking` project
 * and puts them back.
 */

const PROFILE = "/api/v1/warehouse/profile";
const STATS_CONFIG = "/api/v1/stats/config";

/** The two switches. */
export interface Valuation {
  tracked: boolean;
  valueShown: boolean;
}

/** Set both switches, and return what they were. */
export async function setValuation(
  seed: ReceivingSeed,
  to: Valuation,
): Promise<Valuation> {
  const headers = { Authorization: `Bearer ${seed.token}` };
  const profile = await (await seed.request.get(PROFILE, { headers })).json();
  const stats = await (
    await seed.request.get(STATS_CONFIG, { headers })
  ).json();
  const put = await seed.request.put(PROFILE, {
    headers,
    data: { value_tracking_enabled: to.tracked },
  });
  if (!put.ok()) {
    throw new Error(`Could not set value tracking: ${await put.text()}`);
  }
  await seed.api.setModuleSettings(seed.token, "stats", {
    show_inventory_value: to.valueShown,
  });
  return {
    tracked: profile.value_tracking_enabled === true,
    valueShown: stats.show_inventory_value === true,
  };
}
