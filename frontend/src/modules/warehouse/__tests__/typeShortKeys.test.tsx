import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { render } from "@/test/utils";
import { withLanguage } from "@/test/mocks/i18n";
import { useTranslation } from "react-i18next";

import { DocumentsFilters } from "../components/DocumentsFilters";
import type { DocumentTypeFilter } from "../hooks/useDocumentsList";

import en from "../i18n/en.json";
import pl from "../i18n/pl.json";
import de from "../i18n/de.json";
import fr from "../i18n/fr.json";
import es from "../i18n/es.json";

/**
 * Regression guard.
 *
 * DocumentsFilters renders the type tabs via `t("types.${type}")` and
 * TYPE_FILTERS includes CORRECTION, but a catalogue once defined only
 * IN/OUT/INT/PW/RW/SCRAP — so i18next returned the raw key `types.CORRECTION`.
 */

const TYPES_SHORT = [
  "IN",
  "OUT",
  "INT",
  "INTERNAL_IN",
  "INTERNAL_OUT",
  "CORRECTION",
  "SCRAP",
  // No screen writes one, but one written through the API is listed and
  // opened like any other document, and it reads by name, not by code.
  "ADJUSTMENT",
] as const;

type Catalog = Record<string, unknown>;

const catalogs: Record<string, Catalog> = {
  en: en as unknown as Catalog,
  pl: pl as unknown as Catalog,
  de: de as unknown as Catalog,
  fr: fr as unknown as Catalog,
  es: es as unknown as Catalog,
};

function flatKeys(node: unknown, prefix: string[] = []): string[] {
  if (node == null) return [];
  if (typeof node === "string") return [prefix.join(".")];
  if (typeof node === "object") {
    return Object.entries(node as Catalog).flatMap(([k, v]) =>
      flatKeys(v, [...prefix, k]),
    );
  }
  return [];
}

function FiltersHarness({ typeFilter }: { typeFilter: DocumentTypeFilter }) {
  const { t } = useTranslation(["warehouse", "common"]);
  return (
    <DocumentsFilters
      search=""
      setSearch={() => {}}
      typeFilter={typeFilter}
      setTypeFilter={() => {}}
      statusFilter="ALL"
      setStatusFilter={() => {}}
      discrepancyFilter="ALL"
      setDiscrepancyFilter={() => {}}
      dateFrom=""
      setDateFrom={() => {}}
      dateTo=""
      setDateTo={() => {}}
      sortBy="document_date"
      setSortBy={() => {}}
      sortOrder="desc"
      setSortOrder={() => {}}
      t={t}
    />
  );
}

describe("documents — the type labels the screens read are present in all 5 languages", () => {
  for (const [lang, catalog] of Object.entries(catalogs)) {
    it(`${lang} defines types.${TYPES_SHORT.join(", types.")} and typesShort.${TYPES_SHORT.join(", typesShort.")}`, () => {
      const keys = new Set(flatKeys(catalog));
      for (const type of TYPES_SHORT) {
        expect(keys).toContain(`types.${type}`);
        expect(keys).toContain(`typesShort.${type}`);
      }
    });
  }
});

describe("DocumentsFilters — CORRECTION type filter", () => {
  it("renders a translated short label instead of the raw key", () => {
    render(<FiltersHarness typeFilter="CORRECTION" />);
    expect(screen.queryByText("types.CORRECTION")).not.toBeInTheDocument();
    expect(screen.queryByText("typesShort.CORRECTION")).not.toBeInTheDocument();
    // Spelled out: "CORR" was the only abbreviation in a row of full names.
    expect(screen.getAllByText("Correction").length).toBeGreaterThan(0);
    expect(screen.queryByText("CORR")).not.toBeInTheDocument();
  });
});

/**
 * The list's type tabs are where a reader narrows the register to one kind of
 * work, so they say what the type IS.
 *
 * They read `typesShort`, which in Polish is the paperwork code alone — "PZ",
 * "WZ", "MM" — while the same catalogue held "Przyjęcie (PZ)" one key over.
 * English got full names out of the same tabs, so only Polish was encrypted:
 * a reader whose organization runs the "home" profile is never assumed to
 * have warehouse training. The dense register rows keep `typesShort`
 * deliberately (see warehouse/types.ts).
 */
describe("DocumentsFilters — the type tabs name the type, with its code", () => {
  it("reads the Polish name with the code in brackets (pl)", async () => {
    await withLanguage("pl", async () => {
      render(<FiltersHarness typeFilter="ALL" />);
      expect(screen.getAllByText("Przyjęcie (PZ)").length).toBeGreaterThan(0);
      expect(screen.getAllByText("Wydanie (WZ)").length).toBeGreaterThan(0);
      // The code alone is not a tab any more.
      expect(screen.queryAllByText("PZ")).toHaveLength(0);
      expect(screen.queryAllByText("WZ")).toHaveLength(0);
    });
  });

  it("keeps the bare name in the languages that never had a code (en)", () => {
    render(<FiltersHarness typeFilter="ALL" />);
    expect(screen.getAllByText("Receipt").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Delivery").length).toBeGreaterThan(0);
  });
});

/**
 * One shape per catalogue.
 *
 * `types.<CODE>` was "Złomowanie" in Polish — the only long name there
 * without its paperwork code — while "Correction (CORR)" was the only
 * bracketed English one, and German, French and Spanish repeated it. Both
 * halves of the pair drifted from their siblings, and the drift was invisible
 * because nothing compared the seven entries with each other.
 *
 * The rule the catalogues now hold to, per language: either every long name
 * carries its code in brackets and the short name IS that code, or no long
 * name carries one and the short name is the long name with nothing to strip.
 * Polish keeps the codes (PZ, WZ, MM, PW, RW, KOR, ZL — the same ones the
 * PL Magazyn profile numbers documents with); the other four languages use
 * the bare name in both keys.
 */
const CODE_IN_BRACKETS = /\s*\(([A-ZŁ]{2,4})\)$/;

function longName(catalog: Catalog, type: string): string {
  const value = (catalog.types as Record<string, string>)[type];
  expect(typeof value).toBe("string");
  return value;
}

describe("documents — the type names have one shape per language", () => {
  for (const [lang, catalog] of Object.entries(catalogs)) {
    it(`${lang} pairs every code with its name, or none of them`, () => {
      const longs = TYPES_SHORT.map((type) => longName(catalog, type));
      const shorts = TYPES_SHORT.map(
        (type) => (catalog.typesShort as Record<string, string>)[type],
      );
      const codes = longs.map((value) => value.match(CODE_IN_BRACKETS)?.[1]);

      if (codes.every((code) => code !== undefined)) {
        // The code convention: the short name is exactly the code.
        expect(shorts).toEqual(codes);
      } else {
        // The word convention: no long name may carry a stray code, and the
        // short name is the long name without one.
        expect(codes).toEqual(longs.map(() => undefined));
        expect(shorts).toEqual(
          longs.map((value) => value.replace(CODE_IN_BRACKETS, "")),
        );
      }
    });
  }
});
