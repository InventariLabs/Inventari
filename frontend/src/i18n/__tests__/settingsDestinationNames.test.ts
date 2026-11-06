import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import { MAINTAINED_LANGUAGES } from "@/test/languageClasses";
import { moduleRegistry } from "@/lib/moduleRegistry";

// Registering every real module, the same way App.tsx does.
import.meta.glob("../../modules/*/module.ts", { eager: true });

/**
 * A settings destination has one name: the sidebar entry a reader clicks and
 * the heading of the page it opens must read the same in every language.
 * The German sidebar once said "Rollen & Rechte" over a page headed "Zugriff
 * und Rollen", the Statistics module was linked as "Analytics", and the
 * module store was reached as "Modules" but headed "App Store".
 */
const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(HERE, "../..");

interface CommonNames {
  settings: {
    rbac: { title: string };
    audit: { title: string };
    tabs: { roles: string; modules: string; auditLog: string };
  };
  appStore: { title: string };
}
interface ModuleNames {
  modules: Record<string, { name: string }>;
}

function load<T>(file: string): T {
  return JSON.parse(fs.readFileSync(path.join(SRC, file), "utf8")) as T;
}

function lookup(catalogue: unknown, dotted: string): string | undefined {
  let node = catalogue;
  for (const segment of dotted.split(".")) {
    node =
      node && typeof node === "object"
        ? (node as Record<string, unknown>)[segment]
        : undefined;
  }
  return typeof node === "string" ? node : undefined;
}

/**
 * Every module that links a generic module-settings page from the settings
 * sidebar (`settingsSections` under `modules/<name>`): the sidebar entry's
 * title key, and the module whose display name heads the page it opens
 * (ModuleSettingsPage reads `modules:modules.<name>.name`). Read from the
 * registry, so a module added later is held to the same rule.
 */
function moduleSettingsPairs(): {
  module: string;
  namespace: string;
  key: string;
}[] {
  const pairs: { module: string; namespace: string; key: string }[] = [];
  for (const module of moduleRegistry.getAllRegisteredModules()) {
    for (const section of moduleRegistry.getModule(module)?.settingsSections ??
      []) {
      if (section.path !== `modules/${module}`) continue;
      const [namespace, key] = section.title.split(":");
      pairs.push({ module, namespace, key });
    }
  }
  return pairs;
}

describe("module settings destinations are found by the registry", () => {
  it("lists the modules whose sidebar entry opens the generic page", () => {
    expect(moduleSettingsPairs().map((p) => p.module)).toEqual(
      expect.arrayContaining(["approvals", "stats"]),
    );
  });
});

describe.each([...MAINTAINED_LANGUAGES])(
  "settings destination names (%s)",
  (lang) => {
    const common = load<CommonNames>(`i18n/locales/${lang}/common.json`);
    const moduleNames = load<ModuleNames>(`i18n/locales/${lang}/modules.json`);

    it("names the roles page the way its sidebar entry does", () => {
      expect(common.settings.rbac.title).toBe(common.settings.tabs.roles);
    });

    it("names the module store the way its sidebar entry does", () => {
      expect(common.appStore.title).toBe(common.settings.tabs.modules);
    });

    it("names the audit log the way its sidebar entry does", () => {
      expect(common.settings.audit.title).toBe(common.settings.tabs.auditLog);
    });

    it("heads each module settings page with its sidebar entry's name", () => {
      for (const { module, namespace, key } of moduleSettingsPairs()) {
        const sidebar = lookup(
          load<unknown>(`modules/${namespace}/i18n/${lang}.json`),
          key,
        );
        expect(sidebar, `${module}: ${namespace}:${key}`).toBe(
          moduleNames.modules[module].name,
        );
      }
    });
  },
);
