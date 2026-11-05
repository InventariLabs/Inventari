import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import { MAINTAINED_LANGUAGES } from "@/test/languageClasses";

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
    tabs: { roles: string; modules: string };
  };
  appStore: { title: string };
}
interface StatsNames {
  title: string;
  navigation: { settings: string };
}

function load<T>(file: string): T {
  return JSON.parse(fs.readFileSync(path.join(SRC, file), "utf8")) as T;
}

describe.each([...MAINTAINED_LANGUAGES])(
  "settings destination names (%s)",
  (lang) => {
    const common = load<CommonNames>(`i18n/locales/${lang}/common.json`);
    const stats = load<StatsNames>(`modules/stats/i18n/${lang}.json`);

    it("names the roles page the way its sidebar entry does", () => {
      expect(common.settings.rbac.title).toBe(common.settings.tabs.roles);
    });

    it("names the module store the way its sidebar entry does", () => {
      expect(common.appStore.title).toBe(common.settings.tabs.modules);
    });

    it("links the statistics settings under the module's own name", () => {
      expect(stats.navigation.settings).toBe(stats.title);
    });
  },
);
