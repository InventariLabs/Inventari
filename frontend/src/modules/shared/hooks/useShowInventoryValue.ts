import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { statsConfigApi, type StatsConfig } from "@/lib/api/statsConfig";
import { queryKeys } from "@/hooks/queries/keys";

/**
 * The one decision about showing stock value, for screens outside the stats
 * module — the products list's footer, the record's own overview, the
 * valuation section and the stock-as-of report.
 *
 * It lives in the shared layer, not in the stats module, because every
 * module may read it: an import of a module's internals is a boundary
 * crossing the moment it exists, while shared is the layer all modules may
 * lean on. The query itself reads `stats.show_inventory_value` through the
 * config endpoint the stats module serves at the read level.
 *
 * The home profile presets `show_inventory_value` off: a pantry keeps no
 * cost ledger for a figure to be read back from, and "cost layers" is
 * vocabulary it never asked to learn. An admin can flip it back. While the
 * config is loading — or when the stats module is off, where the setting has
 * no reader — the answer is open, matching the backend default.
 */
export function useShowInventoryValue(): boolean {
  const { data: config } = useModuleQuery<StatsConfig>("stats", {
    queryKey: queryKeys.stats.config,
    queryFn: () => statsConfigApi.get(),
  });
  return config?.show_inventory_value ?? true;
}
