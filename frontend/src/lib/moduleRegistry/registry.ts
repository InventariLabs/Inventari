import { onCatalogLoaded } from "@/i18n/config";
import { logger } from "@/utils/logger";
import { CORE_SECTION_NAV } from "./coreSections";
import {
  applyI18nOverrides,
  applyThemeOverrides,
  noteCatalogLanded,
} from "./registryI18nTheme";
import { RegistryQueries } from "./registryQueries";
import type {
  ColumnContributor,
  CoreFormName,
  FrontendModule,
  ListFilterContributor,
} from "./moduleInterfaces";

/**
 * The paths of the nav items a module shows, as written.
 *
 * Not resolved against `basePath`: the shell links each item exactly as
 * written, so a relative path links nowhere, and reading it against the base
 * here let it pass a check the screen then failed.
 */
function shownNavPaths(
  mod: FrontendModule,
  isRegistered: (name: string) => boolean,
): string[] {
  // A nav item that needs a module nobody enabled is not shown, so no route
  // has to answer it (any one of `requiresModules` is enough).
  return mod
    .moduleNav!.items.filter(
      (item) =>
        !item.requiresModules?.length ||
        item.requiresModules.some(isRegistered),
    )
    .map((item) => item.path);
}

function matchPathPattern(navPath: string, routePath: string): boolean {
  const navSegments = navPath.split("/").filter(Boolean);
  const routeSegments = routePath.split("/").filter(Boolean);
  if (navSegments.length !== routeSegments.length) return false;
  return routeSegments.every(
    (seg, i) => seg.startsWith(":") || seg === navSegments[i],
  );
}

class ModuleRegistry {
  private modules = new Map<string, FrontendModule>();
  private columnContributors = new Map<string, ColumnContributor[]>();
  private listFilterContributors = new Map<string, ListFilterContributor[]>();
  private appliedI18nModules = new Set<string>();
  // Pristine namespace bundles, keyed `${lang}:${ns}` — the state before the
  // first override touched that pair; removals restore from here.
  private savedI18nBundles = new Map<string, Record<string, unknown>>();
  private appliedThemeModules = new Set<string>();
  private savedThemeVars = new Map<string, Record<string, string>>();
  readonly queries = new RegistryQueries(
    this.modules,
    this.columnContributors,
    this.listFilterContributors,
  );

  register(module: FrontendModule) {
    this.modules.set(module.name, module);
    if (module.columnContributors) {
      module.columnContributors.forEach((c) => {
        this.addColumnContributor("items", c);
      });
    }
    if (module.listFilterContributors) {
      module.listFilterContributors.forEach((c) => {
        this.addListFilterContributor("items", c);
      });
    }
  }

  /**
   * Warns about nav items of the named modules that no route answers.
   *
   * Run once the modules are registered rather than as each one registers:
   * a route another module hosts in this one's shell (`ModuleRoute.shell`)
   * counts, and that module may register later.
   */
  warnOrphanedNav(moduleNames: string[]) {
    const hosted = [...this.modules.values()].flatMap((m) => m.routes ?? []);
    moduleNames.forEach((name) => {
      const module = this.modules.get(name);
      if (!module?.moduleNav || !module.routes) return;
      const routes = [
        ...module.routes,
        ...hosted.filter((r) => r.shell === module.name),
      ];
      const paths = shownNavPaths(module, (n) => this.modules.has(n));
      const relative = paths.filter((p) => !p.startsWith("/"));
      if (relative.length > 0) {
        logger.warn(
          `[ModuleRegistry] Module "${module.name}" has moduleNav items whose ` +
            `path is not absolute (the shell links them as written): ` +
            relative.map((p) => JSON.stringify(p)).join(", "),
        );
      }
      const orphanedNav = paths
        .filter((p) => p.startsWith("/"))
        .filter(
          (p) =>
            !routes.some(
              (r) =>
                r.path === p ||
                (r.path.includes(":") && matchPathPattern(p, r.path)),
            ),
        );
      if (orphanedNav.length > 0) {
        logger.warn(
          `[ModuleRegistry] Module "${module.name}" has moduleNav items ` +
            `without matching routes: ${orphanedNav.join(", ")}`,
        );
      }
    });
  }

  /**
   * Development aid: names the `navOverrides` of the named modules whose
   * `targetPath` is no navigation item of the modules registered here.
   *
   * An override is matched by path alone, so one that matches nothing is
   * accepted in silence and hides or renames nothing. Run once the modules
   * are registered, like `warnOrphanedNav`: the item an override targets may
   * belong to a module that registers later. A target in a module this
   * organization has not enabled is named too — in development that is the
   * question worth asking.
   */
  warnUnmatchedNavOverrides(moduleNames: string[]) {
    if (!import.meta.env.DEV) return;
    const navPaths = new Set([
      ...Object.values(CORE_SECTION_NAV).map((item) => item.path),
      ...[...this.modules.values()].flatMap(
        (m) => m.moduleNav?.items.map((item) => item.path) ?? [],
      ),
    ]);
    moduleNames.forEach((name) => {
      const unmatched = (this.modules.get(name)?.navOverrides ?? [])
        .map((override) => override.targetPath)
        .filter((path) => !navPaths.has(path));
      if (unmatched.length > 0) {
        logger.warn(
          `[ModuleRegistry] Module "${name}" has navOverrides that match no ` +
            `navigation item of the modules loaded here: ${unmatched.join(", ")}`,
        );
      }
    });
  }

  getRoutes(enabledModules: string[]) {
    return this.queries.getRoutes(enabledModules);
  }

