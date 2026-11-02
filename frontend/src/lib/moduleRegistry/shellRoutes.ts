import type { FrontendModule, ModuleRoute } from "./moduleInterfaces";

/**
 * The enabled modules as the router mounts them: the ones with a `moduleNav`
 * each get a shell holding its routes, the rest contribute flat routes.
 *
 * A route naming another module's shell (`ModuleRoute.shell`) renders inside
 * that shell, among the host's own routes, so the host links to a screen it
 * never imports. With the host switched off the route is not mounted at all:
 * outside its shell the screen loses the nav it was written for.
 */
export function shellRoutes(modules: FrontendModule[]): {
  shellModules: FrontendModule[];
  flatRoutes: ModuleRoute[];
} {
  const withNav = modules.filter((mod) => mod.moduleNav);
  const hosted = modules.flatMap((mod) => mod.routes.filter((r) => r.shell));
  return {
    shellModules: withNav.map((mod) => ({
      ...mod,
      routes: [
        ...mod.routes.filter((r) => !r.shell),
        ...hosted.filter((r) => r.shell === mod.name),
      ],
    })),
    flatRoutes: modules
      .filter((mod) => !mod.moduleNav)
      .flatMap((mod) => mod.routes.filter((r) => !r.shell)),
  };
}
