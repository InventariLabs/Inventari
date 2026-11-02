import { afterEach, beforeEach, describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import i18next from "i18next";

import { withLanguage } from "@/test/mocks/i18n";
import { SUPPORTED_LANGUAGES } from "@/i18n/languages";

/**
 * A module from outside owes English and nothing else (the module guides say
 * so). The runtime keeps that promise through i18next's `fallbackLng`: a
 * module that ships only `en.json` is served an empty catalog for every other
 * language, and every key comes from English.
 *
 * The module here is a stand-in with English alone, registered the way the
 * loader in `config.ts` registers one: its English catalog under the module's
 * name, and an empty catalog for each language it has no file for.
 */

const NAMESPACE = "english_only_probe";
const HERE = path.dirname(fileURLToPath(import.meta.url));

const ENGLISH = {
  title: "Probe module",
  navigation: { title: "Probes" },
  empty: "Nothing here yet",
};

beforeEach(() => {
  for (const lang of SUPPORTED_LANGUAGES) {
    i18next.addResourceBundle(
      lang,
      NAMESPACE,
      lang === "en" ? ENGLISH : {},
      true,
      true,
    );
  }
});

afterEach(() => {
  for (const lang of SUPPORTED_LANGUAGES) {
    i18next.removeResourceBundle(lang, NAMESPACE);
  }
});

describe("a module that ships English only", () => {
  const others = SUPPORTED_LANGUAGES.filter((lang) => lang !== "en");

  it.each(others)(
    "renders in English under %s, without raw keys",
    async (lang) => {
      await withLanguage(lang, () => {
        expect(i18next.t("title", { ns: NAMESPACE })).toBe("Probe module");
        expect(i18next.t("navigation.title", { ns: NAMESPACE })).toBe("Probes");
        expect(i18next.t("empty", { ns: NAMESPACE })).toBe("Nothing here yet");
      });
    },
  );

  it("is held by the fallback the app's own i18n config sets", () => {
    const config = fs.readFileSync(path.resolve(HERE, "../config.ts"), "utf8");

    expect(config).toMatch(/fallbackLng:\s*"en"/);
  });
});
