import { describe, expect, it, vi } from "vitest";
import type { FieldDefinition } from "@/types";
import { getLabel, getPlaceholder } from "./helpers";

/**
 * Missing-key detection for dynamically resolved field labels/placeholders.
 *
 * i18next returns a missing key WITHOUT its namespace prefix, so a guard that
 * compares the result against the prefixed key never trips — and the raw key
 * leaks into the form instead of the intended fallback. These tests pin the
 * behaviour for both shapes of miss (namespaced lookup, bare lookup).
 */

/** Minimal i18next stand-in mirroring UnifiedFieldRenderer's
 *  `useTranslation(["items", "common", "categories"])`: a bare key walks the
 *  namespace chain, a prefixed key pins one namespace, and a miss echoes the
 *  key back WITHOUT its `ns:` prefix — exactly how i18next behaves.
 *  Catalog entries are keyed "<ns>:<key>". */
function makeT(catalog: Record<string, string>) {
  return vi.fn((key: string, opts?: Record<string, unknown>) => {
    const [prefix, rest] = key.includes(":")
      ? (key.split(/:(.+)/) as [string, string])
      : [null, key];
    const chain = prefix
      ? [prefix]
      : typeof opts?.ns === "string"
        ? [opts.ns]
        : ["items", "common", "categories"];
    for (const ns of chain) {
      const hit = catalog[`${ns}:${rest}`];
      if (hit !== undefined) return hit;
    }
    if (opts && typeof opts.defaultValue === "string") return opts.defaultValue;
    return rest;
  });
}

const field = (over: Partial<FieldDefinition>): FieldDefinition =>
  ({
    key: "brand",
    label: "itemBrand",
    type: "text",
    required: false,
    is_system: false,
    visible: true,
    is_custom: false,
    contexts: null,
    ...over,
  }) as FieldDefinition;

describe("getLabel", () => {
  it("resolves a bare label through the items namespace", () => {
    const t = makeT({ "items:itemBrand": "Brand" });
    expect(getLabel(field({}), t)).toBe("Brand");
  });

  it("resolves a dotted label through the items namespace", () => {
    const t = makeT({ "items:fields.purchase_price": "Purchase price" });
    expect(
      getLabel(
        field({ key: "purchase_price", label: "fields.purchase_price" }),
        t,
      ),
    ).toBe("Purchase price");
  });

  it("falls back to the common namespace when items has no such key", () => {
    const t = makeT({ "common:notes": "Notes" });
    expect(getLabel(field({ key: "notes", label: "notes" }), t)).toBe("Notes");
  });

  it("never leaks a camelCase key when it is missing everywhere", () => {
    const t = makeT({ "items:untitledField": "Untitled field" });
    expect(getLabel(field({}), t)).toBe("Untitled field");
  });

  it("never leaks a dotted key when it is missing everywhere", () => {
    const t = makeT({ "items:untitledField": "Untitled field" });
    expect(
      getLabel(
        field({ key: "purchase_price", label: "fields.purchase_price" }),
        t,
      ),
    ).toBe("Untitled field");
  });

  it("keeps a human-readable custom label as-is", () => {
    const t = makeT({});
    expect(
      getLabel(
        field({ key: "warranty", label: "Warranty until", is_custom: true }),
        t,
      ),
    ).toBe("Warranty until");
  });
});

describe("getPlaceholder", () => {
  it("resolves an explicit placeholder key", () => {
    const t = makeT({
      "items:placeholders.description": "Additional notes…",
    });
    expect(
      getPlaceholder(
        field({ key: "description", placeholder: "placeholders.description" }),
        undefined,
        t,
      ),
    ).toBe("Additional notes…");
  });

  it("falls back to the per-key placeholder in the items namespace", () => {
    const t = makeT({ "items:placeholders.brand": "e.g. Bosch" });
    expect(getPlaceholder(field({}), undefined, t)).toBe("e.g. Bosch");
  });

  it("returns an empty placeholder rather than the raw key when it is missing", () => {
    const t = makeT({});
    expect(getPlaceholder(field({}), undefined, t)).toBe("");
    expect(
      getPlaceholder(
        field({ key: "description", placeholder: "placeholders.description" }),
        undefined,
        t,
      ),
    ).toBe("");
  });

  it("picks the unit-aware quantity example", () => {
    const t = makeT({ "items:placeholders.quantityDecimal": "e.g. 1.5" });
    expect(getPlaceholder(field({ key: "quantity" }), "kg", t)).toBe(
      "e.g. 1.5",
    );
  });
});
