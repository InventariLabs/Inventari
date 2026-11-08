import i18n from "i18next";

import { logger } from "@/utils/logger";
import type { FrontendModule } from "./moduleInterfaces";

/**
 * Module i18n overrides — a module can rename core vocabulary for the whole
 * organization while it is enabled ("Products" → "Assets").
 *
 * Override keys carry their namespace: `"inventory:nav.items"` targets the
 * `inventory` namespace, a key without a prefix targets `common`. Dotted
 * paths are nested into the bundle tree before they are added — handing
 * i18next a flat dotted key would store it *beside* the existing
 * `navigation: { items: ... }` tree, and `t()` would keep resolving
 * the nested original, so the override would never reach the screen.
 *
 * Restore works from pristine namespace snapshots: the first time any module
 * touches a (language, namespace) pair, the whole bundle is copied, and a
 * removal puts that copy back and re-applies the overrides of the modules
 * that stay enabled. A per-module snapshot cannot do this — taken after
 * another module applied, it would resurrect that module's labels when the
 * last override comes off.
 */

interface OverrideTarget {
  ns: string;
  path: string[];
  value: string;
}

function parseOverrideKey(key: string, value: string): OverrideTarget {
  const sep = key.indexOf(":");
  if (sep === -1) {
    return { ns: "common", path: key.split("."), value };
  }
  return { ns: key.slice(0, sep), path: key.slice(sep + 1).split("."), value };
}

function setDeep(
  bundle: Record<string, unknown>,
  path: string[],
  value: string,
): void {
  let node = bundle;
  for (const segment of path.slice(0, -1)) {
    const next = node[segment];
    if (typeof next !== "object" || next === null || Array.isArray(next)) {
      node[segment] = {};
    }
    node = node[segment] as Record<string, unknown>;
  }
  node[path[path.length - 1]] = value;
}

/** Whether *path* leads to a translated string in *bundle*. */
function hasString(bundle: Record<string, unknown>, path: string[]): boolean {
  let node: unknown = bundle;
  for (const segment of path) {
    if (typeof node !== "object" || node === null || !(segment in node)) {
      return false;
    }
    node = (node as Record<string, unknown>)[segment];
  }
  return typeof node === "string";
}

/**
 * Development aid: name the override keys *catalog* has no string for.
 *
 * *catalog* is the namespace's own translations before any override, so a key
 * missing from it is one no screen reads: the override is accepted, the badge
 * says the module changes the interface, and nothing on screen changes — which
 * is how two examples in the module guide did nothing for whoever copied them.
 * Checked only once the namespace's catalog is in: a catalog that has not
 * landed yet would make every key look missing.
 */
function warnUnmatchedKeys(
  module: FrontendModule,
  language: string,
  namespace: string,
  catalog: Record<string, unknown>,
): void {
  if (!import.meta.env.DEV || Object.keys(catalog).length === 0) return;
  const unmatched = Object.keys(module.i18nOverrides?.[language] ?? {}).filter(
    (key) => {
      const target = parseOverrideKey(key, "");
      return target.ns === namespace && !hasString(catalog, target.path);
    },
  );
  if (unmatched.length > 0) {
    logger.warn(
      `[ModuleRegistry] Module "${module.name}" overrides ${language} ` +
        `translation keys no catalog has, so they change nothing: ` +
        unmatched.join(", "),
    );
  }
}

function groupByNamespace(
  overrides: Record<string, string>,
): Map<string, Record<string, unknown>> {
  const byNs = new Map<string, Record<string, unknown>>();
  Object.entries(overrides).forEach(([key, value]) => {
    const target = parseOverrideKey(key, value);
    const bundle = byNs.get(target.ns) ?? {};
    setDeep(bundle, target.path, target.value);
    byNs.set(target.ns, bundle);
  });
  return byNs;
}

/** The (language, namespace) pairs a module's overrides touch. */
function targetedNamespaces(module: FrontendModule): string[] {
  const keys = new Set<string>();
  Object.entries(module.i18nOverrides ?? {}).forEach(([lang, overrides]) => {
    Object.keys(overrides).forEach((key) => {
      keys.add(`${lang}:${parseOverrideKey(key, "").ns}`);
    });
  });
  return [...keys];
}

function applyModuleI18n(module: FrontendModule): void {
  Object.entries(module.i18nOverrides ?? {}).forEach(([lang, overrides]) => {
    groupByNamespace(overrides).forEach((bundle, ns) => {
      i18n.addResourceBundle(lang, ns, bundle, true, true);
    });
  });
}

