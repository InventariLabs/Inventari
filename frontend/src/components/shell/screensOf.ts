import { matchPath } from "react-router-dom";
import { moduleRegistry } from "@/lib/moduleRegistry";

/**
 * The screens the enabled modules really draw, for the header Back's climb:
 * the path of a screen that answers it, not merely one that matches a route.
 *
 * - A route whose own modules are all switched off draws the not-found page.
 * - A path that only a parameter route accepts, while another route spells
 *   that segment out (`/inventory/locations/zone` under
 *   `/inventory/locations/zone/:zoneId`), is the folder of those screens, not
 *   an id: it would draw "not found".
 * - A module's root that its own navigation does not list is an address that
 *   sends the person on to another screen (the warehouse root opens History),
 *   so climbing to it only arrives back where the climb started.
 */
export function screensOf(
  enabledModules: string[],
  moduleNav: { basePath: string; items: { path: string }[] } | null,
): (path: string) => boolean {
  const routes = moduleRegistry
    .getRoutes(enabledModules)
    .filter(
      (route) =>
        !route.requiresModules ||
        route.requiresModules.some((name) => enabledModules.includes(name)),
    );
  const root = moduleNav?.basePath.replace(/\/+$/, "");
  const navPaths = moduleNav?.items.map((item) => item.path) ?? [];
  return (path) => {
    if (path === root && !navPaths.includes(path)) return false;
    return routes.some((route) => {
      const match = matchPath({ path: route.path, end: true }, path);
      if (!match) return false;
      const byParameter = Object.keys(match.params).length > 0;
      return (
        !byParameter ||
        !routes.some((other) => other.path.startsWith(`${path}/`))
      );
    });
  };
}
