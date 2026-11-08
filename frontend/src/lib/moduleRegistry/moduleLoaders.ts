import { logger } from "@/utils/logger";
import { moduleRegistry } from "./registry";

/**
 * The import that runs one module's registration.
 *
 * `App` used to glob every `module.ts` with `eager: true`, which put all of
 * them — their registration code and the API layer each drags in — into the
 * entry chunk for every reader, including organizations that had switched
 * most modules off. The glob without `eager` turns each file into a chunk of
 * its own, and these functions import only what an organization actually
 * uses. A module's `module.ts` registers itself as a side effect of import —
 * the same contract the eager glob relied on — so importing is registering.
 */
const loaders = import.meta.glob<unknown>("../../modules/*/module.ts");

function loaderFor(moduleName: string): (() => Promise<unknown>) | undefined {
  return loaders[`../../modules/${moduleName}/module.ts`];
}

/**
 * Registers the named modules.
 *
 * Names without a frontend module (`core`, `items` — core surfaces the
 * enabled list carries along) are skipped. A module whose chunk fails to
 * load is logged and skipped too: one broken module must not take the shell
 * down with it — the eager glob it replaces failed harder, taking the whole
 * entry chunk.
 */
export async function registerModules(enabledModules: string[]): Promise<void> {
  const wanted = enabledModules
    .map((name) => ({ name, load: loaderFor(name) }))
    .filter((entry): entry is { name: string; load: () => Promise<unknown> } =>
      Boolean(entry.load),
    );

  const results = await Promise.allSettled(wanted.map(({ load }) => load()));
  results.forEach((result, i) => {
    if (result.status === "rejected") {
      logger.error(
        `[ModuleRegistry] Failed to load module "${wanted[i].name}":`,
        result.reason,
      );
    }
  });
  const loaded = wanted.map(({ name }) => name);
  moduleRegistry.warnOrphanedNav(loaded);
  moduleRegistry.warnUnmatchedNavOverrides(loaded);
}
