import { ComponentType } from "react";

import {
  CORE_NAV_SECTION_PATHS,
  CORE_SECTION_NAV,
  getCoreNavSectionForPath,
  getCoreSectionForPath,
} from "./coreSections";
import type {
  AdoptableCoreSection,
  BulkAction,
  ColumnContributor,
  CoreFormName,
  LabelPurposeConfig,
  ListFilterContributor,
  FrontendModule,
  ModuleNavConfig,
  ModuleNavItem,
  NavOverride,
  ModuleRoute,
  SearchProvider,
  SettingsSection,
  SlotContribution,
  ValidationRule,
} from "./moduleInterfaces";
// ActionItem types come from FrontendModule.useActionItems — no standalone
// types needed.

export function applyNavOverrides(
  items: ModuleNavItem[],
  overrides: NavOverride[],
): ModuleNavItem[] {
  if (!overrides.length) return items;
  const overrideMap = new Map(overrides.map((o) => [o.targetPath, o] as const));
  return items
    .map((item) => {
      const override = overrideMap.get(item.path);
      if (!override) return item;
      if (override.hidden) return null;
      return {
        ...item,
        ...(override.icon ? { icon: override.icon } : {}),
        ...(override.labelKey ? { labelKey: override.labelKey } : {}),
      };
    })
    .filter((item): item is ModuleNavItem => item !== null);
}

export class RegistryQueries {
  constructor(
    private modules: Map<string, FrontendModule>,
    private columnContributors: Map<string, ColumnContributor[]>,
    private listFilterContributors: Map<
      string,
      ListFilterContributor[]
    > = new Map(),
  ) {}

  getRoutes(enabledModules: string[]): ModuleRoute[] {
    const routes: ModuleRoute[] = [];
    this.modules.forEach((module) => {
      if (enabledModules.includes(module.name)) {
        routes.push(...module.routes);
      }
    });
    return routes;
  }

  getModule(name: string): FrontendModule | undefined {
    return this.modules.get(name);
  }

  getSlotComponents(
    slotName: string,
    enabledModules: string[],
  ): Array<ComponentType<unknown>> {
    const contributions: SlotContribution[] = [];
    this.modules.forEach((module) => {
      if (enabledModules.includes(module.name) && module.slots) {
        module.slots.forEach((s) => {
          if (s.slot === slotName) {
            contributions.push(s);
          }
        });
      }
    });
    return contributions
      .sort((a, b) => (a.priority ?? 100) - (b.priority ?? 100))
      .map((c) => c.component as ComponentType<unknown>);
  }

  getBulkActions(enabledModules: string[]): BulkAction[] {
    const actions: BulkAction[] = [];
    this.modules.forEach((module) => {
      if (enabledModules.includes(module.name) && module.bulkActions) {
        actions.push(
          ...module.bulkActions.map((a) => ({ ...a, moduleName: module.name })),
        );
      }
    });
    return actions;
  }

  getValidationRules(
    form: CoreFormName,
    enabledModules: string[],
  ): ValidationRule[] {
    const rules: ValidationRule[] = [];
    this.modules.forEach((module) => {
      if (enabledModules.includes(module.name) && module.validationRules) {
        rules.push(...module.validationRules.filter((r) => r.form === form));
      }
    });
    return rules.sort((a, b) => (a.priority ?? 100) - (b.priority ?? 100));
  }

  getAllRegisteredModules(): string[] {
    return Array.from(this.modules.keys());
  }

  getNavOverrides(enabledModules: string[]): NavOverride[] {
    const overrides: NavOverride[] = [];
    this.modules.forEach((module) => {
      if (enabledModules.includes(module.name) && module.navOverrides) {
        overrides.push(...module.navOverrides);
      }
    });
    return overrides;
  }

  getLabelPurposes(enabledModules: string[]): LabelPurposeConfig[] {
    const purposes: LabelPurposeConfig[] = [];
    this.modules.forEach((module) => {
      if (enabledModules.includes(module.name) && module.labelPurpose) {
        purposes.push(module.labelPurpose);
      }
    });
    return purposes;
  }

  getColumnContributors(
    table: string,
    enabledModules: string[],
  ): ColumnContributor[] {
    return (this.columnContributors.get(table) ?? []).filter((c) =>
      enabledModules.includes(c.requiredModule),
    );
  }

