import { describe, expect, it } from "vitest";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { MAINTAINED_LANGUAGES } from "@/test/languageClasses";
import "@/modules/settings/module";

const catalogs = import.meta.glob("/src/i18n/locales/*/common.json", {
  eager: true,
  import: "default",
}) as Record<string, { navigation: Record<string, string> }>;

describe("the Settings tile on the launcher", () => {
  it("carries a one-line description like the tiles beside it", () => {
    const tile = moduleRegistry.getModule("settings")?.launcher;
    expect(tile?.description).toBe("common:navigation.settingsDescription");
  });

  it("has that description in every maintained language", () => {
    for (const lang of MAINTAINED_LANGUAGES) {
      const text =
        catalogs[`/src/i18n/locales/${lang}/common.json`]?.navigation
          .settingsDescription;
      expect(text, lang).toBeTruthy();
    }
  });
});
