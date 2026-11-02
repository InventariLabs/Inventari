import { describe, expect, it } from "vitest";

import i18n from "@/test/mocks/i18n";
import type { TranslateFn } from "@/types/i18n";

import { categoryLabel } from "../i18nHelpers";

const t = i18n.t.bind(i18n) as unknown as TranslateFn;

describe("categoryLabel", () => {
  it("names a seeded category from the catalogue, in the reader's language", async () => {
    expect(categoryLabel(t, "deli", "Deli")).toBe("Cold cuts");

    await withLanguagePl(() => {
      expect(categoryLabel(t, "deli", "Deli")).toBe("Wędliny");
    });
  });

  it("keeps the record's name when the category has no code", () => {
    expect(categoryLabel(t, null, "Homemade sauces")).toBe("Homemade sauces");
    expect(categoryLabel(t, undefined, "Homemade sauces")).toBe(
      "Homemade sauces",
    );
  });

  it("keeps the record's name when the catalogue has never heard of the code", () => {
    expect(categoryLabel(t, "no_such_code", "Fallback name")).toBe(
      "Fallback name",
    );
  });

  it("names an equipment category from the shared catalogue, in the reader's language", async () => {
    // The core picker resolves through the shared catalogue, and a record
    // seeded by the equipment module stands beside food categories in the
    // same picker — "Komputer stacjonarny" beside "Nabiał", or neither reads
    // like their reader's language.
    expect(categoryLabel(t, "DESKTOP", "Desktop Computer")).toBe(
      "Desktop Computer",
    );

    await withLanguagePl(() => {
      expect(categoryLabel(t, "DESKTOP", "Desktop Computer")).toBe(
        "Komputer stacjonarny",
      );
      expect(categoryLabel(t, "OTHER_EQUIPMENT", "Other Equipment")).toBe(
        "Inny sprzęt",
      );
    });
  });

  /** withLanguage from the i18n test mock, under its own name here. */
  async function withLanguagePl(body: () => void) {
    const { withLanguage } = await import("@/test/mocks/i18n");
    await withLanguage("pl", body);
  }
});
