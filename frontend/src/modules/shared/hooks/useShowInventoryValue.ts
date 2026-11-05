import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { statsConfigApi, type StatsConfig } from "@/lib/api/statsConfig";
import { queryKeys } from "@/hooks/queries/keys";
import { useModules } from "@/contexts/ModulesContext";

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
 * vocabulary it never asked to learn. An admin can flip it back.
 *
 * While the answer is on its way the value stays hidden: a profile that
 * withholds it must not show it for the first paint and take it back, and a
 * profile that shows it loses nothing by the figure arriving a moment later.
 * Where there is nothing to wait for — the stats module is off, so the
 * setting has no reader, or the config could not be read — the answer is
 * open, matching the backend default.
 */
export function useShowInventoryValue(): boolean {
  const { isLoading: modulesLoading } = useModules();
  const { data: config, isLoading } = useModuleQuery<StatsConfig>("stats", {
    queryKey: queryKeys.stats.config,
    queryFn: () => statsConfigApi.get(),
  });
  if (modulesLoading || isLoading) return false;
  return config?.show_inventory_value ?? true;
}