  getListFilterContributors(
    table: string,
    enabledModules: string[],
  ): ListFilterContributor[] {
    return (this.listFilterContributors.get(table) ?? []).filter((c) =>
      enabledModules.includes(c.requiredModule),
    );
  }

  hasOverrides(moduleName: string): boolean {
    const mod = this.modules.get(moduleName);
    if (!mod) return false;
    // An empty declaration ({}) wears the "Changes the interface" badge
    // without changing anything — only non-empty overrides count.
    return Boolean(
      mod.navOverrides?.length ||
      Object.keys(mod.i18nOverrides ?? {}).length ||
      Object.keys(mod.theme?.cssVariables ?? {}).length,
    );
  }

  getModulesWithLauncher(enabledModules: string[]): FrontendModule[] {
    const result: FrontendModule[] = [];
    this.modules.forEach((module) => {
      if (
        enabledModules.includes(module.name) &&
        module.launcher &&
        !module.launcher.hidden
      ) {
        result.push(module);
      }
    });
    return result.sort(
      (a, b) => (a.launcher!.order ?? 100) - (b.launcher!.order ?? 100),
    );
  }

  /**
   * The listing view of enabled modules — launcher tiles, switcher entries,
   * palette browse. Same set as {@link getModulesWithLauncher} minus any
   * module the current context hides: single-module focus hides every module
   * except the focused one.
   */
  getVisibleModules(
    enabledModules: string[],
    hiddenModules: string[] = [],
  ): FrontendModule[] {
    return this.getModulesWithLauncher(enabledModules).filter(
      (module) => !hiddenModules.includes(module.name),
    );
  }

  /**
   * The module that owns `pathname` — the longest matching
   * `moduleNav.basePath` among the enabled modules wins, so a deeper base
   * path takes precedence over a shallower one that prefixes it.
   *
   * Deliberately broader than the launcher listing: it also matches modules
   * that are hidden from navigation (focus mode) or declare no launcher
   * tile, because a direct link into one still needs its shell and header.
   * Returns null when no enabled module claims the path.
   */
  getOwnerModule(
    pathname: string,
    enabledModules: string[],
  ): FrontendModule | null {
    let owner: FrontendModule | null = null;
    for (const module of this.modules.values()) {
      const basePath = module.moduleNav?.basePath;
      if (!basePath || !enabledModules.includes(module.name)) continue;
      if (!pathname.startsWith(basePath)) continue;
      const ownerBasePath = owner?.moduleNav?.basePath ?? "";
      if (basePath.length > ownerBasePath.length) {
        owner = module;
      }
    }
    return owner;
  }

  /**
   * The module whose shell chrome (banner, tab bar, theme) `pathname` renders
   * under — path ownership plus standalone adoption.
   *
   * Pure ownership stays with {@link getOwnerModule}: a hidden module opened
   * from a direct link keeps its own shell. The one exception is the promise a
   * standalone declaration makes — when the organization focuses on a module
   * that adopts a core section, that section's pages render under the focus
   * module's banner, because the owning module's navigation is hidden and the
   * section (the label pool, the scanner) must keep a home. A section the
   * focus module renounces falls through to the owner untouched — unless the
   * module keeps the list the section hangs under (the archive of kept items).
   */
  getShellModule(
    pathname: string,
    enabledModules: string[],
    focusModule?: string | null,
  ): FrontendModule | null {
    if (focusModule && enabledModules.includes(focusModule)) {
      const focus = this.modules.get(focusModule);
      if (focus?.standalone) {
        const section = getCoreSectionForPath(pathname);
        if (section && focus.standalone.coreSections[section] === "adopt") {
          return focus;
        }
        // A renounced section still falls through to the kept check: the
        // archive hangs under the items and storages prefixes, and the
        // Active/Archived switch on a kept list must not leave the banner.
        const kept = getCoreNavSectionForPath(pathname);
        if (kept && focus.standalone.keepCoreNav?.includes(kept)) {
          return focus;
        }
      }
    }
    return this.getOwnerModule(pathname, enabledModules);
  }

  /**
   * The core-section nav entries a standalone module adopted — what the shell
   * appends to the module's own tabs in focus mode so an adopted section
   * (labels, scanner) keeps a visible home under the module's banner.
   */
  getAdoptedCoreNavItems(moduleName: string): ModuleNavItem[] {
    const declaration = this.modules.get(moduleName)?.standalone;
    if (!declaration) return [];
    return (
      Object.entries(declaration.coreSections) as Array<
        [AdoptableCoreSection, "adopt" | "renounce"]
      >
    )
      .filter(([, decision]) => decision === "adopt")
      .map(([section]) => CORE_SECTION_NAV[section]);
  }

