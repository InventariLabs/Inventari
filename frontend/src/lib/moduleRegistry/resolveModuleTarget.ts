import type { FrontendModule } from "./moduleInterfaces";

/**
 * Canonical navigation target for a module — shared by the Launcher tile
 * and the header ModuleSwitcher so both always land on the same page.
 *
 * Priority: launcher.linkTo > moduleNav.basePath > routes[0].path > "/".
 */
export function resolveModuleTarget(module: FrontendModule): string {
  return (
    module.launcher?.linkTo ??
    module.moduleNav?.basePath ??
    module.routes[0]?.path ??
    "/"
  );
}
