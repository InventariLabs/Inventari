import { api } from "@/lib/api/client";
import type { components } from "@/types/api-generated";

// Served by GET /stats/config at the stats:read level because the switch it
// carries is read by screens outside the analytics tab, while the generic
// module-settings endpoint is admin-only.
export type StatsConfig = components["schemas"]["StatsConfig"];

/**
 * The organization's stats-module config, by its one HTTP door.
 *
 * `show_inventory_value` is read outside the stats module: the products
 * list's footer, a product's own record, the valuation section and the
 * stock-as-of report all honour the switch, and a reader of those screens is
 * not necessarily a reader of the analytics tab. Naming the module's
 * namespace from Core is the same decision the stock-as-of report makes on
 * the backend — the switch belongs to the organization, and the figure it
 * withholds is not only the statistics screen's.
 */
export const statsConfigApi = {
  get: async (): Promise<StatsConfig> => {
    const response = await api.get<StatsConfig>("/stats/config");
    return response.data;
  },
};
