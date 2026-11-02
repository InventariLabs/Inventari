import type { FrontendModule } from "@/lib/moduleRegistry";
import type { LauncherCategory, ProductProfile } from "@/types";

const DEFAULT_CATEGORY: LauncherCategory = "business";

/**
 * Resolves the launcher section for a single module using:
 *   1. The active profile's `launcher_categories[module_name]` override
 *   2. The module's own `launcher.category` (legacy/default)
 *   3. The hard-coded "business" fallback
 *
 * Profile overrides win so that switching a workspace mode (e.g. food_home →
 * equipment_wms) reshuffles the launcher without requiring each module to
 * ship its own category metadata.
 */
export function resolveProfileCategory(
  mod: FrontendModule,
  profile: ProductProfile | null,
): LauncherCategory {
  const override = profile?.launcher_categories?.[mod.name];
  if (override) return override;
  const own = mod.launcher?.category;
  if (own) return own;
  return DEFAULT_CATEGORY;
}

/**
 * Batch helper — resolves the launcher section for every module in `mods`.
 * Preserves the order of `mods` in the returned object keys.
 */
export function resolveProfileCategories(
  mods: FrontendModule[],
  profile: ProductProfile | null,
): Record<string, LauncherCategory> {
  const result: Record<string, LauncherCategory> = {};
  for (const mod of mods) {
    result[mod.name] = resolveProfileCategory(mod, profile);
  }
  return result;
}