function applyI18nRemove(
  enabledModules: string[],
  modules: Map<string, FrontendModule>,
  appliedI18nModules: Set<string>,
  savedBundles: Map<string, Record<string, unknown>>,
): void {
  const toRemove = [...appliedI18nModules].filter(
    (m) => !enabledModules.includes(m),
  );
  if (toRemove.length === 0) return;

  const affected = new Set<string>();
  toRemove.forEach((moduleName) => {
    const module = modules.get(moduleName);
    if (module) {
      targetedNamespaces(module).forEach((key) => affected.add(key));
    }
    appliedI18nModules.delete(moduleName);
  });

  affected.forEach((langAndNs) => {
    const pristine = savedBundles.get(langAndNs);
    if (!pristine) return;
    const sep = langAndNs.indexOf(":");
    i18n.removeResourceBundle(
      langAndNs.slice(0, sep),
      langAndNs.slice(sep + 1),
    );
    i18n.addResourceBundle(
      langAndNs.slice(0, sep),
      langAndNs.slice(sep + 1),
      pristine,
      true,
      true,
    );
  });

  // The pristine restore also wiped the overrides of the modules that stay
  // enabled — put those back, in the order they applied.
  appliedI18nModules.forEach((moduleName) => {
    const module = modules.get(moduleName);
    if (module) applyModuleI18n(module);
  });

  // Drop snapshots nothing targets anymore.
  const stillTargeted = new Set<string>();
  appliedI18nModules.forEach((moduleName) => {
    const module = modules.get(moduleName);
    if (module) {
      targetedNamespaces(module).forEach((key) => stillTargeted.add(key));
    }
  });
  [...savedBundles.keys()].forEach((key) => {
    if (!stillTargeted.has(key)) savedBundles.delete(key);
  });
}

function applyI18nAdd(
  enabledModules: string[],
  modules: Map<string, FrontendModule>,
  appliedI18nModules: Set<string>,
  savedBundles: Map<string, Record<string, unknown>>,
): void {
  modules.forEach((module) => {
    if (
      enabledModules.includes(module.name) &&
      module.i18nOverrides &&
      !appliedI18nModules.has(module.name)
    ) {
      targetedNamespaces(module).forEach((langAndNs) => {
        const sep = langAndNs.indexOf(":");
        const [language, namespace] = [
          langAndNs.slice(0, sep),
          langAndNs.slice(sep + 1),
        ];
        // The pristine snapshot is taken once, before the first override
        // touches the namespace — later appliers must not overwrite it.
        // structuredClone: getResourceBundle hands back the store's own
        // object graph, which addResourceBundle would then mutate under us.
        if (!savedBundles.has(langAndNs)) {
          savedBundles.set(
            langAndNs,
            structuredClone(i18n.getResourceBundle(language, namespace) || {}),
          );
        }
        warnUnmatchedKeys(
          module,
          language,
          namespace,
          savedBundles.get(langAndNs) ?? {},
        );
      });
      applyModuleI18n(module);
      appliedI18nModules.add(module.name);
    }
  });
}

/**
 * Re-apply the standing overrides that target `namespace`.
 *
 * A module's own catalog lands in a namespace named after the module, and
 * another module's overrides may rename keys inside exactly that namespace.
 * Both writes go through `addResourceBundle` with overwrite on, so when the
 * catalog arrives after the overrides — the language chunks land in no
 * particular order — it buried them and the sidebar flipped between the two
 * names across reloads. Called after every catalog that lands in a namespace
 * an applied module targets, so a late catalog re-loses to the standing
 * overrides.
 */
function reapplyOverridesForNamespace(
  namespace: string,
  modules: Map<string, FrontendModule>,
  appliedI18nModules: Set<string>,
): void {
  const canUseI18n =
    typeof i18n?.addResourceBundle === "function" &&
    typeof i18n?.getResourceBundle === "function";
  if (!canUseI18n) return;
  appliedI18nModules.forEach((moduleName) => {
    const module = modules.get(moduleName);
    if (!module?.i18nOverrides) return;
    if (
      targetedNamespaces(module).some((langAndNs) =>
        langAndNs.endsWith(`:${namespace}`),
      )
    ) {
      applyModuleI18n(module);
    }
  });
}

/** A catalog merged into a pristine snapshot: nested maps merge key by key. */
function mergeCatalog(
  pristine: Record<string, unknown>,
  catalog: Record<string, unknown>,
): Record<string, unknown> {
  const merged: Record<string, unknown> = { ...pristine };
  Object.entries(catalog).forEach(([key, value]) => {
    const existing = merged[key];
    const bothObjects =
      typeof existing === "object" &&
      existing !== null &&
      !Array.isArray(existing) &&
      typeof value === "object" &&
      value !== null &&
      !Array.isArray(value);
    merged[key] = bothObjects
      ? mergeCatalog(
          existing as Record<string, unknown>,
          value as Record<string, unknown>,
        )
      : value;
  });
  return merged;
}