  /**
   * The core nav entries (products, stock, ...) a standalone module keeps via
   * `keepCoreNav`. They are the inventory module's own items, so the icon,
   * label and `requiresModules` rules stay in one place. The declaring module
   * counts as one of the modules that satisfy a kept entry's `requiresModules`:
   * keeping the entry is the module's own promise, and focus may have switched
   * off every other module the rule names.
   */
  getKeptCoreNavItems(moduleName: string): ModuleNavItem[] {
    const keep = this.modules.get(moduleName)?.standalone?.keepCoreNav ?? [];
    const inventoryItems =
      this.modules.get("inventory")?.moduleNav?.items ?? [];
    return keep.flatMap((section) => {
      const entry = CORE_NAV_SECTION_PATHS[section].entry;
      return inventoryItems
        .filter((item) => item.path === entry)
        .map((item) =>
          item.requiresModules
            ? {
                ...item,
                requiresModules: [...item.requiresModules, moduleName],
              }
            : item,
        );
    });
  }

  /**
   * The nav items the shell shows for `module`: its own `moduleNav.items`,
   * plus the adopted core sections when the module is the focus module
   * standing alone. Deduped by path — a module that one day lists an adopted
   * section statically must not get the tab twice.
   */
  getShellNavItems(
    module: FrontendModule,
    focusModule?: string | null,
  ): ModuleNavItem[] {
    const items = module.moduleNav?.items ?? [];
    if (!focusModule || module.name !== focusModule) return items;
    const extra = [
      ...this.getKeptCoreNavItems(module.name),
      ...this.getAdoptedCoreNavItems(module.name),
    ];
    if (!extra.length) return items;
    const known = new Set(items.map((item) => item.path));
    return [...items, ...extra.filter((item) => !known.has(item.path))];
  }

  /**
   * The enabled modules that declared they can stand alone — the choice list a
   * single-module mode offers. A module that did not declare `standalone` never
   * appears here, whatever the organization asks for.
   */
  getStandaloneModules(enabledModules: string[]): FrontendModule[] {
    const result: FrontendModule[] = [];
    this.modules.forEach((module) => {
      if (enabledModules.includes(module.name) && module.standalone) {
        result.push(module);
      }
    });
    return result.sort((a, b) => a.name.localeCompare(b.name));
  }

  getBackgroundFeatures(moduleName: string, enabledModules: string[]) {
    const declarations =
      this.modules.get(moduleName)?.standalone?.backgroundFeatures ?? [];
    return declarations.flatMap((declaration) => {
      if (!enabledModules.includes(declaration.provider)) return [];
      const component = this.modules.get(declaration.provider)
        ?.backgroundFeatures?.[declaration.feature];
      return component ? [{ ...declaration, component }] : [];
    });
  }

  getModuleNav(moduleName: string): ModuleNavConfig | undefined {
    return this.modules.get(moduleName)?.moduleNav;
  }

  getSettingsSections(
    enabledModules: string[],
  ): Array<SettingsSection & { moduleName: string }> {
    const result: Array<SettingsSection & { moduleName: string }> = [];
    this.modules.forEach((mod) => {
      if (!enabledModules.includes(mod.name)) return;
      if (!mod.settingsSections?.length) return;
      mod.settingsSections.forEach((section) => {
        result.push({ ...section, moduleName: mod.name });
      });
    });
    return result;
  }

  getSearchProviders(enabledModules: string[]): SearchProvider[] {
    const providers: SearchProvider[] = [];
    this.modules.forEach((mod) => {
      if (enabledModules.includes(mod.name) && mod.searchProvider) {
        providers.push(mod.searchProvider);
      }
    });
    return providers;
  }

  getActionItemProviders(enabledModules: string[]): Array<{
    moduleName: string;
    hook: NonNullable<FrontendModule["useActionItems"]>;
  }> {
    const result: Array<{
      moduleName: string;
      hook: NonNullable<FrontendModule["useActionItems"]>;
    }> = [];
    this.modules.forEach((mod) => {
      if (enabledModules.includes(mod.name) && mod.useActionItems) {
        result.push({ moduleName: mod.name, hook: mod.useActionItems });
      }
    });
    return result;
  }
}
