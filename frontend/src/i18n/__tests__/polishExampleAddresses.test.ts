/**
 * An example address in a Polish placeholder or hint must belong to nobody.
 *
 * "kontakt@firma.pl" and "https://firma.pl" read as sample text, but firma.pl
 * is a registered domain: a user who copies the example into a form, or whose
 * browser follows it, reaches a stranger. RFC 2606 reserves example.com for
 * exactly this, and the English catalogues already speak in one reserved
 * shape. This scans the Polish catalogues that carry example addresses.
 */
import { describe, expect, it } from "vitest";

import commonPl from "@/i18n/locales/pl/common.json";
import equipmentPl from "@/modules/equipment/i18n/pl.json";
import partnersPl from "@/modules/partners/i18n/pl.json";

const ADDRESS =
  /[\w.-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+|https?:\/\/[a-z0-9-]+(?:\.[a-z0-9-]+)+/gi;
const RESERVED = /(?:@|\/\/)example\.(?:com|org|net)$/i;

function strings(value: unknown, out: string[] = []): string[] {
  if (typeof value === "string") out.push(value);
  else if (value && typeof value === "object") {
    for (const v of Object.values(value)) strings(v, out);
  }
  return out;
}

describe("example addresses in Polish copy", () => {
  const catalogues = { commonPl, equipmentPl, partnersPl };

  it.each(Object.entries(catalogues))(
    "%s uses only a domain reserved for examples",
    (_name, catalogue) => {
      const found = strings(catalogue).flatMap((s) => s.match(ADDRESS) ?? []);
      const real = found.filter((a) => !RESERVED.test(a));
      expect(real).toEqual([]);
    },
  );

  it("still carries at least one example address to guard", () => {
    const all = Object.values(catalogues).flatMap((c) =>
      strings(c).flatMap((s) => s.match(ADDRESS) ?? []),
    );
    expect(all.length).toBeGreaterThan(0);
  });
});