/**
 * A translation catalog landed in i18next through the dynamic backend.
 *
 * Two things follow from a catalog arriving late, and both were handled at
 * registration time before the backend owned the bundles: a standing
 * override must not be buried by it, and it becomes the pristine state a
 * removal restores — restoring the pre-catalog snapshot would take the
 * catalog's own keys down with the override.
 *
 * The backend shallow-merges a bundle over whatever the store holds, so the
 * snapshot is merged key by key with the catalog before the overrides are
 * re-applied on top of both.
 */
export function noteCatalogLanded(
  language: string,
  namespace: string,
  catalog: Record<string, unknown>,
  modules: Map<string, FrontendModule>,
  appliedI18nModules: Set<string>,
  savedBundles: Map<string, Record<string, unknown>>,
): void {
  const key = `${language}:${namespace}`;
  // The overrides applied before this language's catalog was in, so this is
  // the first moment their keys can be read against it.
  const firstCatalog = Object.keys(savedBundles.get(key) ?? {}).length === 0;
  let targeted = false;
  appliedI18nModules.forEach((moduleName) => {
    const module = modules.get(moduleName);
    if (!module?.i18nOverrides) return;
    if (!targetedNamespaces(module).includes(key)) return;
    targeted = true;
    const pristine = savedBundles.get(key);
    const merged = pristine
      ? mergeCatalog(structuredClone(pristine), catalog)
      : structuredClone(catalog);
    savedBundles.set(key, merged);
    if (firstCatalog) warnUnmatchedKeys(module, language, namespace, merged);
  });
  if (targeted) {
    reapplyOverridesForNamespace(namespace, modules, appliedI18nModules);
  }
}

export function applyI18nOverrides(
  enabledModules: string[],
  modules: Map<string, FrontendModule>,
  appliedI18nModules: Set<string>,
  savedBundles: Map<string, Record<string, unknown>>,
): void {
  const canUseI18n =
    typeof i18n?.addResourceBundle === "function" &&
    typeof i18n?.getResourceBundle === "function";
  if (!canUseI18n) return;
  applyI18nRemove(enabledModules, modules, appliedI18nModules, savedBundles);
  applyI18nAdd(enabledModules, modules, appliedI18nModules, savedBundles);
}

function applyThemeRemove(
  enabledModules: string[],
  appliedThemeModules: Set<string>,
  savedThemeVars: Map<string, Record<string, string>>,
): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  const toRemove = [...appliedThemeModules].filter(
    (m) => !enabledModules.includes(m),
  );
  toRemove.forEach((moduleName) => {
    const originals = savedThemeVars.get(moduleName);
    if (originals) {
      Object.entries(originals).forEach(([varName, original]) => {
        if (original === "") {
          root.style.removeProperty(varName);
        } else {
          root.style.setProperty(varName, original);
        }
      });
      savedThemeVars.delete(moduleName);
    }
    appliedThemeModules.delete(moduleName);
  });
}

/**
 * Apply CSS variable overrides on `<html>`, remembering the previous values.
 * Returns a cleanup function that reverts exactly the variables this call
 * touched. Shared by the module theme pipeline and the per-profile theme
 * hook (`useProfileTheme`) so both use the same save/restore semantics.
 */
export function applyThemeVariables(vars: Record<string, string>): () => void {
  if (typeof document === "undefined") return () => {};
  const root = document.documentElement;
  const originals: Record<string, string> = {};
  Object.entries(vars).forEach(([varName, value]) => {
    originals[varName] = root.style.getPropertyValue(varName) ?? "";
    root.style.setProperty(varName, value);
  });
  return () => {
    Object.entries(originals).forEach(([varName, original]) => {
      if (original === "") {
        root.style.removeProperty(varName);
      } else {
        root.style.setProperty(varName, original);
      }
    });
  };
}

function applyThemeAdd(
  enabledModules: string[],
  modules: Map<string, FrontendModule>,
  appliedThemeModules: Set<string>,
  savedThemeVars: Map<string, Record<string, string>>,
): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  modules.forEach((module) => {
    if (
      enabledModules.includes(module.name) &&
      module.theme?.cssVariables &&
      !appliedThemeModules.has(module.name)
    ) {
      const originals: Record<string, string> = {};
      Object.entries(module.theme.cssVariables).forEach(([varName, value]) => {
        originals[varName] = root.style.getPropertyValue(varName) ?? "";
        root.style.setProperty(varName, value);
      });
      savedThemeVars.set(module.name, originals);
      appliedThemeModules.add(module.name);
    }
  });
}

export function applyThemeOverrides(
  enabledModules: string[],
  modules: Map<string, FrontendModule>,
  appliedThemeModules: Set<string>,
  savedThemeVars: Map<string, Record<string, string>>,
): void {
  applyThemeRemove(enabledModules, appliedThemeModules, savedThemeVars);
  applyThemeAdd(enabledModules, modules, appliedThemeModules, savedThemeVars);
}