  getModule(name: string) {
    return this.queries.getModule(name);
  }

  getSlotComponents(slotName: string, enabledModules: string[]) {
    return this.queries.getSlotComponents(slotName, enabledModules);
  }

  getBulkActions(enabledModules: string[]) {
    return this.queries.getBulkActions(enabledModules);
  }

  /**
   * Rules a module contributes to one core form, in priority order.
   *
   * Callers go through `useModuleValidation`, which owns the contract for
   * running them (core errors win, a throwing rule is skipped). See the
   * `ValidationRule` type in `moduleInterfaces.ts`.
   */
  getValidationRules(form: CoreFormName, enabledModules: string[]) {
    return this.queries.getValidationRules(form, enabledModules);
  }

  getAllRegisteredModules() {
    return this.queries.getAllRegisteredModules();
  }

  getNavOverrides(enabledModules: string[]) {
    return this.queries.getNavOverrides(enabledModules);
  }

  getLabelPurposes(enabledModules: string[]) {
    return this.queries.getLabelPurposes(enabledModules);
  }

  getListFilterContributors(table: string, enabledModules: string[]) {
    return this.queries.getListFilterContributors(table, enabledModules);
  }

  getColumnContributors(table: string, enabledModules: string[]) {
    return this.queries.getColumnContributors(table, enabledModules);
  }

  getActionItemProviders(enabledModules: string[]) {
    return this.queries.getActionItemProviders(enabledModules);
  }

  applyI18nOverrides(enabledModules: string[]) {
    applyI18nOverrides(
      enabledModules,
      this.modules,
      this.appliedI18nModules,
      this.savedI18nBundles,
    );
  }

  /**
   * A translation catalog arrived through the dynamic i18n backend.
   *
   * Registrations no longer carry bundles — `src/i18n/config.ts` loads every
   * module catalog straight from its JSON file and announces it through
   * `onCatalogLoaded` — so this is where the ordering guarantee moved: a
   * catalog landing after the overrides must not bury them, and it becomes
   * the pristine state a removal restores. See `noteCatalogLanded`.
   */
  catalogLoaded(
    language: string,
    namespace: string,
    catalog: Record<string, unknown>,
  ) {
    noteCatalogLanded(
      language,
      namespace,
      catalog,
      this.modules,
      this.appliedI18nModules,
      this.savedI18nBundles,
    );
  }

  private addListFilterContributor(
    table: string,
    contributor: ListFilterContributor,
  ) {
    const existing = this.listFilterContributors.get(table) ?? [];
    const idx = existing.findIndex((c) => c.key === contributor.key);
    if (idx !== -1) existing[idx] = contributor;
    else existing.push(contributor);
    this.listFilterContributors.set(table, existing);
  }

  private addColumnContributor(table: string, contributor: ColumnContributor) {
    const existing = this.columnContributors.get(table) ?? [];
    const idx = existing.findIndex((c) => c.key === contributor.key);
    if (idx !== -1) {
      existing[idx] = contributor;
    } else {
      existing.push(contributor);
    }
    this.columnContributors.set(table, existing);
  }

  applyThemeOverrides(enabledModules: string[]) {
    applyThemeOverrides(
      enabledModules,
      this.modules,
      this.appliedThemeModules,
      this.savedThemeVars,
    );
  }

  hasOverrides(moduleName: string) {
    return this.queries.hasOverrides(moduleName);
  }

  getModulesWithLauncher(enabledModules: string[]) {
    return this.queries.getModulesWithLauncher(enabledModules);
  }

  getVisibleModules(enabledModules: string[], hiddenModules: string[] = []) {
    return this.queries.getVisibleModules(enabledModules, hiddenModules);
  }

  getOwnerModule(pathname: string, enabledModules: string[]) {
    return this.queries.getOwnerModule(pathname, enabledModules);
  }

  getShellModule(
    pathname: string,
    enabledModules: string[],
    focusModule?: string | null,
  ) {
    return this.queries.getShellModule(pathname, enabledModules, focusModule);
  }

  getAdoptedCoreNavItems(moduleName: string) {
    return this.queries.getAdoptedCoreNavItems(moduleName);
  }

  getBackgroundFeatures(moduleName: string, enabledModules: string[]) {
    return this.queries.getBackgroundFeatures(moduleName, enabledModules);
  }

  getKeptCoreNavItems(moduleName: string) {
    return this.queries.getKeptCoreNavItems(moduleName);
  }

  getShellNavItems(module: FrontendModule, focusModule?: string | null) {
    return this.queries.getShellNavItems(module, focusModule);
  }

  getStandaloneModules(enabledModules: string[]) {
    return this.queries.getStandaloneModules(enabledModules);
  }

  getModuleNav(moduleName: string) {
    return this.queries.getModuleNav(moduleName);
  }

  getSettingsSections(enabledModules: string[]) {
    return this.queries.getSettingsSections(enabledModules);
  }

  getSearchProviders(enabledModules: string[]) {
    return this.queries.getSearchProviders(enabledModules);
  }
}

export const moduleRegistry = new ModuleRegistry();

// The registry learns about landed catalogs from the i18n config, not the
// other way around: `src/i18n/config.ts` is reachable from the anonymous
// attestation tree, and `check:public-bundle` forbids that tree from reaching
// the registry. Subscribing here keeps the dependency pointing at the config.
onCatalogLoaded((language, namespace, catalog) => {
  moduleRegistry.catalogLoaded(language, namespace, catalog);
});
