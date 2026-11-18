/**
 * An example address in a placeholder or hint must belong to nobody.
 *
 * "kontakt@firma.pl", "person@company.com" and "https://empresa.es" read as
 * sample text, but each is a registered domain: a user who copies the example
 * into a form, or whose browser follows it, reaches a stranger. RFC 2606
 * reserves example.com, example.org and example.net for exactly this. This
 * scans every catalogue of every language, the core ones and each module's.
 */
import { describe, expect, it } from "vitest";

const ADDRESS =
  /[\w.-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+|https?:\/\/[a-z0-9-]+(?:\.[a-z0-9-]+)+/gi;
const RESERVED = /(?:@|\/\/)example\.(?:com|org|net)$/i;

const catalogues: Record<string, unknown> = {
  ...import.meta.glob("../locales/*/*.json", {
    eager: true,
    import: "default",
  }),
  ...import.meta.glob("../../modules/*/i18n/*.json", {
    eager: true,
    import: "default",
  }),
};

function strings(value: unknown, out: string[] = []): string[] {
  if (typeof value === "string") out.push(value);
  else if (value && typeof value === "object") {
    for (const v of Object.values(value)) strings(v, out);
  }
  return out;
}

const addressesIn = (catalogue: unknown) =>
  strings(catalogue).flatMap((s) => s.match(ADDRESS) ?? []);

describe("example addresses in the catalogues", () => {
  it("scans the catalogues of every language, community translations included", () => {
    const names = Object.keys(catalogues);
    for (const lang of ["de", "en", "es", "fr", "pl", "pt"]) {
      expect(names.some((n) => n.includes(`/${lang}/`))).toBe(true);
      expect(names.some((n) => n.endsWith(`/i18n/${lang}.json`))).toBe(true);
    }
  });

  it.each(Object.entries(catalogues))(
    "%s uses only a domain reserved for examples",
    (_name, catalogue) => {
      const real = addressesIn(catalogue).filter((a) => !RESERVED.test(a));
      expect(real).toEqual([]);
    },
  );

  it("still carries at least one example address to guard", () => {
    const all = Object.values(catalogues).flatMap(addressesIn);
    expect(all.length).toBeGreaterThan(0);
  });
});
